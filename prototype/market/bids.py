"""딜러 bid 수명주기 — INDICATIVE → FIRM → COMMITTED → SETTLED (§10).

bid는 불변 사실이다:
  · 단계 승격 = 새 행 + supersedes_bid_id 연결 (이전 행은 status='superseded')
  · 가격·유형·시각은 UPDATE 불가 (schema trigger)
  · status 전이만 이 모듈을 통해 갱신되고, 모두 audit_logs에 남는다

단순 bid count를 시장표본으로 쓰지 않기 위한 기초 필드(buyer_id, bid_type,
expiry, settlement_status)가 여기서 채워진다 — 지표 산출은 engine/liquidity.py.
"""
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit
from core.evidence import BID_TYPES, BID_SOURCE_TYPE

# 허용되는 단계 승격 (앞으로만 간다)
PROMOTIONS = {"INDICATIVE": ("FIRM", "COMMITTED"),
              "FIRM": ("COMMITTED",),
              "COMMITTED": ("SETTLED",)}
# 허용되는 status 전이
STATUS_TRANSITIONS = {
    "active": ("expired", "cancelled", "superseded", "selected", "rejected"),
    "selected": ("settled", "cancelled"),
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def place_bid(conn, asset_id, buyer_id, price_krw, bid_type="INDICATIVE",
              bid_time=None, expiry=None, payment_capacity_verified=0,
              env="REAL", actor=None, supersedes=None, meta=None):
    if bid_type not in BID_TYPES:
        raise ValueError(f"bid_type must be one of {BID_TYPES}")
    row = conn.execute("select canonical_asset_id from assets where asset_id=?",
                       (asset_id,)).fetchone()
    if row is None:
        raise ValueError(f"미등록 asset_id: {asset_id}")
    bid_id = str(uuid.uuid4())
    conn.execute(
        "insert into dealer_bids (bid_id, asset_id, canonical_asset_id, buyer_id,"
        " bid_type, bid_price_krw, bid_time, expiry, payment_capacity_verified,"
        " supersedes_bid_id, source, source_type, data_environment, meta)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bid_id, asset_id, row[0], buyer_id, bid_type, price_krw,
         bid_time or now_iso(), expiry, payment_capacity_verified, supersedes,
         buyer_id, BID_SOURCE_TYPE[bid_type], env,
         json.dumps(meta or {}, ensure_ascii=False)))
    audit.log(conn, actor or buyer_id, "place_bid", "dealer_bids", bid_id,
              after={"bid_type": bid_type, "price_krw": price_krw,
                     "asset_id": asset_id})
    conn.commit()
    return bid_id


def promote_bid(conn, bid_id, to_type, price_krw=None, expiry=None,
                payment_capacity_verified=None, actor=None, bid_time=None):
    """단계 승격 — 새 행을 만들고 기존 행은 superseded로 마감한다."""
    old = _get(conn, bid_id)
    if old["status"] not in ("active", "selected"):
        raise ValueError(f"{old['status']} 상태의 bid는 승격할 수 없다: {bid_id}")
    if to_type not in PROMOTIONS.get(old["bid_type"], ()):
        raise ValueError(
            f"{old['bid_type']} → {to_type} 승격 불가 (허용: "
            f"{PROMOTIONS.get(old['bid_type'], ())})")
    new_id = place_bid(
        conn, old["asset_id"], old["buyer_id"],
        price_krw if price_krw is not None else old["bid_price_krw"],
        bid_type=to_type, bid_time=bid_time, expiry=expiry,
        payment_capacity_verified=(payment_capacity_verified
                                   if payment_capacity_verified is not None
                                   else old["payment_capacity_verified"]),
        env=old["data_environment"], actor=actor, supersedes=bid_id)
    _set_status(conn, bid_id, "superseded", actor,
                reason=f"promoted to {to_type} as {new_id}")
    return new_id


def expire_bid(conn, bid_id, actor="system"):
    _transition(conn, bid_id, "expired", actor)


def cancel_bid(conn, bid_id, actor, reason=None):
    _transition(conn, bid_id, "cancelled", actor, reason=reason)


def reject_bid(conn, bid_id, actor, reason):
    _transition(conn, bid_id, "rejected", actor, reason=reason)
    conn.execute("update dealer_bids set rejected_reason=? where bid_id=?",
                 (reason, bid_id))
    conn.commit()


def select_bid(conn, bid_id, actor):
    """낙찰 선택. COMMITTED 단계여야 거래로 이어질 수 있다."""
    _transition(conn, bid_id, "selected", actor)


def settle_bid(conn, bid_id, actor, settled=True):
    """정산 결과 기록. 실패(settlement failure)도 반드시 남긴다 (§10).

    selected 상태의 COMMITTED bid만 정산 가능. 성공 시 SETTLED 단계의 새 행이
    생기고(승격) 그 행이 status='settled'로 마감된다. 반환값: 최종 bid_id.
    """
    old = _get(conn, bid_id)
    if old["status"] != "selected":
        raise ValueError(f"selected 상태만 정산할 수 있다 (현재: {old['status']})")
    if not settled:
        conn.execute("update dealer_bids set settlement_status='failed'"
                     " where bid_id=?", (bid_id,))
        audit.log(conn, actor, "settle_failed", "dealer_bids", bid_id,
                  after={"settlement_status": "failed"})
        conn.commit()
        return bid_id
    if old["bid_type"] != "COMMITTED":
        raise ValueError(f"COMMITTED 단계만 정산 가능 (현재: {old['bid_type']})")
    target = promote_bid(conn, bid_id, "SETTLED", actor=actor)
    conn.execute("update dealer_bids set status='settled',"
                 " settlement_status='settled' where bid_id=?", (target,))
    audit.log(conn, actor, "settle", "dealer_bids", target,
              after={"settlement_status": "settled"})
    conn.commit()
    return target


def expire_stale(conn, as_of=None, actor="system"):
    """expiry가 지난 active bid 일괄 만료 — 유동성 지표에서 자동 제외된다."""
    as_of = as_of or now_iso()
    rows = conn.execute("select bid_id from dealer_bids where status='active'"
                        " and expiry is not null and expiry < ?", (as_of,)).fetchall()
    for (bid_id,) in rows:
        _set_status(conn, bid_id, "expired", actor, reason=f"expiry < {as_of}")
    conn.commit()
    return len(rows)


def _transition(conn, bid_id, new_status, actor, reason=None):
    old = _get(conn, bid_id)
    allowed = STATUS_TRANSITIONS.get(old["status"], ())
    if new_status not in allowed:
        raise ValueError(f"status {old['status']} → {new_status} 전이 불가 "
                         f"(허용: {allowed})")
    _set_status(conn, bid_id, new_status, actor, reason)
    conn.commit()


def _set_status(conn, bid_id, new_status, actor, reason=None):
    old = _get(conn, bid_id)
    conn.execute("update dealer_bids set status=? where bid_id=?",
                 (new_status, bid_id))
    audit.log(conn, actor or "system", "status_change", "dealer_bids", bid_id,
              before={"status": old["status"]}, after={"status": new_status},
              reason=reason)


def _get(conn, bid_id):
    cols = ("bid_id", "asset_id", "canonical_asset_id", "buyer_id", "bid_type",
            "bid_price_krw", "bid_time", "expiry", "status",
            "payment_capacity_verified", "data_environment")
    row = conn.execute(f"select {','.join(cols)} from dealer_bids where bid_id=?",
                       (bid_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 bid_id: {bid_id}")
    return dict(zip(cols, row))
