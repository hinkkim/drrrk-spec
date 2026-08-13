#!/usr/bin/env python3
"""Evidence Report 웹 배포판 생성 — 서버 없이 브라우저에서 작동하는 단일 HTML.

  python3 export_web.py                 # 시뮬레이션 원장 → reports/analyzer.html
  DRRRK_ENV=REAL python3 export_web.py  # 실데이터 원장으로 생성

자산별 Evidence Report(§18)를 통째로 내장한다 — 가격 레이어·유동성·청산 범위·
LTV 게이트(사유 포함)·실측·데이터 품질. 등급 조정·검색·귀금속 계산은 페이지 안
JS. 데이터를 갱신하려면 다시 돌려 재게시하면 된다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db as coredb
from core.evidence import GRADE_MULT, PURITY, GOLD_BUY_SPREAD
from report import asset_report

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = "SIMULATION" if os.environ.get("DRRRK_ENV", "SIM").upper().startswith("SIM") \
    else "REAL"


def build_payload():
    conn = coredb.connect(ENV)
    assets = []
    for cid, cat, brand, model, ref, aliases in conn.execute(
            "select canonical_asset_id, category, brand, model, reference_no,"
            " aliases from asset_master where status='active'"
            " order by category, brand"):
        r = asset_report.build(conn, cid, grade="A")  # A등급 기준 — 조정은 JS
        events = [
            {"t": t[:10], "e": e, "d": d, "v": v, "s": s}
            for t, e, d, v, s in conn.execute(
                "select observed_at, event_type, deal_type, value_krw, source "
                "from valuation_event_v where canonical_asset_id=? "
                "order by observed_at desc limit 8", (cid,))]
        assets.append({
            "cid": cid, "category": cat, "brand": brand, "model": model,
            "ref": ref, "aliases": aliases, "events": events,
            "report": {k: r[k] for k in
                       ("as_of", "window_days", "identity", "market",
                        "dealer_market", "liquidity", "liquidation", "ltv",
                        "outcome", "data_quality", "rule_version")}})
    spot = None
    row = conn.execute("select krw_per_g, updated_at from spot_price"
                       " where metal='gold'").fetchone()
    if row:
        spot = {"krw_per_g": row[0], "as_of": row[1]}
    conn.close()
    return {"assets": assets, "gold_spot": spot, "env": ENV,
            "grade_mult": GRADE_MULT, "purity": PURITY,
            "gold_spread": GOLD_BUY_SPREAD, "gold_ltv_ref": 80.0}


def main():
    payload = build_payload()
    with open(os.path.join(HERE, "analyzer_template.html"), encoding="utf-8") as f:
        htm = f.read()
    out = os.path.join(HERE, "reports", "analyzer.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htm.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)))
    size = os.path.getsize(out) // 1024
    print(f"Evidence Report 배포판 생성: {out} ({size}KB, env={payload['env']})")


if __name__ == "__main__":
    main()
