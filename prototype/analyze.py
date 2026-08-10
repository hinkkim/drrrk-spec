#!/usr/bin/env python3
"""드르륵 자산 분석 엔진 — 실물자산·귀금속 분석 프로그램 (CLI).

자산을 입력하면 원장 데이터에서 분석 결과를 산출한다:
식별 → 시세(MV) → 매입가/청산가치(LV) → 유동성 → 권장 LTV.

사용법:
  python3 analyze.py list                              # 분석 가능한 자산 목록
  python3 analyze.py asset WATCH-ROLEX-SUBMARINER-126610LN --grade A
  python3 analyze.py asset "서브마리너"                 # 별칭·모델명 검색도 가능
  python3 analyze.py gold --purity 18K --weight 18.75  # 귀금속 (금 시세 기반)
  python3 analyze.py gold --purity 24K --weight 37.5 --spot 152000

귀금속 vs 브랜드 자산의 차이가 곧 이 프로그램의 논리다:
  금은 표준화 자산 → 시세 × 순도 × 중량으로 즉시 계산된다 (은행이 이미 담보로 받는 이유).
  명품은 비표준 자산 → 모델·상태별 실거래 원장이 있어야만 같은 답을 낼 수 있다 (드르륵의 존재 이유).
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

from metrics import _pct, DISPOSAL_COST
from simulate import GRADE_MULT

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "drrrk_ledger.db")

PURITY = {"24K": 0.999, "22K": 0.916, "18K": 0.750, "14K": 0.585}
GOLD_BUY_SPREAD = 0.05   # 귀금속 매입 스프레드 (실측으로 교체할 것)
GOLD_LTV = 0.80          # 표준화 자산의 관행적 담보 비율 (참고치)
MIN_SAMPLE = 5


def connect():
    if not os.path.exists(DB):
        sys.exit("원장 DB가 없습니다. 먼저 `python3 run.py`(시뮬레이션) 또는 "
                 "`python3 ingest.py`(실데이터 입력)로 원장을 만드세요.")
    return sqlite3.connect(DB)


# ── 브랜드 자산 분석 (원장 기반) ─────────────────────────────────────────
def find_asset(conn, query):
    """canonical ID 정확 일치 → 별칭/브랜드/모델 부분 일치 순으로 검색."""
    row = conn.execute("select canonical_asset_id from asset_master where "
                       "canonical_asset_id=?", (query,)).fetchone()
    if row:
        return row[0], []
    like = f"%{query}%"
    rows = conn.execute(
        "select canonical_asset_id from asset_master where aliases like ? "
        "or model like ? or brand||' '||model like ?", (like, like, like)).fetchall()
    if len(rows) == 1:
        return rows[0][0], []
    return None, [r[0] for r in rows]


def analyze_asset(conn, cid, grade="A", window_days=180, as_of=None):
    as_of = as_of or _latest_date(conn)
    since = (as_of - timedelta(days=window_days)).isoformat()
    meta = conn.execute("select category, brand, model, reference_no from asset_master "
                        "where canonical_asset_id=?", (cid,)).fetchone()
    if not meta:
        return {"error": f"미등록 자산: {cid}"}
    cat, brand, model, ref = meta

    ext = _values(conn, cid, "external_comp", since)
    sales = _values(conn, cid, "contract_price", since, deal="sale")
    quotes = _values(conn, cid, "buyer_quote", since, deal="sale", exclude_fake=True)

    gm = GRADE_MULT.get(grade, 1.0)  # 원장은 등급 혼합 → A등급 기준으로 정규화 후 조정
    mv = _pct(ext + sales, 0.5)
    lv50, lv25, p10 = _pct(quotes, 0.5), _pct(quotes, 0.25), _pct(quotes, 0.10)
    n = len(quotes)
    days_to_sale = conn.execute(
        "select avg(json_extract(meta,'$.days_to_sale')) from valuation_event "
        "where event_type='contract_price' and canonical_asset_id=? and observed_at>=?",
        (cid, since)).fetchone()[0]
    rec = conn.execute(
        "select avg(value_krw*100.0/json_extract(meta,'$.loan_balance')),"
        " avg(json_extract(meta,'$.days_to_liquidate')), count(*) from valuation_event "
        "where event_type in ('backfill_liquidation','liquidation_price') "
        "and canonical_asset_id=?", (cid,)).fetchone()

    out = {
        "asset": {"canonical_asset_id": cid, "category": cat, "brand": brand,
                  "model": model, "reference_no": ref, "grade": grade},
        "as_of": as_of.isoformat(), "window_days": window_days,
        "market_value_krw": _g(mv, gm),
        "liquidation_value_krw": _g(lv50, gm),
        "liquidation_value_p25_krw": _g(lv25, gm),
        "wholesale_discount_pct": round((1 - lv50 / mv) * 100, 1) if mv and lv50 else None,
        "bid_spread_pct": (round((_pct(quotes, 0.9) - p10) / lv50 * 100, 1)
                           if lv50 and n >= MIN_SAMPLE else None),
        "expected_days_to_sale": round(days_to_sale, 1) if days_to_sale else None,
        "recovery_rate_pct": round(rec[0], 1) if rec[0] else None,
        "days_to_liquidate": round(rec[1], 1) if rec[1] else None,
        "recommended_ltv_pct": (round(p10 * (1 - DISPOSAL_COST) / mv * 100, 1)
                                if mv and p10 and n >= MIN_SAMPLE else None),
        "sample": {"external_comps": len(ext), "sales": len(sales), "quotes": n,
                   "liquidations": rec[2]},
        "confidence": "high" if n >= 30 else "medium" if n >= MIN_SAMPLE else
                      "insufficient",
    }
    if out["confidence"] == "insufficient":
        out["note"] = ("표본 부족 — 가격 산출 불가. 비교견적으로 실호가를 수집하거나 "
                       "ingest.py로 실거래 데이터를 입력하세요.")
    return out


def _values(conn, cid, etype, since, deal=None, exclude_fake=False):
    q = ("select value_krw, meta from valuation_event where event_type=? "
         "and canonical_asset_id=? and observed_at>=?")
    args = [etype, cid, since]
    if deal:
        q += " and deal_type=?"
        args.append(deal)
    out = []
    for v, m in conn.execute(q, args):
        if exclude_fake and json.loads(m or "{}").get("flagged_fake"):
            continue
        out.append(v)
    return out


def _latest_date(conn):
    row = conn.execute("select max(observed_at) from valuation_event").fetchone()
    return date.fromisoformat(row[0][:10]) if row and row[0] else date.today()


def _g(v, gm):
    return int(v * gm) if v is not None else None


# ── 귀금속 분석 (시세 기반 — 표준화 자산) ─────────────────────────────────
def analyze_gold(purity, weight_g, spot=None, conn=None):
    if spot is None and conn is not None:
        row = conn.execute("select krw_per_g, updated_at from spot_price "
                           "where metal='gold'").fetchone() if _has_spot(conn) else None
        if row:
            spot, spot_at = row
        else:
            return {"error": "금 시세가 없습니다. --spot <24K 1g당 원> 을 지정하거나 "
                             "`python3 ingest.py spot gold <가격>` 으로 저장하세요. "
                             "(참고: 한국금거래소 고시가)"}
    else:
        spot_at = "manual"
    factor = PURITY.get(purity.upper())
    if not factor:
        return {"error": f"지원 순도: {', '.join(PURITY)} (입력: {purity})"}
    mv = spot * factor * weight_g
    lv = mv * (1 - GOLD_BUY_SPREAD)
    return {
        "asset": {"type": "GOLD", "purity": purity.upper(), "weight_g": weight_g},
        "spot_krw_per_g_24k": int(spot), "spot_as_of": spot_at,
        "market_value_krw": int(mv),
        "liquidation_value_krw": int(lv),
        "wholesale_discount_pct": round(GOLD_BUY_SPREAD * 100, 1),
        "recommended_ltv_pct": round(GOLD_LTV * 100, 1),
        "confidence": "high",
        "note": "표준화 자산 — 시세×순도×중량으로 직접 산출. "
                "스프레드·LTV 관행값은 실측으로 교체할 것.",
    }


def _has_spot(conn):
    return conn.execute("select count(*) from sqlite_master where type='table' "
                        "and name='spot_price'").fetchone()[0] > 0


# ── 출력 ──────────────────────────────────────────────────────────────────
def print_result(r):
    if "error" in r:
        sys.exit(f"오류: {r['error']}")
    a = r["asset"]
    name = (f"{a['brand']} {a['model']} ({a.get('reference_no') or '-'}) · 등급 {a['grade']}"
            if "brand" in a else f"금 {a['purity']} {a['weight_g']}g")
    w = lambda v: f"₩{v:,}" if v is not None else "— (표본 부족)"
    p = lambda v: f"{v}%" if v is not None else "—"
    print(f"\n■ {name}")
    print(f"  시장가치(MV)        {w(r['market_value_krw'])}")
    print(f"  청산가치(LV)        {w(r['liquidation_value_krw'])}"
          + (f"   (보수적 P25 {w(r['liquidation_value_p25_krw'])})"
             if r.get("liquidation_value_p25_krw") is not None else ""))
    print(f"  도매할인율          {p(r.get('wholesale_discount_pct'))}")
    if "bid_spread_pct" in r:
        print(f"  호가 스프레드       {p(r.get('bid_spread_pct'))}")
        print(f"  예상 처분 소요      {r.get('expected_days_to_sale') or '—'}일 (판매) / "
              f"{r.get('days_to_liquidate') or '—'}일 (유질)")
        print(f"  유질 회수율         {p(r.get('recovery_rate_pct'))}")
    print(f"  권장 LTV            {p(r.get('recommended_ltv_pct'))}")
    if "sample" in r:
        s = r["sample"]
        print(f"  근거 표본           호가 {s['quotes']} · 성사 {s['sales']} · "
              f"외부시세 {s['external_comps']} · 유질처분 {s['liquidations']} "
              f"(최근 {r['window_days']}일, 기준일 {r['as_of']})")
    print(f"  신뢰도              {r['confidence']}")
    if r.get("note"):
        print(f"  ※ {r['note']}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="분석 가능한 자산 목록")
    pa = sub.add_parser("asset", help="브랜드 자산 분석 (원장 기반)")
    pa.add_argument("query", help="canonical ID 또는 모델명/별칭")
    pa.add_argument("--grade", default="A", choices=list(GRADE_MULT))
    pa.add_argument("--json", action="store_true", help="JSON으로 출력 (API 연동용)")
    pg = sub.add_parser("gold", help="귀금속(금) 분석 — 시세 기반")
    pg.add_argument("--purity", default="24K")
    pg.add_argument("--weight", type=float, required=True, help="중량(g)")
    pg.add_argument("--spot", type=float, help="24K 1g당 시세(원). 생략 시 DB 저장값 사용")
    pg.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cmd == "list":
        conn = connect()
        for cid, b, m in conn.execute("select canonical_asset_id, brand, model "
                                      "from asset_master order by category, brand"):
            n = conn.execute("select count(*) from valuation_event where "
                             "canonical_asset_id=? and event_type='buyer_quote'",
                             (cid,)).fetchone()[0]
            print(f"  {cid:45s} {b} {m}  (호가 {n}건)")
        return

    if args.cmd == "asset":
        conn = connect()
        cid, candidates = find_asset(conn, args.query)
        if not cid:
            if candidates:
                sys.exit("검색 결과가 여러 개입니다:\n  " + "\n  ".join(candidates))
            sys.exit(f"'{args.query}' 를 찾지 못했습니다. `python3 analyze.py list` 로 확인하세요.")
        r = analyze_asset(conn, cid, grade=args.grade)
    else:
        conn = sqlite3.connect(DB) if os.path.exists(DB) else None
        r = analyze_gold(args.purity, args.weight, spot=args.spot, conn=conn)

    if getattr(args, "json", False):
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_result(r)


if __name__ == "__main__":
    main()
