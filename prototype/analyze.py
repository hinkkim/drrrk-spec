#!/usr/bin/env python3
"""드르륵 자산 분석 CLI — Evidence Report를 출력한다 (V1).

  python3 analyze.py list                                # 분석 가능한 자산 목록
  python3 analyze.py asset "서브마리너" --grade A         # Evidence Report
  python3 analyze.py asset WATCH-ROLEX-SUBMARINER-126610LN --json
  python3 analyze.py asset "클미" --env SIM               # 시뮬레이션 DB 조회
  python3 analyze.py gold --purity 18K --weight 18.75    # 귀금속 (시세×순도×중량)

기본은 REAL 환경(drrrk_real.db). 시뮬레이션 결과를 보려면 --env SIM.
LTV는 FIRM bid·정산 실측·식별 확정이 갖춰졌을 때만 출력된다 — 부족하면
NOT AVAILABLE과 사유가 나온다 (§12 No-Fake-Confidence).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db as coredb
from core.evidence import PURITY, GOLD_BUY_SPREAD
from engine import baseline
from report import asset_report

GOLD_CONVENTIONAL_LTV = 0.80   # 관행 참고치 — 드르륵 실측 아님 (권장값이 아니다)


def connect(env):
    env = "SIMULATION" if env.upper().startswith("SIM") else "REAL"
    path = coredb.DB_FILES[env]
    if not os.path.exists(path):
        hint = ("python3 sim/run.py 로 시뮬레이션을 생성" if env == "SIMULATION"
                else "intake/ingest.py 로 실데이터를 입력")
        sys.exit(f"{env} 원장이 없습니다 ({path}). 먼저 {hint}하세요.")
    return coredb.connect(env)


def analyze_gold(purity, weight_g, spot=None, conn=None):
    spot_at = "manual"
    if spot is None and conn is not None:
        row = conn.execute("select krw_per_g, updated_at from spot_price"
                           " where metal='gold'").fetchone()
        if row:
            spot, spot_at = row
    if spot is None:
        return {"error": "금 시세가 없습니다. --spot <24K 1g당 원> 지정 또는 "
                         "`python3 intake/ingest.py spot gold <가격>` 으로 저장하세요."}
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
        "conventional_ltv_reference_pct": round(GOLD_CONVENTIONAL_LTV * 100, 1),
        "confidence": "high",
        "note": "표준화 자산 — 시세×순도×중량으로 직접 산출. LTV는 은행 관행"
                " 참고치이며 드르륵 실측·권장값이 아니다.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="REAL", help="REAL(기본) 또는 SIM")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="분석 가능한 자산 목록")
    pa = sub.add_parser("asset", help="Evidence Report (원장 기반)")
    pa.add_argument("query", help="canonical ID 또는 모델명/별칭")
    pa.add_argument("--grade", default="A", choices=["S", "A", "B", "C"])
    pa.add_argument("--asset-id", help="개별 실물 기준 리포트 (식별·진위 포함)")
    pa.add_argument("--json", action="store_true")
    pg = sub.add_parser("gold", help="귀금속(금) 분석 — 시세 기반")
    pg.add_argument("--purity", default="24K")
    pg.add_argument("--weight", type=float, required=True, help="중량(g)")
    pg.add_argument("--spot", type=float, help="24K 1g당 시세(원)")
    pg.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cmd == "list":
        conn = connect(args.env)
        for cid, b, m in conn.execute(
                "select canonical_asset_id, brand, model from asset_master"
                " where status='active' order by category, brand"):
            n = conn.execute("select count(*) from dealer_bids where"
                             " canonical_asset_id=?", (cid,)).fetchone()[0]
            nf = conn.execute("select count(*) from dealer_bids where"
                              " canonical_asset_id=? and bid_type in"
                              " ('FIRM','COMMITTED','SETTLED')", (cid,)).fetchone()[0]
            print(f"  {cid:45s} {b} {m}  (bid {n} · firm {nf})")
        return

    if args.cmd == "asset":
        conn = connect(args.env)
        cid, candidates = baseline.find_asset(conn, args.query)
        if not cid:
            if candidates:
                sys.exit("검색 결과가 여러 개입니다:\n  " + "\n  ".join(candidates))
            sys.exit(f"'{args.query}' 를 찾지 못했습니다. `python3 analyze.py list`로 확인하세요.")
        r = asset_report.build(conn, cid, grade=args.grade,
                               asset_id=args.asset_id)
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json
              else asset_report.render_text(r))
        return

    conn = None
    real_db = coredb.DB_FILES["REAL"]
    if os.path.exists(real_db):
        conn = coredb.connect("REAL")
    r = analyze_gold(args.purity, args.weight, spot=args.spot, conn=conn)
    if "error" in r:
        sys.exit(f"오류: {r['error']}")
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        a = r["asset"]
        print(f"\n■ 금 {a['purity']} {a['weight_g']}g"
              f"  (24K {r['spot_krw_per_g_24k']:,}원/g, {r['spot_as_of']})")
        print(f"  시장가치(MV)      ₩{r['market_value_krw']:,}")
        print(f"  청산가치(LV)      ₩{r['liquidation_value_krw']:,}"
              f"  (매입 스프레드 {r['wholesale_discount_pct']}%)")
        print(f"  관행 LTV 참고치   {r['conventional_ltv_reference_pct']}%"
              f"  — 권장값 아님")
        print(f"  ※ {r['note']}\n")


if __name__ == "__main__":
    main()
