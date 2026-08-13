#!/usr/bin/env python3
"""분석 프로그램의 웹 배포판 생성 — 서버 없이 브라우저에서 작동하는 단일 HTML.

  python3 export_web.py   # → reports/analyzer.html

원장에서 자산별 통계·최근 이벤트를 추출해 페이지에 내장하고,
분석 로직(등급 조정·귀금속 계산·별칭 검색)은 페이지 안 JS로 구현한다.
데이터를 갱신하려면 이 스크립트를 다시 돌려 재게시하면 된다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db as coredb
from engine import baseline

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = "SIMULATION" if os.environ.get("DRRRK_ENV", "SIM").upper().startswith("SIM") \
    else "REAL"


def build_payload():
    conn = coredb.connect(ENV)
    assets = []
    for cid, cat, brand, model, ref, aliases in conn.execute(
            "select canonical_asset_id, category, brand, model, reference_no, aliases "
            "from asset_master where status='active' order by category, brand"):
        r = baseline.analyze_asset_compat(conn, cid, grade="A")  # 등급 조정은 JS에서
        events = [
            {"t": t[:10], "e": e, "d": d, "v": v, "s": s}
            for t, e, d, v, s in conn.execute(
                "select observed_at, event_type, deal_type, value_krw, source "
                "from valuation_event_v where canonical_asset_id=? "
                "order by observed_at desc limit 8", (cid,))]
        assets.append({
            "cid": cid, "category": cat, "brand": brand, "model": model,
            "ref": ref, "aliases": aliases, "stats": {
                "mv": r["market_value_krw"], "lv": r["liquidation_value_krw"],
                "lv25": r["liquidation_value_p25_krw"],
                "discount": r["wholesale_discount_pct"],
                "spread": r.get("bid_spread_pct"),
                "days_sale": r.get("expected_days_to_sale"),
                "days_liq": r.get("days_to_liquidate"),
                "recovery": r.get("recovery_rate_pct"),
                "ltv": r.get("recommended_ltv_pct"),
                "ltv_reasons": r.get("ltv_reasons", []),
                "ltv_indicative_ref": r.get("indicative_ltv_reference_pct"),
                "sample": r["sample"], "confidence": r["confidence"],
                "window": r["window_days"], "as_of": r["as_of"],
            }, "events": events})
    spot = None
    row = conn.execute("select krw_per_g, updated_at from spot_price "
                       "where metal='gold'").fetchone()
    if row:
        spot = {"krw_per_g": row[0], "as_of": row[1]}
    conn.close()
    from core.evidence import GRADE_MULT, PURITY, GOLD_BUY_SPREAD
    return {"assets": assets, "gold_spot": spot, "env": ENV,
            "grade_mult": GRADE_MULT, "purity": PURITY,
            "gold_spread": GOLD_BUY_SPREAD, "gold_ltv": 80.0}


def main():
    payload = build_payload()
    with open(os.path.join(HERE, "analyzer_template.html"), encoding="utf-8") as f:
        htm = f.read()
    out = os.path.join(HERE, "reports", "analyzer.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htm.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)))
    print(f"웹 배포판 생성: {out}")


if __name__ == "__main__":
    main()
