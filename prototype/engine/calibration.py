#!/usr/bin/env python3
"""캘리브레이션 루프 (T14) — 추정과 실측을 자동으로 대사한다. (prototype/ 에서 실행)

  python3 engine/calibration.py --env REAL          # 대사 실행 + 요약
  python3 engine/calibration.py --env SIM --dry-run

동작:
  outcome이 없는 liquidation_estimates마다, 같은 canonical 자산(asset_id가
  있으면 그 실물)의 '추정 이후 horizon+유예 안에 계약·정산된' 판매 거래를 찾아
  outcomes에 기록한다 (오차·하방오차 자동 계산). 이것이 Learning Loop의 입력 —
  rule/ML은 이 대사 결과로만 평가·개선된다 (§14·§15).

INSUFFICIENT 추정은 숫자가 없으므로 대사하지 않는다.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import transactions as mtx

GRACE_DAYS = 30   # horizon 초과 유예 — 이 안에 정산되면 해당 추정의 실측으로 인정


def reconcile(conn, dry_run=False):
    """미대사 추정 ↔ 정산 거래 매칭. {'matched': n, 'pairs': [...]} 반환."""
    pending = conn.execute(
        "select e.estimate_id, e.canonical_asset_id, e.asset_id, e.horizon_days,"
        " e.estimated_at from liquidation_estimates e"
        " left join outcomes o using (estimate_id)"
        " where o.outcome_id is null and e.confidence != 'INSUFFICIENT'"
        " order by e.estimated_at").fetchall()
    used_tx = {r[0] for r in conn.execute("select transaction_id from outcomes")}
    pairs = []
    for eid, cid, aid, horizon, est_at in pending:
        deadline = (date.fromisoformat(est_at[:10])
                    + timedelta(days=horizon + GRACE_DAYS)).isoformat()
        cond, args = "canonical_asset_id=?", [cid]
        if aid:
            cond, args = "asset_id=?", [aid]
        rows = conn.execute(
            f"select transaction_id from v_net_proceeds"
            f" where {cond} and transaction_type='sale' and settled_at is not null"
            f" and settled_at>=? and settled_at<=?"
            f" order by settled_at", args + [est_at[:10], deadline]).fetchall()
        tid = next((r[0] for r in rows if r[0] not in used_tx), None)
        if tid is None:
            continue
        used_tx.add(tid)
        pairs.append((eid, tid))
        if not dry_run:
            mtx.record_outcome(conn, eid, tid, actor="calibration")
    return {"matched": len(pairs), "pending_unmatched": len(pending) - len(pairs),
            "pairs": pairs}


def summary(conn):
    """confidence별 캘리브레이션 요약 — kpi의 Valuation 섹션 재사용."""
    from kpi import _valuation
    return _valuation(conn)


def render(res, cal):
    L = ["\n■ 캘리브레이션 루프"]
    L.append(f"  신규 대사 {res['matched']}건 · 실측 대기 {res['pending_unmatched']}건")
    if not cal["outcomes_n"]:
        L.append(f"  {cal['note']}")
        return "\n".join(L) + "\n"
    L.append(f"  누적 outcome {cal['outcomes_n']}건 · 평균 |오차| "
             f"{cal['mean_abs_error_pct']}% · 하방오차 {cal['mean_downside_error_pct']}%")
    for conf, c in cal["calibration_by_confidence"].items():
        L.append(f"    {conf:12s} n={c['n']}  |오차| {c['mean_abs_error_pct']}%")
    return "\n".join(L) + "\n"


def main():
    from core import db as coredb
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="REAL", help="REAL(기본) 또는 SIM")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = "SIMULATION" if args.env.upper().startswith("SIM") else "REAL"
    if not os.path.exists(coredb.DB_FILES[env]):
        raise SystemExit(f"{env} 원장이 없습니다.")
    conn = coredb.connect(env)
    res = reconcile(conn, dry_run=args.dry_run)
    print(render(res, summary(conn)))
    conn.close()


if __name__ == "__main__":
    main()
