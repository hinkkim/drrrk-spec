#!/usr/bin/env python3
"""청산 추정 백테스트 (§14) — 배포 게이트. (prototype/ 에서 실행)

  python3 engine/backtest.py --env SIM
  python3 engine/backtest.py --env REAL --horizon 30

방법 — 시간 절단 holdout:
  정산 완료된 판매 거래마다, "계약 전일"을 as_of로 고정하고 그 시점까지의
  데이터만으로 두 예측을 만든다:
    · Dealer Median baseline : 이전 window의 bid P50
    · Rule Engine (rule-v1)  : liquidation.estimate의 mid
  이후 실측 net proceeds와 비교한다. as_of 상한이 엔진 쿼리에 걸려 있어
  미래 데이터 누출이 없다.

배포 규칙: Rule Engine이 out-of-sample에서 baseline을 이기지 못하면
배포하지 않는다. ML도 이후 같은 게이트를 통과해야 한다.
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import pct, GRADE_MULT
from engine import liquidation
from engine.baseline import _bid_rows, until_of

MIN_PRIOR_QUOTES = 3


def run_backtest(conn, horizon_days=30, window_days=180,
                 min_prior_quotes=MIN_PRIOR_QUOTES):
    """모든 정산 거래에 대해 사전 예측 vs 실측. 집계 dict 반환."""
    txs = conn.execute(
        "select v.transaction_id, v.canonical_asset_id, v.net_proceeds_krw,"
        " t.contracted_at, a.grade"
        " from v_net_proceeds v join transactions t using (transaction_id)"
        " left join assets a on a.asset_id = v.asset_id"
        " where v.transaction_type='sale' and v.settled_at is not null"
        " and v.canonical_asset_id is not null"
        " order by t.contracted_at").fetchall()

    rows, skipped = [], 0
    for tid, cid, net, contracted_at, grade in txs:
        cutoff = date.fromisoformat(contracted_at[:10]) - timedelta(days=1)
        since = (cutoff - timedelta(days=window_days)).isoformat()
        prior = [q[0] for q in _bid_rows(conn, cid, since, firm=None,
                                         until=until_of(cutoff))]
        if len(prior) < min_prior_quotes or not net:
            skipped += 1
            continue
        gm = GRADE_MULT.get(grade or "A", 1.0)
        baseline_pred = pct(prior, 0.5) * gm
        est = liquidation.estimate(conn, cid, horizon_days, grade=grade or "A",
                                   window_days=window_days, as_of=cutoff)
        rule_pred = est["range_mid_krw"]
        rule_low = est["range_low_krw"]
        rows.append({
            "transaction_id": tid, "canonical_asset_id": cid,
            "cutoff": cutoff.isoformat(), "actual_net_krw": net,
            "baseline_pred_krw": int(baseline_pred),
            "baseline_err_pct": round((baseline_pred - net) / net * 100, 2),
            "rule_pred_krw": rule_pred,
            "rule_err_pct": (round((rule_pred - net) / net * 100, 2)
                             if rule_pred else None),
            "rule_floor_breached": (rule_low is not None and rule_low > net),
            "rule_confidence": est["confidence"],
        })

    with_rule = [r for r in rows if r["rule_err_pct"] is not None]
    mae = lambda errs: round(sum(abs(e) for e in errs) / len(errs), 2) if errs else None
    base_mae = mae([r["baseline_err_pct"] for r in rows])
    rule_mae = mae([r["rule_err_pct"] for r in with_rule])
    # 하방 안전성: 추정 low(급처분 하한)가 실측보다 높았던 비율 — 낮을수록 안전
    floor_breach = (round(sum(r["rule_floor_breached"] for r in with_rule)
                          / len(with_rule) * 100, 1) if with_rule else None)
    return {
        "horizon_days": horizon_days, "window_days": window_days,
        "n_transactions": len(rows), "n_skipped_thin_history": skipped,
        "baseline_mae_pct": base_mae,
        "rule_mae_pct": rule_mae, "rule_coverage_n": len(with_rule),
        "rule_floor_breach_pct": floor_breach,
        "rule_beats_baseline": (rule_mae is not None and base_mae is not None
                                and rule_mae <= base_mae),
        "rows": rows,
    }


def render(bt):
    L = [f"\n■ 청산 추정 백테스트 — {bt['horizon_days']}일 horizon, "
         f"window {bt['window_days']}일"]
    L.append(f"  표본: 정산 거래 {bt['n_transactions']}건 "
             f"(사전 데이터 부족 제외 {bt['n_skipped_thin_history']}건)")
    if not bt["n_transactions"]:
        L.append("  평가 불가 — 정산 실측이 더 필요하다.")
        return "\n".join(L) + "\n"
    L.append(f"  Dealer Median baseline  MAE {bt['baseline_mae_pct']}%")
    L.append(f"  Rule Engine (rule-v1)   MAE {bt['rule_mae_pct']}% "
             f"(적용 {bt['rule_coverage_n']}건)")
    L.append(f"  하한(floor) 침해율       {bt['rule_floor_breach_pct']}% "
             "— 추정 low가 실측보다 높았던 비율 (낮을수록 안전)")
    verdict = ("✔ Rule이 baseline 이상 — 배포 게이트 통과"
               if bt["rule_beats_baseline"] else
               "✘ Rule이 baseline을 못 이김 — 배포 보류 (baseline 유지)")
    L.append(f"  {verdict}")
    return "\n".join(L) + "\n"


def main():
    from core import db as coredb
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="SIM", help="SIM(기본) 또는 REAL")
    ap.add_argument("--horizon", type=int, default=30, choices=[7, 30, 60])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    env = "SIMULATION" if args.env.upper().startswith("SIM") else "REAL"
    if not os.path.exists(coredb.DB_FILES[env]):
        raise SystemExit(f"{env} 원장이 없습니다.")
    conn = coredb.connect(env)
    bt = run_backtest(conn, horizon_days=args.horizon)
    conn.close()
    if args.json:
        print(json.dumps(bt, ensure_ascii=False, indent=2))
    else:
        print(render(bt))


if __name__ == "__main__":
    main()
