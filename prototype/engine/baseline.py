"""Dealer Median baseline — v1 원장 위의 분위수 통계 (§14의 비교 기준선).

이후의 Rule Engine·ML은 out-of-sample에서 이 baseline을 이겨야만 배포된다.

가격은 하나의 숫자가 아니라 §11의 레이어로 산출한다:
  retail_asking / observed_sold / dealer_indicative / dealer_firm / settled(net)
각 레이어에 표본수와 freshness(최신 관측일)를 병기한다.
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import (pct, GRADE_MULT, DISPOSAL_COST, MIN_SAMPLE,
                           STALE_DAYS)

RULE_VERSION = "baseline-v1.0"

# 가격 통계에 포함하는 bid status (취소·거절·중복단계 제외)
PRICE_STATUSES = ("active", "expired", "selected", "settled")
FIRM_TYPES = ("FIRM", "COMMITTED", "SETTLED")


def find_asset(conn, query):
    """canonical ID 정확 일치 → 별칭/모델 부분 일치. (cid, 후보목록) 반환."""
    row = conn.execute("select canonical_asset_id from asset_master where"
                       " canonical_asset_id=? and status='active'",
                       (query,)).fetchone()
    if row:
        return row[0], []
    like = f"%{query}%"
    rows = conn.execute(
        "select canonical_asset_id from asset_master where status='active' and"
        " (aliases like ? or model like ? or brand||' '||model like ?)",
        (like, like, like)).fetchall()
    if len(rows) == 1:
        return rows[0][0], []
    return None, [r[0] for r in rows]


def until_of(as_of):
    """as_of '당일 포함' 상한 — ISO 문자열 비교용 (다음날 0시 미만)."""
    return (as_of + timedelta(days=1)).isoformat()


def value_layers(conn, cid, window_days=180, as_of=None):
    """§11 가격 레이어 — 각각 {median, n, latest}. 표본 없으면 median=None.

    as_of를 주면 그 시점까지의 데이터만 사용한다 (백테스트의 시간 절단)."""
    as_of = as_of or latest_date(conn)
    since = (as_of - timedelta(days=window_days)).isoformat()
    until = until_of(as_of)

    def layer(rows):
        vals = [r[0] for r in rows]
        latest = max((r[1] for r in rows), default=None)
        return {"median_krw": _i(pct(vals, 0.5)), "n": len(vals),
                "latest": latest[:10] if latest else None,
                "stale": _stale(latest, as_of)}

    listing = conn.execute(
        "select price_krw, observed_at from market_events where"
        " canonical_asset_id=? and source_type='PUBLIC_LISTING'"
        " and observed_at>=? and observed_at<?", (cid, since, until)).fetchall()
    sold = conn.execute(
        "select price_krw, observed_at from market_events where"
        " canonical_asset_id=? and source_type='EXTERNAL_SOLD'"
        " and observed_at>=? and observed_at<?", (cid, since, until)).fetchall()
    indicative = _bid_rows(conn, cid, since, firm=False, until=until)
    firm = _bid_rows(conn, cid, since, firm=True, until=until)
    settled = conn.execute(
        "select net_proceeds_krw, settled_at from v_net_proceeds"
        " where canonical_asset_id=? and transaction_type='sale'"
        " and settled_at is not null and settled_at>=? and settled_at<?",
        (cid, since, until)).fetchall()

    return {
        "as_of": as_of.isoformat(), "window_days": window_days,
        "retail_asking": layer(listing),
        "observed_sold": layer(sold),
        "dealer_indicative": layer(indicative),
        "dealer_firm": layer(firm),
        "actual_net_proceeds": layer(settled),
    }


def analyze_asset_compat(conn, cid, grade="A", window_days=180, as_of=None,
                         identity_verified=True):
    """구 analyze.analyze_asset과 같은 키를 내는 호환 산출 (v1 테이블 기반).

    권장 LTV는 §12 게이트를 통과할 때만 값이 나온다. 미달 시 None +
    ltv_reasons에 사유 코드. 참고용 indicative 기반 값은 별도 키로 분리.
    """
    as_of = as_of or latest_date(conn)
    since = (as_of - timedelta(days=window_days)).isoformat()
    until = until_of(as_of)
    meta = conn.execute("select category, brand, model, reference_no from"
                        " asset_master where canonical_asset_id=?", (cid,)).fetchone()
    if not meta:
        return {"error": f"미등록 자산: {cid}"}
    cat, brand, model, ref = meta

    ext = [r[0] for r in conn.execute(
        "select price_krw from market_events where canonical_asset_id=?"
        " and observed_at>=? and observed_at<?", (cid, since, until))]
    sales = conn.execute(
        "select gross_price_krw, days_to_sale from transactions where"
        " canonical_asset_id=? and transaction_type='sale'"
        " and contracted_at>=? and contracted_at<?", (cid, since, until)).fetchall()
    settled_n = conn.execute(
        "select count(*) from transactions where canonical_asset_id=?"
        " and transaction_type='sale' and settled_at is not null"
        " and contracted_at>=? and contracted_at<?", (cid, since, until)).fetchone()[0]
    quotes = [r[0] for r in _bid_rows(conn, cid, since, firm=None, until=until)]
    firm = [r[0] for r in _bid_rows(conn, cid, since, firm=True, until=until)]
    latest_bid = conn.execute(
        "select max(bid_time) from dealer_bids where canonical_asset_id=?"
        " and bid_time<?", (cid, until)).fetchone()[0]

    gm = GRADE_MULT.get(grade, 1.0)
    mv = pct(ext + [s[0] for s in sales], 0.5)
    base = firm if len(firm) >= MIN_SAMPLE else quotes
    lv50, lv25, p10 = pct(base, 0.5), pct(base, 0.25), pct(base, 0.10)
    n = len(base)
    d2s = [s[1] for s in sales if s[1] is not None]
    rec = _recovery(conn, cid)

    # ── §12 게이트: FIRM 표본 + 정산 실측 + 식별 확정 없이는 LTV를 내지 않는다 ──
    reasons = []
    if not identity_verified:
        reasons.append("identification_unverified")
    if len(firm) < MIN_SAMPLE:
        reasons.append("no_firm_bid" if not firm else "sample_too_small")
    if settled_n < 3:
        reasons.append("no_settled_transaction")
    if _stale(latest_bid, as_of):
        reasons.append("stale_market_evidence")
    ltv = (round(p10 * (1 - DISPOSAL_COST) / mv * 100, 1)
           if (mv and p10 and not reasons) else None)
    indicative_ref = (round(pct(quotes, 0.10) * (1 - DISPOSAL_COST) / mv * 100, 1)
                      if (mv and quotes and len(quotes) >= MIN_SAMPLE and
                          ltv is None) else None)

    out = {
        "asset": {"canonical_asset_id": cid, "category": cat, "brand": brand,
                  "model": model, "reference_no": ref, "grade": grade},
        "as_of": as_of.isoformat(), "window_days": window_days,
        "market_value_krw": _g(mv, gm),
        "liquidation_value_krw": _g(lv50, gm),
        "liquidation_value_p25_krw": _g(lv25, gm),
        "wholesale_discount_pct": (round((1 - lv50 / mv) * 100, 1)
                                   if mv and lv50 else None),
        "bid_spread_pct": (round((pct(base, 0.9) - p10) / lv50 * 100, 1)
                           if lv50 and n >= MIN_SAMPLE else None),
        "expected_days_to_sale": (round(sum(d2s) / len(d2s), 1) if d2s else None),
        "recovery_rate_pct": rec["rate"],
        "days_to_liquidate": rec["days"],
        "recommended_ltv_pct": ltv,
        "ltv_reasons": reasons,
        "indicative_ltv_reference_pct": indicative_ref,  # 참고치 — 권장이 아니다
        "sample": {"external_comps": len(ext), "sales": len(sales),
                   "settled_sales": settled_n, "quotes": len(quotes),
                   "firm_bids": len(firm), "liquidations": rec["n"]},
        "confidence": ("high" if len(firm) >= 30 else
                       "medium" if len(firm) >= MIN_SAMPLE else
                       "low" if n >= MIN_SAMPLE else "insufficient"),
        "rule_version": RULE_VERSION,
    }
    if out["confidence"] == "insufficient":
        out["note"] = ("표본 부족 — 가격 산출 불가. 견적(bid)·실거래를 "
                       "intake/ingest.py로 입력하세요.")
    return out


def latest_date(conn):
    rows = [conn.execute("select max(bid_time) from dealer_bids").fetchone()[0],
            conn.execute("select max(observed_at) from market_events").fetchone()[0],
            conn.execute("select max(contracted_at) from transactions").fetchone()[0]]
    dates = [r[:10] for r in rows if r]
    return date.fromisoformat(max(dates)) if dates else date.today()


def _bid_rows(conn, cid, since, firm, until=None):
    """(price, bid_time) 목록. firm=True → FIRM 이상, False → INDICATIVE만,
    None → 전체. superseded(단계 중복)·cancelled·rejected 제외, 가품 플래그 제외.
    until을 주면 그 시각 미만의 bid만 (백테스트의 시간 절단)."""
    q = ("select bid_price_krw, bid_time, meta from dealer_bids where"
         " canonical_asset_id=? and bid_time>=? and status in "
         f"{PRICE_STATUSES!r}")
    args = [cid, since]
    if until:
        q += " and bid_time<?"
        args.append(until)
    if firm is True:
        q += f" and bid_type in {FIRM_TYPES!r}"
    elif firm is False:
        q += " and bid_type='INDICATIVE'"
    out = []
    for v, t, m in conn.execute(q, args):
        if json.loads(m or "{}").get("flagged_fake"):
            continue
        out.append((v, t))
    return out


def _recovery(conn, cid):
    rows = conn.execute(
        "select gross_price_krw, meta from transactions where"
        " canonical_asset_id=? and transaction_type='liquidation'", (cid,)).fetchall()
    rates, days = [], []
    for liq, meta in rows:
        m = json.loads(meta or "{}")
        if m.get("loan_balance"):
            rates.append(liq / m["loan_balance"] * 100)
        if m.get("days_to_liquidate"):
            days.append(m["days_to_liquidate"])
    return {"rate": round(sum(rates) / len(rates), 1) if rates else None,
            "days": round(sum(days) / len(days), 1) if days else None,
            "n": len(rows)}


def _stale(latest, as_of):
    if not latest:
        return True
    return (as_of - date.fromisoformat(latest[:10])).days > STALE_DAYS


def _i(v):
    return int(v) if v is not None else None


def _g(v, gm):
    return int(v * gm) if v is not None else None
