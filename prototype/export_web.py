#!/usr/bin/env python3
"""분석 프로그램의 웹 배포판 생성 — 서버 없이 브라우저에서 작동하는 단일 HTML.

  python3 export_web.py   # → reports/analyzer.html

원장에서 자산별 통계·최근 이벤트를 추출해 페이지에 내장하고,
분석 로직(등급 조정·귀금속 계산·별칭 검색)은 페이지 안 JS로 구현한다.
데이터를 갱신하려면 이 스크립트를 다시 돌려 재게시하면 된다.
"""
import json
import os
import sqlite3

import analyze as az

HERE = os.path.dirname(os.path.abspath(__file__))


def build_payload():
    conn = sqlite3.connect(az.DB)
    assets = []
    for cid, cat, brand, model, ref, aliases in conn.execute(
            "select canonical_asset_id, category, brand, model, reference_no, aliases "
            "from asset_master order by category, brand"):
        r = az.analyze_asset(conn, cid, grade="A")  # A등급 기준 — 등급 조정은 JS에서
        events = [
            {"t": t[:10], "e": e, "d": d, "v": v, "s": s}
            for t, e, d, v, s in conn.execute(
                "select observed_at, event_type, deal_type, value_krw, source "
                "from valuation_event where canonical_asset_id=? "
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
                "sample": r["sample"], "confidence": r["confidence"],
                "window": r["window_days"], "as_of": r["as_of"],
            }, "events": events})
    spot = None
    if az._has_spot(conn):
        row = conn.execute("select krw_per_g, updated_at from spot_price "
                           "where metal='gold'").fetchone()
        if row:
            spot = {"krw_per_g": row[0], "as_of": row[1]}
    conn.close()
    return {"assets": assets, "gold_spot": spot,
            "grade_mult": {"S": 1.08, "A": 1.00, "B": 0.88, "C": 0.72},
            "purity": {"24K": 0.999, "22K": 0.916, "18K": 0.750, "14K": 0.585},
            "gold_spread": 0.05, "gold_ltv": 80.0}


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
