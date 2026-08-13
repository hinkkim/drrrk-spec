"""Evidence Report (§18) — LTV 계산기가 아니라 근거 보고서를 조립한다.

섹션: IDENTITY / CONDITION / AUTHENTICITY / MARKET / DEALER MARKET /
      LIQUIDITY / LIQUIDATION / OUTCOME / DATA QUALITY
모든 숫자에 표본수·freshness·confidence가 붙고, 부족하면 부족하다고 말한다.
JSON 하나로 조립되며 CLI(analyze.py)·웹(app.py)·API(/api/asset)가 공유한다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import baseline, liquidity, liquidation
from intake.verify import authenticity_status


def build(conn, cid, grade="A", asset_id=None, window_days=180):
    """canonical 자산 1개의 Evidence Report. asset_id를 주면 개별 실물 기준
    (식별 상태·진위·correction 이력이 그 실물의 것으로 채워진다)."""
    meta = conn.execute(
        "select category, brand, model, reference_no from asset_master"
        " where canonical_asset_id=?", (cid,)).fetchone()
    if not meta:
        return {"error": f"미등록 자산: {cid}"}
    cat, brand, model, ref = meta

    identity = _identity(conn, cid, asset_id)
    layers = baseline.value_layers(conn, cid, window_days)
    liq = liquidity.metrics(conn, cid, window_days)
    compat = baseline.analyze_asset_compat(
        conn, cid, grade=grade, window_days=window_days,
        identity_verified=(identity["human_verified"] if asset_id else True))
    est = {h: liquidation.estimate(conn, cid, h, grade=grade,
                                   window_days=window_days, asset_id=asset_id)
           for h in (7, 30)}

    return {
        "asset": {"canonical_asset_id": cid, "category": cat, "brand": brand,
                  "model": model, "reference_no": ref, "grade": grade,
                  "asset_id": asset_id},
        "as_of": layers["as_of"], "window_days": window_days,
        "identity": identity,
        "condition": _condition(conn, asset_id, grade),
        "authenticity": _authenticity(conn, asset_id),
        "market": {"retail_asking": layers["retail_asking"],
                   "observed_sold": layers["observed_sold"]},
        "dealer_market": {
            "dealer_indicative": layers["dealer_indicative"],
            "dealer_firm": layers["dealer_firm"],
            "unique_bidders": liq["unique_bidders"],
            "unique_qualified_bidders": liq["unique_qualified_bidders"],
            "firm_bid_count": liq["firm_bid_count"],
            "bid_dispersion_pct": liq["bid_dispersion_pct"],
            "top1_buyer_share_pct": liq["top1_buyer_share_pct"],
            "firm_bid_cancellation_count": liq["firm_bid_cancellation_count"],
            "settlement_failure_count": liq["settlement_failure_count"],
        },
        "liquidity": {
            "bid_to_sale_conversion_pct": liq["bid_to_sale_conversion_pct"],
            "days_to_sale_median": liq["days_to_sale_median"],
            "failed_listing_count": liq["failed_listing_count"],
            "time_to_first_bid_days": liq["time_to_first_bid_days"],
            "time_to_first_firm_bid_days": liq["time_to_first_firm_bid_days"],
        },
        "liquidation": {
            "expected_7d": _est_view(est[7]),
            "expected_30d": _est_view(est[30]),
        },
        "outcome": _outcome(conn, cid, asset_id),
        "ltv": {
            "recommended_pct": compat["recommended_ltv_pct"],
            "status": ("AVAILABLE" if compat["recommended_ltv_pct"] is not None
                       else "NOT_AVAILABLE"),
            "reasons": compat["ltv_reasons"],
            "indicative_reference_pct": compat["indicative_ltv_reference_pct"],
        },
        "data_quality": _data_quality(conn, cid, compat, asset_id),
        "rule_version": compat["rule_version"],
    }


def _identity(conn, cid, asset_id):
    out = {"human_verified": False, "identity_status": None,
           "ai_top_candidate": None, "ai_confidence": None,
           "correction_count": 0}
    if asset_id:
        row = conn.execute("select identity_status from assets where asset_id=?",
                           (asset_id,)).fetchone()
        out["identity_status"] = row[0] if row else None
        out["human_verified"] = bool(row and row[0] == "HUMAN_VERIFIED")
        pred = conn.execute(
            "select payload, confidence from ai_predictions where asset_id=?"
            " and prediction_type='identity' order by observed_at desc limit 1",
            (asset_id,)).fetchone()
        if pred:
            cands = json.loads(pred[0]).get("candidates", [])
            out["ai_top_candidate"] = (cands[0]["canonical_asset_id"]
                                       if cands else None)
            out["ai_confidence"] = pred[1]
        out["correction_count"] = conn.execute(
            "select count(*) from verification_corrections c join"
            " human_verifications v using (verification_id) where v.asset_id=?",
            (asset_id,)).fetchone()[0]
    else:
        n = conn.execute("select count(*) from assets where canonical_asset_id=?"
                         " and identity_status='HUMAN_VERIFIED'", (cid,)).fetchone()[0]
        out["human_verified"] = n > 0
        out["identity_status"] = f"{n} verified assets"
    return out


def _condition(conn, asset_id, grade):
    if not asset_id:
        return {"grade": grade, "assessment_count": None,
                "note": "canonical 레벨 조회 — 등급은 입력값"}
    rows = conn.execute(
        "select grade, source_type, observed_at from condition_assessments"
        " where asset_id=? order by observed_at desc", (asset_id,)).fetchall()
    return {"grade": rows[0][0] if rows else grade,
            "assessment_count": len(rows),
            "expert_assessed": any(r[1] == "EXPERT_ESTIMATE" for r in rows)}


def _authenticity(conn, asset_id):
    if not asset_id:
        return {"status": "N/A", "evidence_count": None}
    n = conn.execute("select count(*) from authentication_evidence where"
                     " asset_id=?", (asset_id,)).fetchone()[0]
    return {"status": authenticity_status(conn, asset_id), "evidence_count": n}


def _est_view(e):
    return {"range_low_krw": e["range_low_krw"],
            "range_mid_krw": e["range_mid_krw"],
            "range_high_krw": e["range_high_krw"],
            "confidence": e["confidence"], "reasons": e["reason_codes"],
            "input_sample": e["input_sample"]}


def _outcome(conn, cid, asset_id):
    cond, args = "canonical_asset_id=?", [cid]
    if asset_id:
        cond, args = "asset_id=?", [asset_id]
    rows = conn.execute(
        f"select transaction_id, gross_price_krw, total_costs_krw,"
        f" net_proceeds_krw, costs_unknown, days_to_sale, settled_at"
        f" from v_net_proceeds where {cond} and transaction_type='sale'"
        f" order by settled_at desc limit 5", args).fetchall()
    cols = ("transaction_id", "gross_krw", "costs_krw", "net_proceeds_krw",
            "costs_unknown", "days_to_sale", "settled_at")
    return {"recent_transactions": [dict(zip(cols, r)) for r in rows]}


def _data_quality(conn, cid, compat, asset_id):
    missing = []
    if asset_id:
        if not conn.execute("select 1 from asset_images where asset_id=? limit 1",
                            (asset_id,)).fetchone():
            missing.append("images")
        if not conn.execute("select 1 from condition_assessments where asset_id=?"
                            " limit 1", (asset_id,)).fetchone():
            missing.append("condition_assessment")
        if not conn.execute("select 1 from authentication_evidence where asset_id=?"
                            " limit 1", (asset_id,)).fetchone():
            missing.append("authentication_evidence")
    s = compat["sample"]
    grade = ("A" if s["settled_sales"] >= 3 and s["firm_bids"] >= 5 else
             "B" if s["firm_bids"] >= 2 or s["settled_sales"] >= 1 else
             "C" if s["quotes"] else "D")
    return {"sample": s, "evidence_grade": grade, "missing_fields": missing,
            "environment_mix": dict(conn.execute(
                "select data_environment, count(*) from dealer_bids"
                " where canonical_asset_id=? group by data_environment", (cid,)))}


# ── 텍스트 렌더 (CLI용) ───────────────────────────────────────────────────
def render_text(r):
    if "error" in r:
        return f"오류: {r['error']}"
    a = r["asset"]
    w = lambda v: f"₩{v:,}" if v is not None else "—"
    L = []
    L.append(f"\n■ ASSET  {a['brand']} {a['model']} ({a.get('reference_no') or '-'})"
             f" · 등급 {a['grade']} · 기준일 {r['as_of']} (최근 {r['window_days']}일)")
    i = r["identity"]
    L.append(f"  IDENTITY      검증: {'YES' if i['human_verified'] else 'NO'}"
             f" ({i['identity_status']})"
             + (f" · AI top-1 {i['ai_top_candidate']} ({i['ai_confidence']})"
                if i["ai_top_candidate"] else "")
             + (f" · correction {i['correction_count']}건"
                if i["correction_count"] else ""))
    c, au = r["condition"], r["authenticity"]
    L.append(f"  CONDITION     등급 {c['grade']} · 평가 {c.get('assessment_count')}건")
    L.append(f"  AUTHENTICITY  {au['status']} · 근거 {au.get('evidence_count')}건")
    m = r["market"]
    L.append(f"  MARKET        호가시세 {w(m['retail_asking']['median_krw'])}"
             f" (n={m['retail_asking']['n']}) · sold {w(m['observed_sold']['median_krw'])}"
             f" (n={m['observed_sold']['n']})")
    d = r["dealer_market"]
    L.append(f"  DEALER        indicative {w(d['dealer_indicative']['median_krw'])}"
             f" (n={d['dealer_indicative']['n']}) · firm {w(d['dealer_firm']['median_krw'])}"
             f" (n={d['firm_bid_count']}) · 바이어 {d['unique_bidders']}명"
             f" · 분산 {d['bid_dispersion_pct'] or '—'}%")
    lq = r["liquidity"]
    L.append(f"  LIQUIDITY     성사 전환 {lq['bid_to_sale_conversion_pct'] or '—'}%"
             f" · 처분 중위 {lq['days_to_sale_median'] or '—'}일"
             f" · 첫 bid {lq['time_to_first_bid_days'] if lq['time_to_first_bid_days'] is not None else '—'}일"
             f" / 첫 FIRM {lq['time_to_first_firm_bid_days'] if lq['time_to_first_firm_bid_days'] is not None else '—'}일"
             f" · 유찰 {lq['failed_listing_count']}건")
    for h in ("expected_7d", "expected_30d"):
        e = r["liquidation"][h]
        if e["range_mid_krw"] is not None:
            L.append(f"  LIQUIDATION   {h[9:]}: {w(e['range_low_krw'])} ~ "
                     f"{w(e['range_high_krw'])} (mid {w(e['range_mid_krw'])})"
                     f" · {e['confidence']}"
                     + (f" · {','.join(e['reasons'])}" if e["reasons"] else ""))
        else:
            L.append(f"  LIQUIDATION   {h[9:]}: INSUFFICIENT DATA"
                     f" — {', '.join(e['reasons'])}")
    o = r["outcome"]["recent_transactions"]
    if o:
        t = o[0]
        L.append(f"  OUTCOME       최근 성사 {w(t['gross_krw'])} − 비용 "
                 f"{w(t['costs_krw'])} = net {w(t['net_proceeds_krw'])}"
                 + (" (비용 미상)" if t["costs_unknown"] else ""))
    ltv = r["ltv"]
    if ltv["status"] == "AVAILABLE":
        L.append(f"  LTV           권장 {ltv['recommended_pct']}%")
    else:
        L.append(f"  LTV           NOT AVAILABLE — {', '.join(ltv['reasons'])}"
                 + (f" (indicative 참고치 {ltv['indicative_reference_pct']}%"
                    f" — 권장 아님)" if ltv["indicative_reference_pct"] else ""))
    q = r["data_quality"]
    L.append(f"  DATA QUALITY  evidence grade {q['evidence_grade']}"
             f" · firm {q['sample']['firm_bids']} · 정산 {q['sample']['settled_sales']}"
             f" · 누락 {','.join(q['missing_fields']) or '없음'}"
             f" · 환경 {q['environment_mix']}")
    return "\n".join(L) + "\n"
