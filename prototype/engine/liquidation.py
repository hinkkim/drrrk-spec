"""청산가치 추정 V1 — rule-based / statistical baseline (§14).

목적: "정해진 기간 안에 실제 현금화 가능한 가격 범위".
ML이 아니다 — FIRM bid·정산 실측의 분위수 + 등급·freshness 조정 규칙이며,
모든 산출에 구간·confidence·표본 명세·rule 버전을 붙인다.

데이터가 부족하면 숫자를 만들지 않는다 (§12):
  confidence=INSUFFICIENT → range는 전부 None + reason_codes.
"""
import json
import os
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import pct, GRADE_MULT, MIN_SAMPLE, STALE_DAYS
from engine.baseline import latest_date, _bid_rows

RULE_VERSION = "rule-v1.0"

# horizon → (low, mid, high) 분위수: 기간이 짧을수록 하방 분위수 (급처분 할인)
HORIZON_PCTS = {7: (0.10, 0.25, 0.40), 30: (0.25, 0.50, 0.75),
                60: (0.40, 0.60, 0.80)}


def estimate(conn, cid, horizon_days=30, grade="A", window_days=180,
             as_of=None, persist=False, env=None, asset_id=None):
    if horizon_days not in HORIZON_PCTS:
        raise ValueError(f"horizon_days must be one of {tuple(HORIZON_PCTS)}")
    as_of = as_of or latest_date(conn)
    since = (as_of - timedelta(days=window_days)).isoformat()

    firm = [r[0] for r in _bid_rows(conn, cid, since, firm=True)]
    indicative = [r[0] for r in _bid_rows(conn, cid, since, firm=False)]
    settled = [r[0] for r in conn.execute(
        "select net_proceeds_krw from v_net_proceeds where canonical_asset_id=?"
        " and transaction_type='sale' and settled_at is not null"
        " and settled_at>=?", (cid, since))]
    latest_bid = conn.execute(
        "select max(bid_time) from dealer_bids where canonical_asset_id=?",
        (cid,)).fetchone()[0]

    reasons, base = [], firm
    if len(firm) < 2:
        reasons.append("no_firm_bid" if not firm else "sample_too_small")
        base = firm + indicative
    if not settled:
        reasons.append("no_settled_transaction")
    stale = (not latest_bid or
             (as_of - date.fromisoformat(latest_bid[:10])).days > STALE_DAYS)
    if stale:
        reasons.append("stale_market_evidence")
    if asset_id is not None:
        st = conn.execute("select identity_status from assets where asset_id=?",
                          (asset_id,)).fetchone()
        if not st or st[0] != "HUMAN_VERIFIED":
            reasons.append("identification_unverified")

    # confidence 사다리 — 강등 사유가 있으면 위로 못 올라간다
    if len(base) < 2:
        if "sample_too_small" not in reasons:
            reasons.append("sample_too_small")
        confidence = "INSUFFICIENT"
    elif len(firm) >= 10 and len(settled) >= 3 and not stale \
            and "identification_unverified" not in reasons:
        confidence = "HIGH"
    elif len(firm) >= MIN_SAMPLE and settled and \
            "identification_unverified" not in reasons:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    gm = GRADE_MULT.get(grade, 1.0)
    if confidence == "INSUFFICIENT":
        low = mid = high = None      # 숫자를 억지로 만들지 않는다
    else:
        pl, pm, ph = HORIZON_PCTS[horizon_days]
        low, mid, high = (int(pct(base, p) * gm) for p in (pl, pm, ph))

    result = {
        "canonical_asset_id": cid, "asset_id": asset_id, "grade": grade,
        "horizon_days": horizon_days,
        "range_low_krw": low, "range_mid_krw": mid, "range_high_krw": high,
        "confidence": confidence, "reason_codes": reasons,
        "input_sample": {"firm_bids": len(firm), "indicative_bids": len(indicative),
                         "settled_transactions": len(settled),
                         "window_days": window_days},
        "rule_version": RULE_VERSION, "estimated_at": as_of.isoformat(),
    }
    if persist:
        result["estimate_id"] = _persist(conn, result, env)
    return result


def _persist(conn, r, env):
    if env is None:
        from core import db as coredb
        env = coredb.environment(conn) or "REAL"
        if env not in ("SIMULATION", "REAL", "BACKFILL"):
            env = "REAL"
    eid = str(uuid.uuid4())
    conn.execute(
        "insert into liquidation_estimates (estimate_id, canonical_asset_id,"
        " asset_id, horizon_days, range_low_krw, range_mid_krw, range_high_krw,"
        " confidence, reason_codes, input_sample, rule_version,"
        " data_environment, estimated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, r["canonical_asset_id"], r["asset_id"], r["horizon_days"],
         r["range_low_krw"], r["range_mid_krw"], r["range_high_krw"],
         r["confidence"], json.dumps(r["reason_codes"]),
         json.dumps(r["input_sample"]), r["rule_version"], env,
         r["estimated_at"]))
    conn.commit()
    return eid
