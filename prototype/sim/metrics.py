"""주간 배치 — 원장(valuation_event)에서 Asset Score 지표를 산출한다.

산식 (구현 스펙 §4, ML이 아닌 분위수 통계):
  Market Value        = P50( external_comp ∪ contract_price(sale), 최근 180일 )
  Liquidation Value   = P50/P25( buyer_quote(sale) )
  Bid Spread          = (P90 − P10) / P50 of buyer_quote
  Volatility(90d)     = std( 주간 MV 변화율 ) — external_comp 시계열
  MAPE                = mean |ai_estimate − 같은 instance의 성사가| / 성사가
  Wholesale Discount  = 1 − LV_P50 / MV_P50
  Recovery Rate       = liquidation / loan_balance (백필 pawn 실측)
  Recommended LTV     = P10(buyer_quote) × (1 − 처분비용률) / MV_P50
"""
import json
import os
import statistics as st
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import pct as _pct, DISPOSAL_COST, MIN_SAMPLE


def compute_metrics(conn, as_of: date, window_days=180):
    since = (as_of - timedelta(days=window_days)).isoformat()
    cur = conn.cursor()
    assets = cur.execute("select canonical_asset_id, category from asset_master").fetchall()
    week = as_of.isoformat()
    rows = []

    for cid, cat in assets:
        ext = _vals(cur, "external_comp", cid=cid, since=since)
        sales = _vals(cur, "contract_price", cid=cid, since=since, deal="sale")
        quotes = _vals(cur, "buyer_quote", cid=cid, since=since, deal="sale",
                       exclude_fake=True)
        mv = _pct(ext + sales, 0.5)
        lv50, lv25 = _pct(quotes, 0.5), _pct(quotes, 0.25)
        spread = ((_pct(quotes, 0.9) - _pct(quotes, 0.1)) / lv50 * 100
                  if lv50 and len(quotes) >= MIN_SAMPLE else None)

        depth = _bid_depth(cur, cid, since)
        vol = _volatility(cur, cid, as_of)
        mape = _mape(cur, cid, since)
        rec = _recovery(cur, cid)
        wd = (1 - lv50 / mv) * 100 if (mv and lv50) else None
        p10 = _pct(quotes, 0.10)
        ltv = (p10 * (1 - DISPOSAL_COST) / mv * 100
               if (mv and p10 and len(quotes) >= MIN_SAMPLE) else None)
        n = len(ext) + len(sales) + len(quotes)
        rows.append((week, cid, cat, _i(mv), _i(lv50), _i(lv25), depth, _r(spread),
                     _r(vol), _r(mape), _r(wd), _r(rec["rate"]), _r(rec["days"]),
                     _r(ltv), n))

    cur.executemany(
        "insert or replace into metric_snapshot values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    return rows


def _vals(cur, etype, cid, since, deal=None, exclude_fake=False):
    q = ("select value_krw, meta from valuation_event where event_type=? "
         "and canonical_asset_id=? and observed_at>=?")
    args = [etype, cid, since]
    if deal:
        q += " and deal_type=?"
        args.append(deal)
    out = []
    for v, meta in cur.execute(q, args):
        if exclude_fake and json.loads(meta or "{}").get("flagged_fake"):
            continue
        out.append(v)
    return out


def _bid_depth(cur, cid, since):
    row = cur.execute(
        "select avg(c) from (select count(*) c from valuation_event "
        "where event_type='buyer_quote' and canonical_asset_id=? and observed_at>=? "
        "and instance_id is not null group by instance_id)", (cid, since)).fetchone()
    return round(row[0], 2) if row and row[0] else None


def _volatility(cur, cid, as_of):
    since = (as_of - timedelta(days=90)).isoformat()
    rows = cur.execute(
        "select json_extract(meta,'$.week') w, avg(value_krw) from valuation_event "
        "where event_type='external_comp' and canonical_asset_id=? and observed_at>=? "
        "group by w order by w", (cid, since)).fetchall()
    series = [v for _, v in rows]
    if len(series) < 4:
        return None
    changes = [(b - a) / a * 100 for a, b in zip(series, series[1:])]
    return st.pstdev(changes)


def _mape(cur, cid, since):
    rows = cur.execute(
        "select e.value_krw, s.value_krw from valuation_event e "
        "join valuation_event s on s.instance_id = e.instance_id "
        " and s.event_type='contract_price' and s.deal_type='sale' "
        "where e.event_type='ai_estimate' and e.canonical_asset_id=? "
        " and e.observed_at>=?", (cid, since)).fetchall()
    if not rows:
        return None
    return sum(abs(est - act) / act for est, act in rows) / len(rows) * 100


def _recovery(cur, cid):
    rows = cur.execute(
        "select value_krw, meta from valuation_event "
        "where event_type in ('backfill_liquidation','liquidation_price') "
        "and canonical_asset_id=?", (cid,)).fetchall()
    rates, days = [], []
    for liq, meta in rows:
        m = json.loads(meta or "{}")
        if m.get("loan_balance"):
            rates.append(liq / m["loan_balance"] * 100)
        if m.get("days_to_liquidate"):
            days.append(m["days_to_liquidate"])
    return {"rate": (sum(rates) / len(rates)) if rates else None,
            "days": (sum(days) / len(days)) if days else None}


def _i(v):
    return int(v) if v is not None else None


def _r(v):
    return round(v, 1) if v is not None else None
