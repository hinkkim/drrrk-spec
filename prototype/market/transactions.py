"""거래·비용·Net Proceeds — 가장 높은 등급의 Ground Truth (§15).

  transactions        성사 사실 (gross). 값 컬럼 불변.
  transaction_costs   수수료·배송·감정 등 비용 행
  v_net_proceeds      net = gross − Σcosts (DERIVED — 저장하지 않는다)
  outcomes            사전 추정치와 실측의 대사 (캘리브레이션 원천)
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit

TX_SOURCE_TYPE = {"sale": "ACTUAL_SALE", "purchase": "ACTUAL_PURCHASE",
                  "liquidation": "ACTUAL_LIQUIDATION"}


def record_transaction(conn, asset_id, transaction_type, gross_price_krw,
                       contracted_at, winning_bid_id=None, settled_at=None,
                       days_to_sale=None, costs_unknown=0, source="drrrk",
                       env="REAL", actor=None, meta=None):
    row = conn.execute("select canonical_asset_id from assets where asset_id=?",
                       (asset_id,)).fetchone()
    if row is None:
        raise ValueError(f"미등록 asset_id: {asset_id}")
    if winning_bid_id:
        b = conn.execute("select status from dealer_bids where bid_id=?",
                         (winning_bid_id,)).fetchone()
        if b is None:
            raise ValueError(f"없는 winning_bid_id: {winning_bid_id}")
    tid = str(uuid.uuid4())
    stype = ("PARTNER_HISTORICAL" if env == "BACKFILL"
             else TX_SOURCE_TYPE[transaction_type])
    conn.execute(
        "insert into transactions (transaction_id, asset_id, canonical_asset_id,"
        " winning_bid_id, transaction_type, gross_price_krw, contracted_at,"
        " settled_at, days_to_sale, costs_unknown, source, source_type,"
        " data_environment, meta) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, asset_id, row[0], winning_bid_id, transaction_type,
         gross_price_krw, contracted_at, settled_at, days_to_sale,
         costs_unknown, source, stype, env,
         json.dumps(meta or {}, ensure_ascii=False)))
    audit.log(conn, actor or source, "record_transaction", "transactions", tid,
              after={"transaction_type": transaction_type,
                     "gross_price_krw": gross_price_krw,
                     "winning_bid_id": winning_bid_id})
    conn.commit()
    return tid


def add_cost(conn, transaction_id, cost_type, amount_krw, note=None, actor="drrrk"):
    if not conn.execute("select 1 from transactions where transaction_id=?",
                        (transaction_id,)).fetchone():
        raise ValueError(f"없는 transaction_id: {transaction_id}")
    cid = str(uuid.uuid4())
    conn.execute("insert into transaction_costs (cost_id, transaction_id,"
                 " cost_type, amount_krw, note) values (?,?,?,?,?)",
                 (cid, transaction_id, cost_type, amount_krw, note))
    # 비용이 실제로 입력되면 costs_unknown 해제
    conn.execute("update transactions set costs_unknown=0 where transaction_id=?",
                 (transaction_id,))
    audit.log(conn, actor, "add_cost", "transaction_costs", cid,
              after={"cost_type": cost_type, "amount_krw": amount_krw,
                     "transaction_id": transaction_id})
    conn.commit()
    return cid


def net_proceeds(conn, transaction_id):
    """Net Proceeds 조회 (DERIVED). {'gross','costs','net','costs_unknown'}"""
    row = conn.execute(
        "select gross_price_krw, total_costs_krw, net_proceeds_krw, costs_unknown"
        " from v_net_proceeds where transaction_id=?", (transaction_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 transaction_id: {transaction_id}")
    return {"gross_krw": row[0], "total_costs_krw": row[1],
            "net_proceeds_krw": row[2], "costs_unknown": bool(row[3])}


def record_outcome(conn, estimate_id, transaction_id, actor="system"):
    """청산가치 추정 vs 실제 Net Proceeds 대사 — Learning Loop의 입력 (§14·§20)."""
    est = conn.execute(
        "select range_low_krw, range_mid_krw, data_environment"
        " from liquidation_estimates where estimate_id=?", (estimate_id,)).fetchone()
    if est is None:
        raise ValueError(f"없는 estimate_id: {estimate_id}")
    np_ = net_proceeds(conn, transaction_id)
    net = np_["net_proceeds_krw"]
    low, mid, env = est
    oid = str(uuid.uuid4())
    error = round((mid - net) / net * 100, 2) if (mid and net) else None
    downside = round((low - net) / net * 100, 2) if (low and net) else None
    conn.execute(
        "insert into outcomes (outcome_id, estimate_id, transaction_id,"
        " net_proceeds_krw, error_pct, downside_error_pct, data_environment)"
        " values (?,?,?,?,?,?,?)",
        (oid, estimate_id, transaction_id, net, error, downside, env))
    audit.log(conn, actor, "record_outcome", "outcomes", oid,
              after={"net_proceeds_krw": net, "error_pct": error,
                     "downside_error_pct": downside})
    conn.commit()
    return oid
