#!/usr/bin/env python3
"""제품 KPI 리포트 (§20) — GMV·LTV가 아니라 데이터 품질을 잰다.

  python3 kpi.py                # REAL 원장
  python3 kpi.py --env SIM      # 시뮬레이션 원장
  python3 kpi.py --json

섹션: Data(검증·정확도·correction) / Ops(검증 시간·리뷰 비율) /
Market(바이어·FIRM→정산 전환) / Valuation(추정 vs 실측 캘리브레이션).
표본이 없으면 None — 숫자를 만들지 않는다.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db as coredb
from core.evidence import pct


def compute(conn):
    return {"data": _data(conn), "ops": _ops(conn), "market": _market(conn),
            "valuation": _valuation(conn)}


# ── Data ─────────────────────────────────────────────────────────────────
def _data(conn):
    total = _n(conn, "select count(*) from assets")
    verified = _n(conn, "select count(*) from assets"
                        " where identity_status='HUMAN_VERIFIED'")
    idv = _n(conn, "select count(*) from human_verifications"
                   " where field='identity'")
    corrected = _n(conn, "select count(distinct v.verification_id) from"
                         " verification_corrections c join human_verifications v"
                         " using (verification_id) where v.field='identity'")
    # AI top-1 정확도 / top-3 recall — AI 예측과 인간 확정이 둘 다 있는 자산만
    top1_hit = top3_hit = graded = 0
    for aid, cid in conn.execute(
            "select asset_id, canonical_asset_id from assets"
            " where identity_status='HUMAN_VERIFIED'"
            " and canonical_asset_id is not null"):
        row = conn.execute(
            "select payload from ai_predictions where asset_id=?"
            " and prediction_type='identity' order by observed_at desc limit 1",
            (aid,)).fetchone()
        if not row:
            continue
        cands = [c.get("canonical_asset_id")
                 for c in json.loads(row[0]).get("candidates", [])]
        graded += 1
        top1_hit += int(bool(cands) and cands[0] == cid)
        top3_hit += int(cid in cands[:3])
    completeness = conn.execute("""
        select avg((exists(select 1 from asset_images i where i.asset_id=a.asset_id))
                 + (exists(select 1 from condition_assessments c where c.asset_id=a.asset_id))
                 + (exists(select 1 from authentication_evidence e where e.asset_id=a.asset_id)))
        from assets a""").fetchone()[0]
    return {
        "total_assets": total,
        "verified_assets": verified,
        "verification_coverage_pct": _pctv(verified, total),
        "ai_top1_identity_accuracy_pct": _pctv(top1_hit, graded),
        "ai_top3_recall_pct": _pctv(top3_hit, graded),
        "ai_graded_sample": graded,
        "human_correction_rate_pct": _pctv(corrected, idv),
        "evidence_completeness_pct": (round(completeness / 3 * 100, 1)
                                      if completeness is not None else None),
    }


# ── Ops ──────────────────────────────────────────────────────────────────
def _ops(conn):
    minutes = []
    for started, completed in conn.execute(
            "select started_at, completed_at from human_verifications"
            " where started_at is not null and completed_at is not null"):
        try:
            dt = (datetime.fromisoformat(completed)
                  - datetime.fromisoformat(started)).total_seconds() / 60
        except ValueError:
            continue
        if dt >= 0:
            minutes.append(dt)
    total = _n(conn, "select count(*) from assets")
    reviewed = _n(conn, "select count(distinct asset_id) from human_verifications")
    return {
        "verifications_total": _n(conn, "select count(*) from human_verifications"),
        "median_verification_minutes": (round(pct(minutes, 0.5), 1)
                                        if minutes else None),
        "human_review_ratio_pct": _pctv(reviewed, total),
    }


# ── Market ───────────────────────────────────────────────────────────────
def _market(conn):
    firm_assets = {r[0] for r in conn.execute(
        "select distinct asset_id from dealer_bids"
        " where bid_type in ('FIRM','COMMITTED','SETTLED')")}
    settled_assets = {r[0] for r in conn.execute(
        "select distinct asset_id from dealer_bids where status='settled'")}
    verified = _n(conn, "select count(*) from assets"
                        " where identity_status='HUMAN_VERIFIED'")
    firm_total = _n(conn, "select count(*) from dealer_bids"
                          " where bid_type in ('FIRM','COMMITTED','SETTLED')"
                          " and status != 'superseded'")
    d2s = [r[0] for r in conn.execute(
        "select days_to_sale from transactions where transaction_type='sale'"
        " and days_to_sale is not null")]
    return {
        "unique_buyers": _n(conn, "select count(distinct buyer_id) from dealer_bids"),
        "qualified_buyers": _n(conn, "select count(distinct buyer_id) from"
                                     " dealer_bids where payment_capacity_verified=1"),
        "firm_bids_total": firm_total,
        "firm_bids_per_verified_asset": (round(firm_total / verified, 2)
                                         if verified else None),
        "firm_to_settlement_conversion_pct": _pctv(
            len(firm_assets & settled_assets), len(firm_assets)),
        "settlement_failures": _n(conn, "select count(*) from dealer_bids"
                                        " where settlement_status='failed'"),
        "days_to_sale_median": pct(d2s, 0.5),
    }


# ── Valuation — 추정 vs 실측 (outcomes) ──────────────────────────────────
def _valuation(conn):
    rows = conn.execute(
        "select o.error_pct, o.downside_error_pct, e.confidence from outcomes o"
        " join liquidation_estimates e using (estimate_id)"
        " where o.error_pct is not null").fetchall()
    if not rows:
        return {"outcomes_n": 0, "note": "outcome 대사 표본 없음 — 추정 후 거래가"
                                         " 정산되면 자동 축적된다"}
    abs_err = [abs(r[0]) for r in rows]
    downside = [r[1] for r in rows if r[1] is not None]
    calib = {}
    for err, _, conf in rows:
        calib.setdefault(conf, []).append(abs(err))
    return {
        "outcomes_n": len(rows),
        "mean_abs_error_pct": round(sum(abs_err) / len(abs_err), 1),
        "mean_downside_error_pct": (round(sum(downside) / len(downside), 1)
                                    if downside else None),
        "calibration_by_confidence": {
            k: {"n": len(v), "mean_abs_error_pct": round(sum(v) / len(v), 1)}
            for k, v in sorted(calib.items())},
    }


def _n(conn, sql):
    return conn.execute(sql).fetchone()[0]


def _pctv(num, den):
    return round(num / den * 100, 1) if den else None


def render(k):
    L = ["\n■ DRRRK 제품 KPI (§20)"]
    fmt = lambda v: "—" if v is None else v
    d = k["data"]
    L += ["  [Data]",
          f"    검증 자산            {d['verified_assets']}/{d['total_assets']}"
          f" ({fmt(d['verification_coverage_pct'])}%)",
          f"    AI top-1 정확도      {fmt(d['ai_top1_identity_accuracy_pct'])}%"
          f" · top-3 recall {fmt(d['ai_top3_recall_pct'])}%"
          f" (표본 {d['ai_graded_sample']})",
          f"    correction rate      {fmt(d['human_correction_rate_pct'])}%",
          f"    evidence 완결성      {fmt(d['evidence_completeness_pct'])}%"
          " (사진·상태·진위)"]
    o = k["ops"]
    L += ["  [Ops]",
          f"    검증 건수            {o['verifications_total']}"
          f" · 소요 중위 {fmt(o['median_verification_minutes'])}분"
          f" · 리뷰 비율 {fmt(o['human_review_ratio_pct'])}%"]
    m = k["market"]
    L += ["  [Market]",
          f"    바이어               {m['unique_buyers']}명"
          f" (지불능력 검증 {m['qualified_buyers']}명)",
          f"    FIRM bid             {m['firm_bids_total']}건"
          f" · 검증자산당 {fmt(m['firm_bids_per_verified_asset'])}건",
          f"    FIRM→정산 전환       {fmt(m['firm_to_settlement_conversion_pct'])}%"
          f" · 정산 실패 {m['settlement_failures']}건"
          f" · 처분 중위 {fmt(m['days_to_sale_median'])}일"]
    v = k["valuation"]
    L.append("  [Valuation]")
    if not v["outcomes_n"]:
        L.append(f"    {v['note']}")
    else:
        L.append(f"    outcome 대사 {v['outcomes_n']}건"
                 f" · 평균 |오차| {v['mean_abs_error_pct']}%"
                 f" · 하방오차 {fmt(v['mean_downside_error_pct'])}%")
        for conf, c in v["calibration_by_confidence"].items():
            L.append(f"      {conf:12s} n={c['n']}  |오차| {c['mean_abs_error_pct']}%")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="REAL", help="REAL(기본) 또는 SIM")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    env = "SIMULATION" if args.env.upper().startswith("SIM") else "REAL"
    if not os.path.exists(coredb.DB_FILES[env]):
        raise SystemExit(f"{env} 원장이 없습니다.")
    conn = coredb.connect(env)
    k = compute(conn)
    conn.close()
    print(json.dumps(k, ensure_ascii=False, indent=2) if args.json else render(k))


if __name__ == "__main__":
    main()
