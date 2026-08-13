#!/usr/bin/env python3
"""시뮬레이션 결과 웹 대시보드 생성.

사용법:
  python3 dashboard.py          # 원장 DB가 없으면 기본 시뮬레이션 먼저 실행
  → reports/dashboard.html 생성 (브라우저로 열면 됨. 서버 불필요, 단일 파일)

포함 내용:
  - 스탯 타일 (등록/이벤트/성사/가품 차단/오염도)
  - 가격 4레이어 차트: 중고 거래 시세(주간) · 매입 호가(도매) · 판매 성사가 — 자산 선택 가능
  - 1차 단계(식별 정확도) 시나리오 비교 소형 다중 차트
  - Asset Score 전체 테이블 (회수율·처분일·권장 LTV 포함)
"""
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulate import run_simulation, START
from metrics import compute_metrics
from report import asset_scores, pollution_stats, overall_mape

HERE = os.path.dirname(os.path.abspath(__file__))   # sim/
ROOT = os.path.dirname(HERE)                        # prototype/
DB = os.path.join(ROOT, "drrrk_sim.db")
DAYS = 365
COMPARE_SEEDS = 3


def ensure_db():
    if os.path.exists(DB):
        return sqlite3.connect(DB)
    from run import init_db
    conn = init_db(DB)
    run_simulation(conn, days=DAYS, listings_per_day=2.0, seed=42)
    compute_metrics(conn, as_of=START + timedelta(days=DAYS))
    return conn


def day_offset(iso):
    return (date.fromisoformat(iso[:10]) - START).days


def asset_series(conn, cid, days=DAYS):
    retail = [{"d": day_offset(t), "v": int(v)} for t, v in conn.execute(
        "select observed_at, avg(value_krw) from valuation_event "
        "where event_type='external_comp' and canonical_asset_id=? "
        "group by observed_at order by observed_at", (cid,)) if day_offset(t) <= days]
    quotes = [{"d": day_offset(t), "v": int(v)} for t, v in conn.execute(
        "select observed_at, value_krw from valuation_event "
        "where event_type='buyer_quote' and deal_type='sale' and canonical_asset_id=? "
        "and json_extract(meta,'$.flagged_fake')=0", (cid,))]
    sales = [{"d": day_offset(t), "v": int(v)} for t, v in conn.execute(
        "select observed_at, value_krw from valuation_event "
        "where event_type='contract_price' and deal_type='sale' and canonical_asset_id=?",
        (cid,))]
    # 오귀속(오식별) 이상치는 차트 스케일 보호를 위해 클리핑하되 개수는 표기
    med = median([p["v"] for p in retail]) if retail else 0
    def clip(pts):
        kept = [p for p in pts if med and 0.35 * med <= p["v"] <= 1.6 * med]
        return kept, len(pts) - len(kept)
    quotes, q_out = clip(quotes)
    sales, s_out = clip(sales)
    return {"retail": retail, "quotes": quotes, "sales": sales,
            "outliers": q_out + s_out}


def run_compare():
    from run import init_db
    out = []
    for acc in (0.85, 0.95, 0.99):
        agg = {"polluted": [], "mape": [], "spread": [], "ltv": []}
        for s in range(COMPARE_SEEDS):
            db = os.path.join(ROOT, f"_cmp_{int(acc*100)}_{s}.db")
            conn = init_db(db)
            run_simulation(conn, days=DAYS, listings_per_day=2.0, seed=42 + s,
                           id_accuracy=acc)
            compute_metrics(conn, as_of=START + timedelta(days=DAYS))
            p, m = pollution_stats(conn), overall_mape(conn)
            agg["polluted"].append(p["polluted_price_events_pct"])
            agg["mape"].append(m["mape_pct"])
            agg["spread"].append(m["spread_pct"])
            agg["ltv"].append(m["avg_ltv_pct"])
            conn.close()
            os.remove(db)
        out.append({"acc": int(acc * 100),
                    **{k: round(sum(v) / len(v), 1) for k, v in agg.items()}})
    return out


def build_payload():
    conn = ensure_db()
    scores = asset_scores(conn)
    poll = pollution_stats(conn)
    stats_row = conn.execute(
        "select (select count(*) from asset_instance where source='drrrk'),"
        " (select count(*) from valuation_event),"
        " (select count(*) from valuation_event where event_type='buyer_quote'),"
        " (select count(*) from valuation_event where event_type='contract_price'"
        "  and deal_type='sale')").fetchone()
    top = [s for s in scores if s["sample_size"] >= 30][:6]
    assets = []
    for s in top:
        cid = s["canonical_asset_id"]
        assets.append({"cid": cid, "name": f"{s['brand']} {s['model']}",
                       "score": s, **asset_series(conn, cid)})
    rec = conn.execute(
        "select count(*), avg(value_krw*100.0/json_extract(meta,'$.loan_balance')),"
        " avg(json_extract(meta,'$.days_to_liquidate')) from valuation_event "
        "where event_type in ('backfill_liquidation','liquidation_price')").fetchone()
    payload = {
        "days": DAYS,
        "stats": {"listings": stats_row[0], "events": stats_row[1],
                  "quotes": stats_row[2], "sales": stats_row[3]},
        "pollution": poll,
        "recovery": {"n": rec[0], "rate": round(rec[1] or 0, 1),
                     "days": round(rec[2] or 0, 1)},
        "assets": assets,
        "scores": scores,
        "compare": run_compare(),
    }
    conn.close()
    return payload


def main():
    payload = build_payload()
    with open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    outdir = os.path.join(ROOT, "reports")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"대시보드 생성: {out}")
    print("브라우저로 열면 됩니다 (서버 불필요, 단일 파일).")


if __name__ == "__main__":
    main()
