#!/usr/bin/env python3
"""드르륵 자산 분석 프로그램 — 로컬 웹 앱 (V1, Evidence Report 중심).

  python3 app.py                # REAL 원장 → http://localhost:8765
  python3 app.py --env SIM      # 시뮬레이션 원장 조회
  python3 app.py --port 9000

LTV 계산기가 아니라 근거 보고서를 보여준다: 식별·진위·시장·딜러·유동성·청산·
실측·데이터 품질. 표본이 부족하면 숫자 대신 '산출 불가 + 사유'가 나온다 (§12).
CLI: analyze.py · 실데이터 입력: intake/ingest.py · API: /api/asset
"""
import argparse
import html
import json
import os
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db as coredb
from engine import baseline
from report import asset_report, console
import analyze as az

STYLE = """<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { color-scheme: light dark;
  --plane:#eef0ef; --surface:#f9faf9; --ink:#131717; --ink2:#49524f; --muted:#7c8582;
  --ring:#d7dcda; --grid:#e3e7e5; --accent:#0e7264; --accent-soft:rgba(14,114,100,.08);
  --brass:#8a6b2d; --good:#1d7a3e; --warn:#b05416;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace; }
@media (prefers-color-scheme: dark) { :root {
  --plane:#0e1112; --surface:#151a1a; --ink:#eef1f0; --ink2:#b7c0bd; --muted:#79837f;
  --ring:#2b3231; --grid:#202625; --accent:#31a892; --accent-soft:rgba(49,168,146,.1);
  --brass:#c9a45c; --good:#43b365; --warn:#dd8a45; } }
* { box-sizing:border-box }
body { margin:0; background:var(--plane); color:var(--ink); font-size:14px; line-height:1.5;
  font-family:system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic","Segoe UI",sans-serif; }
.wrap { max-width:860px; margin:0 auto; padding:26px 20px 70px; display:flex; flex-direction:column; gap:14px; }
.eyebrow { font:700 11px var(--mono); letter-spacing:.3em; }
.eyebrow b { color:var(--accent); } .eyebrow .badge { margin-left:10px; letter-spacing:.1em; }
h1 { font-size:20px; font-weight:750; letter-spacing:-.01em; margin:6px 0 0;
  padding-bottom:12px; border-bottom:2px solid var(--ink); }
h1 a { color:inherit; text-decoration:none; }
.card { background:var(--surface); border:1px solid var(--ring); padding:15px 20px 17px; }
.card h2 { font:600 10.5px var(--mono); letter-spacing:.14em; text-transform:uppercase;
  margin:0 0 10px; color:var(--muted); }
.row { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
.row label { min-width:0; } .row input, .row select { min-width:130px; }
label { display:flex; flex-direction:column; gap:4px; font-size:11.5px; color:var(--ink2); }
input, select { font:inherit; color:var(--ink); background:var(--plane); border:1px solid var(--ring);
  border-radius:2px; padding:8px 10px; min-width:120px; }
input:focus, select:focus, button:focus-visible { outline:2px solid var(--accent); outline-offset:0; }
button { font:inherit; font-weight:600; font-size:13px; color:var(--surface); background:var(--ink);
  border:none; border-radius:2px; padding:9px 18px; cursor:pointer; }
button:hover { background:var(--accent); }
.kv { display:grid; grid-template-columns:max-content 1fr; gap:6px 20px; }
.kv dt { color:var(--ink2); font-size:12.5px; padding-top:1px; }
.kv dd { margin:0; font-weight:600; font-family:var(--mono); font-size:13px; letter-spacing:-.01em; }
.big { font-size:18px; } .good { color:var(--good); } .warn { color:var(--warn); }
.note { color:var(--muted); font-size:12px; max-width:74ch; }
.badge { display:inline-block; font:700 10px var(--mono); letter-spacing:.09em;
  text-transform:uppercase; border-radius:2px; padding:2px 7px;
  border:1px solid currentColor; color:var(--warn); }
.candidates a { display:block; padding:7px 0; color:var(--accent);
  border-bottom:1px solid var(--grid); text-decoration:none; }
.candidates a:last-child { border-bottom:none; }
table { border-collapse:collapse; width:100%; font-size:12.5px; }
th,td { padding:6px 9px; text-align:right; white-space:nowrap; }
td { font-family:var(--mono); letter-spacing:-.01em; }
td:first-child { font-family:inherit; }
th { font:600 10px var(--mono); letter-spacing:.12em; text-transform:uppercase;
  color:var(--muted); border-bottom:1px solid var(--ring); }
td:first-child, th:first-child { text-align:left; padding-left:0; }
th:first-child { padding-left:0; }
tbody tr { border-bottom:1px solid var(--grid); }
tbody tr:last-child { border-bottom:none; }
</style>"""


def w(v):
    return f"₩{v:,}" if v is not None else "—"


def p(v):
    return f"{v}%" if v is not None else "—"


def esc(s):
    return html.escape(str(s))


def header(env):
    tag = "Simulation data" if env == "SIMULATION" else "Real ledger"
    tag_color = "var(--warn)" if env == "SIMULATION" else "var(--good)"
    return (f'<div class="wrap"><div><div class="eyebrow">DRRRK<b>·</b>ASSET'
            f' INTELLIGENCE <span class="badge" style="color:{tag_color}">{tag}</span></div>'
            f'<h1><a href="/">실물자산 Evidence Report</a>'
            f' <span style="font-size:13px;font-weight:400">·'
            f' <a href="/console" style="color:var(--accent);text-decoration:none">'
            f'검증 콘솔</a></span></h1></div>')


FORMS = """
<div class="card"><h2>브랜드 자산 — EVIDENCE REPORT</h2>
<form class="row" action="/asset" method="get">
  <label>모델명 · 별칭 · canonical ID
    <input name="q" placeholder="예: 서브마리너, 클미, WATCH-ROLEX-…" required style="min-width:280px"></label>
  <label>상태 등급
    <select name="grade"><option>S</option><option selected>A</option><option>B</option><option>C</option></select></label>
  <button>분석</button>
</form>
<div class="note" style="margin-top:8px">식별 → 진위 → 시장 → 딜러 호가(단계별) → 유동성 → 청산 범위 → 실측 → 데이터 품질.
표본이 부족하면 숫자 대신 "산출 불가 + 사유"가 나온다.</div></div>
<div class="card"><h2>귀금속 — 표준화 자산</h2>
<form class="row" action="/gold" method="get">
  <label>순도 <select name="purity"><option selected>24K</option><option>22K</option><option>18K</option><option>14K</option></select></label>
  <label>중량 (g) <input name="weight" type="number" step="0.01" min="0.1" placeholder="18.75" required></label>
  <label>24K 1g 시세 (원) — 비우면 저장값 <input name="spot" type="number" step="100"></label>
  <button>분석</button>
</form>
<div class="note" style="margin-top:8px">금은 시세×순도×중량으로 즉시 계산된다 — 은행이 이미 담보로 받는 이유.
명품은 모델·상태별 실거래 원장이 있어야 같은 답을 낼 수 있다 — 드르륵이 만드는 데이터가 그것.</div></div>"""


def kv(rows):
    return ('<dl class="kv">'
            + "".join(f"<dt>{k}</dt><dd class='{cls}'>{v}</dd>"
                      for k, v, cls in rows) + "</dl>")


def layer_txt(l):
    if l["median_krw"] is None:
        return "—"
    s = f"{w(l['median_krw'])} <span class='note'>(n={l['n']}, {l['latest'] or '—'})</span>"
    if l["stale"]:
        s += " <span class='warn'>stale</span>"
    return s


def render_report(r):
    if "error" in r:
        return f'<div class="card"><h2 class="warn">분석 불가</h2><p>{esc(r["error"])}</p></div>'
    a, i = r["asset"], r["identity"]
    cards = []
    cards.append(
        f'<div class="card"><h2>ASSET</h2><div class="big">{esc(a["brand"])} '
        f'{esc(a["model"])} <span class="note">({a.get("reference_no") or "-"}) · '
        f'등급 {a["grade"]} · 기준일 {r["as_of"]} · 최근 {r["window_days"]}일</span></div></div>')
    ident = ("<span class='good'>HUMAN VERIFIED</span>" if i["human_verified"]
             else f"<span class='warn'>{esc(i['identity_status'])}</span>")
    ai = (f"AI top-1: {esc(i['ai_top_candidate'])} ({i['ai_confidence']})"
          if i["ai_top_candidate"] else "AI 예측 없음")
    au = r["authenticity"]
    cards.append(f'<div class="card"><h2>IDENTITY · AUTHENTICITY</h2>'
                 + kv([("식별", ident, ""), ("AI 후보", ai, ""),
                       ("Correction", f"{i['correction_count']}건", ""),
                       ("진위", esc(au["status"]), ""),
                       ("진위 근거", f"{au.get('evidence_count')}건", "")])
                 + "</div>")
    m, d = r["market"], r["dealer_market"]
    cards.append(f'<div class="card"><h2>MARKET · DEALER MARKET</h2>'
                 + kv([("소매 호가 시세", layer_txt(m["retail_asking"]), ""),
                       ("외부 sold", layer_txt(m["observed_sold"]), ""),
                       ("딜러 indicative", layer_txt(d["dealer_indicative"]), ""),
                       ("딜러 FIRM", layer_txt(d["dealer_firm"]), "big"),
                       ("바이어", f"{d['unique_bidders']}명 (검증 {d['unique_qualified_bidders']}명)"
                        f" · top1 점유 {p(d['top1_buyer_share_pct'])}", ""),
                       ("호가 분산", p(d["bid_dispersion_pct"]), ""),
                       ("FIRM 취소·정산실패", f"{d['firm_bid_cancellation_count']}건 · "
                        f"{d['settlement_failure_count']}건", "")])
                 + "</div>")
    lq = r["liquidity"]
    liq_rows = [("성사 전환율", p(lq["bid_to_sale_conversion_pct"]), ""),
                ("처분 소요 중위", f"{lq['days_to_sale_median'] or '—'}일", ""),
                ("유찰", f"{lq['failed_listing_count']}건", "")]
    for label, key in (("7일 청산 범위", "expected_7d"), ("30일 청산 범위", "expected_30d")):
        e = r["liquidation"][key]
        if e["range_mid_krw"] is not None:
            txt = (f"{w(e['range_low_krw'])} ~ {w(e['range_high_krw'])} "
                   f"<span class='note'>(mid {w(e['range_mid_krw'])} · {e['confidence']}"
                   + (f" · {esc(','.join(e['reasons']))}" if e["reasons"] else "") + ")</span>")
        else:
            txt = (f"<span class='warn'>INSUFFICIENT DATA</span> "
                   f"<span class='note'>{esc(', '.join(e['reasons']))}</span>")
        liq_rows.append((label, txt, ""))
    cards.append(f'<div class="card"><h2>LIQUIDITY · LIQUIDATION</h2>'
                 + kv(liq_rows) + "</div>")
    ltv = r["ltv"]
    if ltv["status"] == "AVAILABLE":
        ltv_rows = [("권장 LTV", p(ltv["recommended_pct"]), "big good")]
    else:
        ltv_rows = [("권장 LTV", "<span class='warn'>NOT AVAILABLE</span>", "big"),
                    ("사유", esc(", ".join(ltv["reasons"])), "")]
        if ltv["indicative_reference_pct"]:
            ltv_rows.append(("indicative 참고치",
                             f"{p(ltv['indicative_reference_pct'])} "
                             "<span class='note'>— FIRM·정산 실측 아님, 권장값 아님</span>", ""))
    cards.append(f'<div class="card"><h2>FINANCIAL LTV</h2>' + kv(ltv_rows) + "</div>")
    o = r["outcome"]["recent_transactions"]
    if o:
        tr = "".join(
            f"<tr><td>{esc((t['settled_at'] or '')[:10])}</td><td>{w(t['gross_krw'])}</td>"
            f"<td>{w(t['costs_krw'])}{' (미상)' if t['costs_unknown'] else ''}</td>"
            f"<td>{w(t['net_proceeds_krw'])}</td><td>{t['days_to_sale'] or '—'}</td></tr>"
            for t in o)
        cards.append('<div class="card"><h2>OUTCOME — 실측</h2><table><thead><tr>'
                     '<th>정산일</th><th>성사가</th><th>비용</th><th>Net Proceeds</th>'
                     f'<th>소요일</th></tr></thead><tbody>{tr}</tbody></table></div>')
    q = r["data_quality"]
    cards.append(f'<div class="card"><h2>DATA QUALITY</h2>'
                 + kv([("Evidence grade", q["evidence_grade"], "big"),
                       ("표본", esc(json.dumps(q["sample"], ensure_ascii=False)), ""),
                       ("환경 구성", esc(json.dumps(q["environment_mix"],
                                                 ensure_ascii=False)), ""),
                       ("누락", esc(", ".join(q["missing_fields"]) or "없음"), "")])
                 + f'<div class="note" style="margin-top:8px">rule {r["rule_version"]}</div></div>')
    return "".join(cards)


def render_gold(r):
    if "error" in r:
        return f'<div class="card"><h2 class="warn">분석 불가</h2><p>{esc(r["error"])}</p></div>'
    a = r["asset"]
    return (f'<div class="card"><h2>GOLD — 표준화 자산</h2>'
            f'<div class="big">금 {a["purity"]} {a["weight_g"]}g '
            f'<span class="note">(24K {r["spot_krw_per_g_24k"]:,}원/g, {esc(r["spot_as_of"])})</span></div>'
            + kv([("시장가치 (MV)", w(r["market_value_krw"]), "big"),
                  ("청산가치 (LV)", w(r["liquidation_value_krw"]), "big"),
                  ("매입 스프레드", p(r["wholesale_discount_pct"]), ""),
                  ("관행 LTV 참고치", f"{p(r['conventional_ltv_reference_pct'])} "
                   "<span class='note'>— 권장값 아님</span>", "")])
            + f'<div class="note" style="margin-top:8px">※ {esc(r["note"])}</div></div>')


class Handler(BaseHTTPRequestHandler):
    env = "REAL"

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/":
            body = FORMS
        elif url.path.startswith("/console"):
            conn = coredb.connect(self.env)
            body = console.page(conn, url.path, q, self.env)
            conn.close()
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
        elif url.path in ("/asset", "/api/asset"):
            conn = coredb.connect(self.env)
            cid, cands = baseline.find_asset(conn, q.get("q", ""))
            if cid:
                r = asset_report.build(conn, cid, grade=q.get("grade", "A"),
                                       asset_id=q.get("asset_id"))
                if url.path == "/api/asset":
                    conn.close()
                    return self._json(r)
                body = render_report(r)
            elif cands:
                if url.path == "/api/asset":
                    conn.close()
                    return self._json({"error": "ambiguous", "candidates": cands})
                links = "".join(
                    f'<a href="/asset?q={urllib.parse.quote(c)}&grade={q.get("grade","A")}">{esc(c)}</a>'
                    for c in cands)
                body = (f'<div class="card"><h2>검색 결과가 여러 개입니다</h2>'
                        f'<div class="candidates">{links}</div></div>')
            else:
                if url.path == "/api/asset":
                    conn.close()
                    return self._json({"error": "not found"})
                body = (f'<div class="card"><h2 class="warn">검색 결과 없음</h2>'
                        f'<p>"{esc(q.get("q", ""))}" — 카탈로그에 없습니다.</p></div>')
            conn.close()
        elif url.path == "/gold":
            conn = (coredb.connect("REAL")
                    if os.path.exists(coredb.DB_FILES["REAL"]) else None)
            spot = float(q["spot"]) if q.get("spot") else None
            body = render_gold(az.analyze_gold(q.get("purity", "24K"),
                                               float(q.get("weight", 0) or 0),
                                               spot=spot, conn=conn))
            if conn:
                conn.close()
        else:
            self.send_response(404)
            self.end_headers()
            return
        page = (f"<!doctype html><html lang='ko'><head>{STYLE}"
                f"<title>드르륵 자산 분석</title></head><body>{header(self.env)}{body}"
                f"<div class='note'>CLI: analyze.py · 실데이터 입력: intake/ingest.py · "
                f"API: /api/asset?q=서브마리너&grade=A</div></div></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(page))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/console/"):
            self.send_response(404)
            self.end_headers()
            return
        form = self._parse_post()
        conn = coredb.connect(self.env)
        env = "SIMULATION" if self.env == "SIMULATION" else "REAL"
        result = console.action(conn, url.path, form, env)
        conn.close()
        if result is None:
            self.send_response(404)
            self.end_headers()
            return
        kind, payload = result
        if kind == "redirect":
            self.send_response(303)
            self.send_header("Location", payload)
            self.end_headers()
            return
        page = (f"<!doctype html><html lang='ko'><head>{STYLE}"
                f"<title>드르륵 자산 분석</title></head><body>{header(self.env)}"
                f"{payload}</div></body></html>").encode()
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(page))
        self.end_headers()
        self.wfile.write(page)

    def _parse_post(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        form = {}
        if ctype.startswith("multipart/form-data"):
            import email
            msg = email.message_from_bytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
            for part in msg.get_payload():
                name = part.get_param("name", header="content-disposition")
                filename = part.get_param("filename", header="content-disposition")
                data = part.get_payload(decode=True) or b""
                if filename is not None:
                    form[f"_file_{name}"] = {"filename": filename, "data": data}
                elif name:
                    form[name] = data.decode("utf-8", "replace").strip()
        else:
            for k, v in urllib.parse.parse_qs(body.decode("utf-8", "replace")).items():
                form[k] = v[0]
        return form

    def _json(self, payload):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--env", default="REAL", help="REAL(기본) 또는 SIM")
    args = ap.parse_args()
    env = "SIMULATION" if args.env.upper().startswith("SIM") else "REAL"
    if not os.path.exists(coredb.DB_FILES[env]):
        hint = ("python3 sim/run.py" if env == "SIMULATION"
                else "python3 intake/ingest.py events <csv>")
        raise SystemExit(f"{env} 원장이 없습니다 — 먼저 `{hint}` 실행")
    Handler.env = env
    print(f"드르륵 자산 분석 프로그램 [{env}]: http://localhost:{args.port}  (중지: Ctrl+C)")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
