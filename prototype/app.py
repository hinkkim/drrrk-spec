#!/usr/bin/env python3
"""드르륵 자산 분석 프로그램 — 로컬 웹 앱 (설치 불필요, 표준 라이브러리만).

  python3 app.py            # → http://localhost:8765 접속
  python3 app.py --port 9000

브라우저에서 자산을 입력하면 분석 결과(식별 → 시세 → 청산가치 → 유동성 → 권장 LTV)를 보여준다.
CLI 버전은 analyze.py, 실데이터 입력은 ingest.py.
"""
import argparse
import html
import json
import sqlite3
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

import analyze as az

STYLE = """<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { color-scheme: light dark;
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --ring:rgba(11,11,11,.1); --grid:#e1e0d9; --accent:#2a78d6; --good:#006300; }
@media (prefers-color-scheme: dark) { :root {
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
  --ring:rgba(255,255,255,.1); --grid:#2c2c2a; --accent:#3987e5; --good:#0ca30c; } }
* { box-sizing:border-box }
body { margin:0; background:var(--plane); color:var(--ink); font-size:14px; line-height:1.55;
  font-family:system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic","Segoe UI",sans-serif; }
.wrap { max-width:760px; margin:0 auto; padding:28px 18px 60px; display:flex; flex-direction:column; gap:16px; }
.eyebrow { font-size:11px; letter-spacing:.12em; color:var(--muted); }
h1 { font-size:20px; margin:2px 0 0; } h1 a { color:inherit; text-decoration:none; }
.card { background:var(--surface); border:1px solid var(--ring); border-radius:8px; padding:18px 20px; }
.card h2 { font-size:15px; margin:0 0 10px; }
form.row { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--ink2); }
input, select { font:inherit; color:var(--ink); background:var(--plane); border:1px solid var(--grid);
  border-radius:6px; padding:8px 10px; min-width:120px; }
input:focus, select:focus { outline:2px solid var(--accent); outline-offset:1px; }
button { font:inherit; font-weight:600; color:#fff; background:var(--accent); border:none;
  border-radius:6px; padding:9px 18px; cursor:pointer; }
.kv { display:grid; grid-template-columns:max-content 1fr; gap:6px 18px; font-variant-numeric:tabular-nums; }
.kv dt { color:var(--ink2); } .kv dd { margin:0; font-weight:600; }
.kv dd.big { font-size:20px; } .kv dd.ltv { color:var(--good); font-size:20px; }
.note { color:var(--muted); font-size:12px; margin-top:10px; max-width:70ch; }
table { border-collapse:collapse; width:100%; font-size:12.5px; margin-top:6px; }
th,td { padding:6px 9px; text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
th { color:var(--muted); font-weight:600; border-bottom:1px solid var(--grid); }
td:first-child, th:first-child { text-align:left; }
tbody tr { border-bottom:1px solid var(--grid); }
.warn { color:#b45309; }
.candidates a { display:block; padding:4px 0; color:var(--accent); }
</style>"""

HEADER = """<div class="wrap">
<div><div class="eyebrow">DRRRK · ASSET ANALYZER — PROTOTYPE</div>
<h1><a href="/">실물자산 분석 프로그램</a></h1></div>"""

FORMS = """
<div class="card"><h2>브랜드 자산 분석 <span style="color:var(--muted);font-weight:400">— 원장 데이터 기반 (비표준 자산)</span></h2>
<form class="row" action="/asset" method="get">
  <label>모델명 · 별칭 · canonical ID
    <input name="q" placeholder="예: 서브마리너, 클미, WATCH-ROLEX-…" required style="min-width:280px"></label>
  <label>상태 등급
    <select name="grade"><option>S</option><option selected>A</option><option>B</option><option>C</option></select></label>
  <button>분석</button>
</form></div>
<div class="card"><h2>귀금속 분석 <span style="color:var(--muted);font-weight:400">— 시세 × 순도 × 중량 (표준화 자산)</span></h2>
<form class="row" action="/gold" method="get">
  <label>순도 <select name="purity"><option selected>24K</option><option>22K</option><option>18K</option><option>14K</option></select></label>
  <label>중량 (g) <input name="weight" type="number" step="0.01" min="0.1" placeholder="18.75" required></label>
  <label>24K 1g 시세 (원) — 비우면 저장값 사용 <input name="spot" type="number" step="100" placeholder="ingest.py spot 으로 저장 가능"></label>
  <button>분석</button>
</form>
<div class="note">금은 표준화 자산이라 시세만으로 즉시 계산된다 — 은행이 이미 담보로 받는 이유.
명품은 모델·상태별 실거래 원장이 있어야 같은 답을 낼 수 있다 — 드르륵이 만드는 데이터가 그것.</div></div>"""


def w(v):
    return f"₩{v:,}" if v is not None else "—"


def p(v):
    return f"{v}%" if v is not None else "—"


def render_result(r, conn=None):
    if "error" in r:
        return f'<div class="card"><h2 class="warn">분석 불가</h2><p>{html.escape(r["error"])}</p></div>'
    a = r["asset"]
    if "brand" in a:
        title = f'{a["brand"]} {a["model"]} <span style="color:var(--muted)">({a.get("reference_no") or "-"}) · 등급 {a["grade"]}</span>'
    else:
        title = f'금 {a["purity"]} {a["weight_g"]}g <span style="color:var(--muted)">(24K {r["spot_krw_per_g_24k"]:,}원/g, {r["spot_as_of"]})</span>'
    rows = [
        ("시장가치 (MV)", f'<dd class="big">{w(r["market_value_krw"])}</dd>'),
        ("청산가치 (LV)", f'<dd class="big">{w(r["liquidation_value_krw"])}</dd>'),
    ]
    if r.get("liquidation_value_p25_krw") is not None:
        rows.append(("보수적 LV (P25)", f'<dd>{w(r["liquidation_value_p25_krw"])}</dd>'))
    rows.append(("도매할인율", f'<dd>{p(r.get("wholesale_discount_pct"))}</dd>'))
    if "bid_spread_pct" in r:
        rows += [("호가 스프레드", f'<dd>{p(r.get("bid_spread_pct"))}</dd>'),
                 ("예상 처분 소요", f'<dd>{r.get("expected_days_to_sale") or "—"}일 (판매) · {r.get("days_to_liquidate") or "—"}일 (유질)</dd>'),
                 ("유질 회수율", f'<dd>{p(r.get("recovery_rate_pct"))}</dd>')]
    rows.append(("권장 LTV", f'<dd class="ltv">{p(r.get("recommended_ltv_pct"))}</dd>'))
    if "sample" in r:
        s = r["sample"]
        rows.append(("근거 표본", f'<dd style="font-weight:400">호가 {s["quotes"]} · 성사 {s["sales"]} · 외부시세 {s["external_comps"]} · 유질처분 {s["liquidations"]} <span style="color:var(--muted)">(최근 {r["window_days"]}일)</span></dd>'))
    rows.append(("신뢰도", f'<dd>{r["confidence"]}</dd>'))
    kv = "".join(f"<dt>{k}</dt>{v}" for k, v in rows)
    note = f'<div class="note">※ {html.escape(r["note"])}</div>' if r.get("note") else ""
    recent = _recent_events(conn, a["canonical_asset_id"]) if (conn and "canonical_asset_id" in a) else ""
    return f'<div class="card"><h2>{title}</h2><dl class="kv">{kv}</dl>{note}</div>{recent}'


def _recent_events(conn, cid):
    rows = conn.execute(
        "select observed_at, event_type, deal_type, value_krw, source from valuation_event "
        "where canonical_asset_id=? order by observed_at desc limit 10", (cid,)).fetchall()
    if not rows:
        return ""
    names = {"buyer_quote": "매입 호가", "contract_price": "성사가", "external_comp": "외부 시세",
             "ai_estimate": "AI 추정", "backfill_appraisal": "감정가(백필)",
             "backfill_loan": "대출액(백필)", "backfill_liquidation": "처분가(백필)",
             "liquidation_price": "처분가", "extension_reappraisal": "재평가"}
    tr = "".join(f"<tr><td>{t[:10]}</td><td>{names.get(e, e)}</td><td>{d}</td>"
                 f"<td>{v:,}</td><td>{html.escape(s)}</td></tr>"
                 for t, e, d, v, s in rows)
    return (f'<div class="card"><h2>최근 원장 이벤트</h2><table><thead><tr>'
            f'<th>일자</th><th>유형</th><th>거래</th><th>금액(원)</th><th>출처</th></tr>'
            f'</thead><tbody>{tr}</tbody></table></div>')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/":
            body = FORMS
        elif url.path == "/asset":
            conn = sqlite3.connect(az.DB)
            cid, cands = az.find_asset(conn, q.get("q", ""))
            if cid:
                body = render_result(az.analyze_asset(conn, cid, grade=q.get("grade", "A")), conn)
            elif cands:
                links = "".join(
                    f'<a href="/asset?q={urllib.parse.quote(c)}&grade={q.get("grade","A")}">{c}</a>'
                    for c in cands)
                body = f'<div class="card"><h2>검색 결과가 여러 개입니다</h2><div class="candidates">{links}</div></div>'
            else:
                body = f'<div class="card"><h2 class="warn">검색 결과 없음</h2><p>"{html.escape(q.get("q",""))}" — 카탈로그에 없습니다. catalog_seed.csv에 추가하거나 다른 이름으로 검색하세요.</p></div>'
            conn.close()
        elif url.path == "/gold":
            conn = sqlite3.connect(az.DB) if __import__("os").path.exists(az.DB) else None
            spot = float(q["spot"]) if q.get("spot") else None
            body = render_result(az.analyze_gold(q.get("purity", "24K"),
                                                 float(q.get("weight", 0) or 0),
                                                 spot=spot, conn=conn))
            if conn:
                conn.close()
        elif url.path == "/api/asset":  # 금융기관 PoC API 형태 (JSON)
            conn = sqlite3.connect(az.DB)
            cid, _ = az.find_asset(conn, q.get("q", ""))
            payload = (az.analyze_asset(conn, cid, grade=q.get("grade", "A"))
                       if cid else {"error": "not found"})
            conn.close()
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        page = (f"<!doctype html><html lang='ko'><head>{STYLE}"
                f"<title>드르륵 자산 분석</title></head><body>{HEADER}{body}"
                f"<div class='note'>CLI: analyze.py · 실데이터 입력: ingest.py · "
                f"API: /api/asset?q=서브마리너&grade=A</div></div></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(page))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    print(f"드르륵 자산 분석 프로그램: http://localhost:{args.port}  (중지: Ctrl+C)")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
