"""유동성 원시 지표 (§13) — 점수화하지 않는다. 원시값 + 표본수를 그대로 노출.

단순 bid count를 시장표본으로 쓰지 않는다:
  unique_bidders / firm_bid_count / buyer 집중도 / 취소율 / 전환율을 분리 산출.
"""
import os
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import pct
from engine.baseline import latest_date, PRICE_STATUSES, FIRM_TYPES

FAILED_LISTING_DAYS = 30


def metrics(conn, cid, window_days=180, as_of=None):
    as_of = as_of or latest_date(conn)
    since = (as_of - timedelta(days=window_days)).isoformat()

    rows = conn.execute(
        "select buyer_id, bid_type, bid_price_krw, status, asset_id from"
        " dealer_bids where canonical_asset_id=? and bid_time>=?"
        " and status != 'superseded'", (cid, since)).fetchall()
    prices = [r[2] for r in rows if r[3] in PRICE_STATUSES]
    firm_rows = [r for r in rows if r[1] in FIRM_TYPES]
    buyers = {}
    for b, *_ in rows:
        buyers[b] = buyers.get(b, 0) + 1
    top = sorted(buyers.values(), reverse=True)
    total_bids = len(rows)

    verified_buyers = {r[0] for r in conn.execute(
        "select distinct buyer_id from dealer_bids where canonical_asset_id=?"
        " and bid_time>=? and payment_capacity_verified=1", (cid, since))}

    cancelled_firm = conn.execute(
        "select count(*) from dealer_bids where canonical_asset_id=?"
        " and bid_time>=? and bid_type in ('FIRM','COMMITTED')"
        " and status='cancelled'", (cid, since)).fetchone()[0]
    settle_failed = conn.execute(
        "select count(*) from dealer_bids where canonical_asset_id=?"
        " and bid_time>=? and settlement_status='failed'", (cid, since)).fetchone()[0]

    # 자산 단위 전환: bid를 받은 자산 중 판매 거래로 이어진 비율
    bid_assets = {r[4] for r in rows}
    sold_assets = {r[0] for r in conn.execute(
        "select distinct asset_id from transactions where canonical_asset_id=?"
        " and transaction_type='sale' and contracted_at>=?", (cid, since))}
    conv = (len(bid_assets & sold_assets) / len(bid_assets) * 100
            if bid_assets else None)

    d2s = [r[0] for r in conn.execute(
        "select days_to_sale from transactions where canonical_asset_id=?"
        " and transaction_type='sale' and days_to_sale is not null"
        " and contracted_at>=?", (cid, since))]

    # 유찰: bid는 받았지만 팔리지 않았고 마지막 bid가 오래된 자산
    cutoff = (as_of - timedelta(days=FAILED_LISTING_DAYS)).isoformat()
    failed = 0
    for aid in bid_assets - sold_assets:
        last = conn.execute("select max(bid_time) from dealer_bids where"
                            " asset_id=?", (aid,)).fetchone()[0]
        if last and last < cutoff:
            failed += 1

    return {
        "canonical_asset_id": cid, "as_of": as_of.isoformat(),
        "window_days": window_days,
        "bid_count": total_bids,
        "unique_bidders": len(buyers),
        "unique_qualified_bidders": len(verified_buyers),
        "firm_bid_count": len(firm_rows),
        "bid_dispersion_pct": (round((pct(prices, 0.9) - pct(prices, 0.1))
                                     / pct(prices, 0.5) * 100, 1)
                               if len(prices) >= 3 else None),
        "top1_buyer_share_pct": (round(top[0] / total_bids * 100, 1)
                                 if total_bids else None),
        "top3_buyer_share_pct": (round(sum(top[:3]) / total_bids * 100, 1)
                                 if total_bids else None),
        "firm_bid_cancellation_count": cancelled_firm,
        "settlement_failure_count": settle_failed,
        "bid_to_sale_conversion_pct": round(conv, 1) if conv is not None else None,
        "days_to_sale_median": pct(d2s, 0.5),
        "failed_listing_count": failed,
    }


def write_snapshot(conn, cid, env, window_days=180, as_of=None):
    m = metrics(conn, cid, window_days, as_of)
    sid = str(uuid.uuid4())
    conn.execute(
        "insert into liquidity_snapshots (snapshot_id, snapshot_date,"
        " canonical_asset_id, window_days, unique_qualified_bidders, bid_count,"
        " firm_bid_count, bid_dispersion_pct, top1_buyer_share_pct,"
        " top3_buyer_share_pct, bid_to_sale_conversion_pct, days_to_sale_median,"
        " failed_listing_count, data_environment)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, m["as_of"], cid, window_days, m["unique_qualified_bidders"],
         m["bid_count"], m["firm_bid_count"], m["bid_dispersion_pct"],
         m["top1_buyer_share_pct"], m["top3_buyer_share_pct"],
         m["bid_to_sale_conversion_pct"], m["days_to_sale_median"],
         m["failed_listing_count"], env))
    conn.commit()
    return sid
