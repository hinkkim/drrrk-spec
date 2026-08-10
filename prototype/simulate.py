"""거래 시뮬레이터 — 원장에 4개 가격 레이어의 이벤트를 생성한다.

  ① 중고 거래 시세 (retail)     : external_comp (주간, KREAM/Chrono24 모사)
  ② 매입/위탁 호가 (wholesale)  : buyer_quote (deal_type=sale) — LV 직접 관측치
  ③ 담보 거래 가치              : backfill_appraisal/loan (전당포 과거 장부 백필 모사)
  ④ 회수율                     : backfill_liquidation (처분가·소요일·비용 meta)

가격 구조 (시뮬레이션 가정):
  retail(t)   = base_retail × drift(t)                  # 주간 랜덤워크 + 카테고리 추세
  grade_mult  = S 1.08 / A 1.00 / B 0.88 / C 0.72
  wholesale   = retail × grade_mult × (1 − discount)    # discount: WATCH 15%, BAG 25%, JWL 22%
  quote       = wholesale × (1 + N(0, 0.05))            # 바이어별 노이즈
  성사가      = max(quote) 근방
  ai_estimate = '관측된' 모델의 retail × 관측 grade_mult × (1 + N(0, 0.10))
                → 오식별 시 엉뚱한 모델 가격이 나온다 (1차 단계 오류의 전파 경로)
"""
import json
import math
import random
import sqlite3
import uuid
from datetime import date, timedelta

from identify import identify_mock

GRADE_MULT = {"S": 1.08, "A": 1.00, "B": 0.88, "C": 0.72}
GRADE_DIST = [("S", 0.10), ("A", 0.40), ("B", 0.35), ("C", 0.15)]
WHOLESALE_DISCOUNT = {"WATCH": 0.15, "BAG": 0.25, "JWL": 0.22}
CATEGORY_TREND_WK = {"WATCH": 0.0005, "BAG": 0.001, "JWL": 0.0002}  # 주간 추세
WEEKLY_VOL = 0.008
START = date(2025, 8, 11)  # 시뮬레이션 시작일 (월요일)


def _pick_grade(rng):
    r, acc = rng.random(), 0.0
    for g, p in GRADE_DIST:
        acc += p
        if r < acc:
            return g
    return "C"


def _ev(cur, instance_id, canonical, deal_type, event_type, value, day, source, meta=None):
    cur.execute(
        "insert into valuation_event (event_id, instance_id, canonical_asset_id, deal_type,"
        " event_type, value_krw, observed_at, source, meta) values (?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), instance_id, canonical, deal_type, event_type,
         int(value), day.isoformat(), source, json.dumps(meta or {}, ensure_ascii=False)))


def load_catalog(conn):
    cur = conn.execute("select canonical_asset_id, category, brand, model, reference_no "
                       "from asset_master")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run_simulation(conn, days=365, listings_per_day=2.0, seed=42,
                   id_accuracy=0.95, grade_accuracy=0.80, fake_detection=0.90,
                   counterfeit_rate=0.02, sale_conversion=0.60,
                   backfill_pawn_deals=300):
    rng = random.Random(seed)
    cur = conn.cursor()
    catalog = load_catalog(conn)
    weights = {a["canonical_asset_id"]: p for a, p in
               [(a, pop) for a, pop in zip(catalog, _popularities(conn, catalog))]}
    retail = {a["canonical_asset_id"]: _base_retail(conn, a["canonical_asset_id"])
              for a in catalog}
    stats = {"listings": 0, "fake_rejected": 0, "fake_leaked": 0,
             "quotes": 0, "sales": 0, "user_confirms": 0}

    # ── ③④ 전당포 과거 장부 백필 (담보 가치 + 회수율 데이터) ──
    for _ in range(backfill_pawn_deals):
        asset = _weighted_choice(rng, catalog, weights)
        cid = asset["canonical_asset_id"]
        g = _pick_grade(rng)
        past = START - timedelta(days=rng.randint(30, 730))
        appraisal = retail[cid] * GRADE_MULT[g] * rng.uniform(0.92, 1.05)
        ltv = rng.uniform(0.50, 0.70)
        loan = appraisal * ltv
        iid = str(uuid.uuid4())
        cur.execute("insert into asset_instance (instance_id, canonical_asset_id, grade,"
                    " source) values (?,?,?,?)", (iid, cid, g, "backfill"))
        _ev(cur, iid, cid, "pawn", "backfill_appraisal", appraisal, past, "backfill:p1",
            {"grade": g})
        _ev(cur, iid, cid, "pawn", "backfill_loan", loan, past, "backfill:p1",
            {"ltv": round(ltv, 3)})
        if rng.random() < 0.15:  # 디폴트 → 유질 처분
            w = retail[cid] * GRADE_MULT[g] * (1 - WHOLESALE_DISCOUNT[asset["category"]])
            liq = w * rng.uniform(0.88, 0.98)  # fire-sale 추가 할인
            d2l = rng.randint(14, 45)
            _ev(cur, iid, cid, "pawn", "backfill_liquidation", liq,
                past + timedelta(days=rng.randint(95, 200)), "backfill:p1",
                {"loan_balance": int(loan * rng.uniform(1.0, 1.08)),
                 "days_to_liquidate": d2l, "cost_pct": 0.05})

    # ── 일별 시뮬레이션 ──
    for d in range(days):
        day = START + timedelta(days=d)
        wk = d // 7

        # ① 중고 거래 시세: 주 1회 external_comp + 시세 랜덤워크
        if d % 7 == 0:
            for a in catalog:
                cid = a["canonical_asset_id"]
                retail[cid] *= 1 + CATEGORY_TREND_WK[a["category"]] + rng.gauss(0, WEEKLY_VOL)
                _ev(cur, None, cid, "external", "external_comp",
                    retail[cid] * rng.uniform(0.98, 1.02), day, "ext:market",
                    {"week": wk})

        # 신규 등록 (poisson 근사)
        n = _poisson(rng, listings_per_day)
        for _ in range(n):
            true_asset = _weighted_choice(rng, catalog, weights)
            tcid = true_asset["canonical_asset_id"]
            tg = _pick_grade(rng)
            is_fake = rng.random() < counterfeit_rate

            # ── 1차 단계: 식별·상태·정가품 ──
            r = identify_mock(true_asset, tg, is_fake, catalog, rng,
                              id_accuracy=id_accuracy, grade_accuracy=grade_accuracy,
                              fake_detection=fake_detection)
            if r.fake_detected:
                stats["fake_rejected"] += 1
                continue
            if is_fake:
                stats["fake_leaked"] += 1
            if r.needs_user_confirm:
                stats["user_confirms"] += 1  # 유저 선택 UI 폴백 (정답 선택 가정 80%)
                if rng.random() < 0.80:
                    r.canonical_asset_id = tcid
            ocid = r.canonical_asset_id
            stats["listings"] += 1

            iid = str(uuid.uuid4())
            cur.execute("insert into asset_instance (instance_id, canonical_asset_id, grade,"
                        " source, listing_id) values (?,?,?,?,?)",
                        (iid, ocid, r.grade, "drrrk", f"L{d}-{stats['listings']}"))
            cur.execute("insert into sim_truth values (?,?,?,?,?,?,?,?)",
                        (iid, tcid, ocid, tg, r.grade, int(is_fake),
                         int(r.fake_detected), r.confidence))

            # AI 추정(예상 성사가 기준): '관측된' 모델·등급으로 산출 → 오식별이면 엉뚱한 가격
            ocat = next(a["category"] for a in catalog if a["canonical_asset_id"] == ocid)
            est = (retail[ocid] * GRADE_MULT[r.grade]
                   * (1 - WHOLESALE_DISCOUNT[ocat]) * (1 + rng.gauss(0, 0.08)))
            _ev(cur, iid, ocid, "sale", "ai_estimate", est, day, "ledger:v0",
                {"basis": "expected_sale_price", "low": int(est * 0.9),
                 "high": int(est * 1.1), "confidence": r.confidence})

            # ② 매입/위탁 호가: 바이어는 실물을 보므로 '진짜' 모델·등급으로 가격을 낸다
            true_wholesale = (retail[tcid] * GRADE_MULT[tg]
                              * (1 - WHOLESALE_DISCOUNT[true_asset["category"]]))
            if is_fake:
                true_wholesale *= 0.05  # 가품: 바이어 검수에서 사실상 거래 불가 호가
            quotes = []
            for b in range(_poisson(rng, 3.5, lo=1, hi=7)):
                q = true_wholesale * (1 + rng.gauss(0, 0.05))
                quotes.append(q)
                _ev(cur, iid, ocid, "sale", "buyer_quote", q, day, f"buyer:{b+1}",
                    {"flagged_fake": bool(is_fake)})
                stats["quotes"] += 1

            # 판매 성사 → 처분 실측 (등록→성사 소요일 포함)
            if quotes and not is_fake and rng.random() < sale_conversion:
                price = max(quotes) * rng.uniform(0.99, 1.01)
                d2s = min(days - d - 1, _poisson(rng, 6, lo=1, hi=21))
                _ev(cur, iid, ocid, "sale", "contract_price", price,
                    day + timedelta(days=d2s), "drrrk",
                    {"days_to_sale": d2s})
                stats["sales"] += 1

    conn.commit()
    return stats


# ── 헬퍼 ──────────────────────────────────────────────────────────────────
def _poisson(rng, lam, lo=0, hi=None):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            break
        k += 1
    if hi is not None:
        k = min(k, hi)
    return max(lo, k)


def _weighted_choice(rng, catalog, weights):
    total = sum(weights[a["canonical_asset_id"]] for a in catalog)
    r, acc = rng.uniform(0, total), 0.0
    for a in catalog:
        acc += weights[a["canonical_asset_id"]]
        if r <= acc:
            return a
    return catalog[-1]


def _popularities(conn, catalog):
    rows = dict(conn.execute("select canonical_asset_id, popularity from _seed_meta"))
    return [rows[a["canonical_asset_id"]] for a in catalog]


def _base_retail(conn, cid):
    return conn.execute("select base_retail_krw from _seed_meta where canonical_asset_id=?",
                        (cid,)).fetchone()[0]
