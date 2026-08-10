"""Asset Score 리포트 + 1차 단계 오염도 분석."""
import json
import os


def asset_scores(conn):
    rows = conn.execute(
        "select m.*, a.brand, a.model from metric_snapshot m "
        "join asset_master a using (canonical_asset_id) "
        "where m.canonical_asset_id != '' order by m.sample_size desc").fetchall()
    cols = [d[0] for d in conn.execute("select * from metric_snapshot limit 0").description]
    cols += ["brand", "model"]
    return [dict(zip(cols, r)) for r in rows]


def pollution_stats(conn):
    """1차 단계(식별·상태·정가품) 오류가 원장을 얼마나 오염시켰는지 — 정답지 대조."""
    t = dict(conn.execute(
        "select 'n', count(*) from sim_truth union all "
        "select 'misid', sum(true_canonical != observed_canonical) from sim_truth union all "
        "select 'misgrade', sum(true_grade != observed_grade) from sim_truth union all "
        "select 'fake_in', sum(is_fake) from sim_truth").fetchall())
    ev = conn.execute(
        "select count(*) from valuation_event v join sim_truth s using (instance_id) "
        "where v.event_type in ('buyer_quote','contract_price') "
        "and s.true_canonical != s.observed_canonical").fetchone()[0]
    ev_total = conn.execute(
        "select count(*) from valuation_event "
        "where event_type in ('buyer_quote','contract_price') "
        "and instance_id in (select instance_id from sim_truth)").fetchone()[0]
    n = max(t.get("n", 0), 1)
    return {
        "listings": t.get("n", 0),
        "misid_rate_pct": round((t.get("misid") or 0) / n * 100, 1),
        "misgrade_rate_pct": round((t.get("misgrade") or 0) / n * 100, 1),
        "fakes_leaked": t.get("fake_in", 0),
        "polluted_price_events_pct": round(ev / max(ev_total, 1) * 100, 1),
    }


def overall_mape(conn):
    row = conn.execute(
        "select avg(mape_estimate_pct), avg(bid_spread_pct), avg(recommended_ltv_pct) "
        "from metric_snapshot where canonical_asset_id != '' "
        "and mape_estimate_pct is not null").fetchone()
    return {"mape_pct": round(row[0], 1) if row[0] else None,
            "spread_pct": round(row[1], 1) if row[1] else None,
            "avg_ltv_pct": round(row[2], 1) if row[2] else None}


def write_reports(conn, outdir, sim_stats, params):
    os.makedirs(outdir, exist_ok=True)
    scores = asset_scores(conn)
    poll = pollution_stats(conn)
    with open(os.path.join(outdir, "asset_scores.json"), "w", encoding="utf-8") as f:
        json.dump({"params": params, "sim_stats": sim_stats,
                   "pollution": poll, "scores": scores}, f, ensure_ascii=False, indent=2)

    lines = ["# 드르륵 자산 언더라이팅 원장 — 시뮬레이션 리포트", ""]
    lines.append(f"- 파라미터: {json.dumps(params, ensure_ascii=False)}")
    lines.append(f"- 등록 {sim_stats['listings']}건 / 견적 {sim_stats['quotes']}건 / "
                 f"판매 성사 {sim_stats['sales']}건 / 가품 차단 {sim_stats['fake_rejected']}건 "
                 f"(유입 {sim_stats['fake_leaked']}건) / 유저 확인 폴백 {sim_stats['user_confirms']}건")
    lines.append("")
    lines.append("## 1차 단계 오염도 (식별·상태·정가품)")
    lines.append(f"- 오식별률 {poll['misid_rate_pct']}% · 상태 오판률 {poll['misgrade_rate_pct']}% "
                 f"· 가품 유입 {poll['fakes_leaked']}건")
    lines.append(f"- **잘못된 자산 ID에 귀속된 가격 이벤트: {poll['polluted_price_events_pct']}%**")
    lines.append("")
    lines.append("## Asset Score (표본 상위)")
    lines.append("| 자산 | MV(P50) | LV(P50) | 도매할인 | Bid Depth | Spread | MAPE | 회수율 | 처분일 | 권장 LTV | 표본 |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for s in scores[:12]:
        lines.append(
            f"| {s['brand']} {s['model']} | {_won(s['market_value_p50'])} | "
            f"{_won(s['liq_value_p50'])} | {_p(s['wholesale_discount_pct'])} | "
            f"{s['bid_depth_avg'] or '—'} | {_p(s['bid_spread_pct'])} | "
            f"{_p(s['mape_estimate_pct'])} | {_p(s['recovery_rate_pct'])} | "
            f"{s['days_to_liquidate'] or '—'} | {_p(s['recommended_ltv_pct'])} | "
            f"{s['sample_size']} |")
    path = os.path.join(outdir, "summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _won(v):
    return f"{v:,}" if v else "—"


def _p(v):
    return f"{v}%" if v is not None else "—"
