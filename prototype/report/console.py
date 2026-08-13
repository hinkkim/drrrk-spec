"""전문가 검증 콘솔 (T8) — Human-in-the-Loop의 작업대 (§5).

흐름: 자산 등록(+사진) → AI top-3 후보 확인 → 원클릭 확정 또는 correction
(사유 13종) → 상태 등급 확정 → 진위 evidence 첨부. 검증 소요시간은 페이지
렌더 시각(hidden started_at)부터 제출까지 자동 기록된다 — KPI의 원천.

app.py가 /console* 경로를 이 모듈에 위임한다. 표준 라이브러리만 사용.
"""
import hashlib
import html
import json
import os
import sys
import urllib.parse
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.evidence import CORRECTION_REASONS
from engine import baseline
from intake import ai_assist, ingest, verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(ROOT, "uploads")

REASON_KO = {
    "reference_mismatch": "레퍼런스 불일치", "serial_mismatch": "시리얼 불일치",
    "material": "소재", "size": "사이즈", "year": "연식", "hardware": "금구",
    "stitching": "스티치", "logo": "로고", "aftermarket_part": "비순정 부품",
    "repair": "수리 흔적", "condition": "상태", "insufficient_image": "사진 부족",
    "authenticity_issue": "진위 문제",
}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ── GET ──────────────────────────────────────────────────────────────────
def page(conn, path, q, env):
    """콘솔 GET 라우팅. 해당 없으면 None."""
    if path == "/console":
        return _index(conn, env)
    if path == "/console/asset":
        return _asset_page(conn, q.get("id", ""), env, msg=q.get("msg"))
    return None


def _index(conn, env):
    pending = conn.execute(
        "select asset_id, canonical_asset_id, identity_status, grade, source,"
        " created_at from assets where identity_status != 'HUMAN_VERIFIED'"
        " order by created_at desc limit 30").fetchall()
    done = conn.execute(
        "select count(*) from assets where identity_status='HUMAN_VERIFIED'"
    ).fetchone()[0]
    rows = "".join(
        f'<tr><td><a href="/console/asset?id={aid}">{aid[:8]}…</a></td>'
        f'<td>{esc(cid or "미확정")}</td><td>{esc(st)}</td><td>{esc(g or "—")}</td>'
        f'<td>{esc(src)}</td><td>{esc(at[:16])}</td></tr>'
        for aid, cid, st, g, src, at in pending) or \
        '<tr><td colspan="6" style="text-align:left">검증 대기 자산 없음</td></tr>'
    return f"""
<div class="card"><h2>신규 자산 등록</h2>
<form class="row" action="/console/register" method="post" enctype="multipart/form-data">
  <label>접수 경로 <input name="source" value="drrrk" required></label>
  <label>등록자 <input name="registered_by" placeholder="staff:이름"></label>
  <label>리스팅 ID <input name="listing_id" placeholder="선택"></label>
  <label>사진 <input name="photo" type="file" accept="image/*"></label>
  <button>등록 → 검증으로</button>
</form>
<div class="note" style="margin-top:8px">등록 시점에는 canonical ID가 없다(UNIDENTIFIED).
AI 후보와 전문가 확정을 거쳐야 원장 이벤트가 이 자산에 귀속된다.</div></div>
<div class="card"><h2>검증 대기 ({len(pending)}) <span style="color:var(--muted);font-weight:400">
· 검증 완료 {done}건</span></h2>
<table><thead><tr><th>자산</th><th>canonical</th><th>상태</th><th>등급</th>
<th>접수</th><th>등록시각</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def _asset_page(conn, aid, env, msg=None):
    row = conn.execute(
        "select canonical_asset_id, identity_status, grade, source, created_at"
        " from assets where asset_id=?", (aid,)).fetchone()
    if not row:
        return '<div class="card"><h2 class="warn">없는 자산입니다</h2></div>'
    cid, status, grade, source, created = row
    images = conn.execute("select file_path from asset_images where asset_id=?",
                          (aid,)).fetchall()
    ai = ai_assist.top_candidates(conn, aid)
    auth_rows = conn.execute(
        "select evidence_type, result, observed_at from authentication_evidence"
        " where asset_id=? order by observed_at desc", (aid,)).fetchall()

    h = []
    if msg:
        h.append(f'<div class="card"><b>{esc(msg)}</b></div>')
    h.append(
        f'<div class="card"><h2>자산 {esc(aid[:8])}… '
        f'<span style="color:var(--muted);font-weight:400">{esc(source)} · {esc(created[:16])}</span></h2>'
        + _kv([("canonical", esc(cid or "미확정")),
               ("식별 상태", _status_badge(status)),
               ("상태 등급", esc(grade or "미확정")),
               ("사진", f"{len(images)}장 " + " ".join(
                   f'<span class="badge">{esc(os.path.basename(p))}</span>'
                   for (p,) in images)),
               ("진위 근거", verify.authenticity_status(conn, aid)
                + f" ({len(auth_rows)}건)")])
        + "</div>")

    # ── 식별·상태 검증 폼 (검증 타이머: started_at hidden) ──
    if ai and ai["candidates"]:
        cands = "".join(
            f'<label style="flex-direction:row;align-items:center;gap:8px">'
            f'<input type="radio" name="choice" value="{esc(c["canonical_asset_id"])}"'
            f'{" checked" if i == 0 else ""}>'
            f'<span>{esc(c["canonical_asset_id"])} '
            f'<span style="color:var(--muted)">({c.get("confidence")}'
            f' · {esc(c.get("evidence", ""))})</span></span></label>'
            for i, c in enumerate(ai["candidates"]))
        ai_block = (f'<div class="note">AI top-{len(ai["candidates"])} 후보'
                    f' (전체 confidence {ai["confidence"]})</div>{cands}')
        ai_top1 = ai["candidates"][0]["canonical_asset_id"]
        ai_pid = ai["prediction_id"]
    else:
        ai_block = '<div class="note">AI 예측 없음 — 카탈로그 검색으로 직접 확정</div>'
        ai_top1, ai_pid = "", ""
    reasons = "".join(f'<option value="{r}">{REASON_KO[r]} ({r})</option>'
                      for r in CORRECTION_REASONS)
    h.append(f"""
<div class="card"><h2>① 식별·상태 확정 <span style="color:var(--muted);font-weight:400">— 최종 판단은 전문가</span></h2>
<form action="/console/verify" method="post" style="display:flex;flex-direction:column;gap:10px">
  <input type="hidden" name="asset_id" value="{esc(aid)}">
  <input type="hidden" name="started_at" value="{now_iso()}">
  <input type="hidden" name="ai_top1" value="{esc(ai_top1)}">
  <input type="hidden" name="ai_prediction_id" value="{esc(ai_pid)}">
  {ai_block}
  <div class="row">
    <label style="flex:1">또는 카탈로그 검색 (모델명·별칭·canonical ID)
      <input name="search" placeholder="후보에 정답이 없으면 여기 입력" style="min-width:260px"></label>
  </div>
  <div class="row">
    <label>AI가 틀렸다면 — correction 사유
      <select name="correction_reason"><option value="">(AI가 맞음 / AI 없음)</option>{reasons}</select></label>
    <label>correction 메모 <input name="correction_note" style="min-width:220px"></label>
  </div>
  <div class="row">
    <label>상태 등급 확정 <select name="grade"><option value="">(보류)</option>
      <option>S</option><option>A</option><option>B</option><option>C</option></select></label>
    <label>검증자 <input name="verified_by" placeholder="expert:이름" required></label>
    <label>사용 근거 <input name="evidence_used" placeholder="각인 대조, 보증서…" style="min-width:200px"></label>
    <button>확정</button>
  </div>
</form></div>""")

    # ── 진위 evidence 폼 ──
    auth_hist = "".join(f'<tr><td>{esc(t)}</td><td>{esc(r)}</td><td>{esc(at[:16])}</td></tr>'
                        for t, r, at in auth_rows)
    h.append(f"""
<div class="card"><h2>② 진위 Evidence</h2>
<form class="row" action="/console/auth" method="post">
  <input type="hidden" name="asset_id" value="{esc(aid)}">
  <label>유형 <select name="evidence_type"><option>serial</option><option>hologram</option>
    <option>receipt</option><option>external_cert</option><option>expert_opinion</option></select></label>
  <label>결과 <select name="result"><option>pass</option><option>fail</option>
    <option>inconclusive</option></select></label>
  <label>시리얼 (해시 저장) <input name="serial" placeholder="원문 미저장"></label>
  <label>확인자 <input name="auth_source" placeholder="expert:이름" required></label>
  <button>기록</button>
</form>
{f'<table style="margin-top:10px"><thead><tr><th>유형</th><th>결과</th><th>일시</th></tr></thead><tbody>{auth_hist}</tbody></table>' if auth_hist else ''}
</div>""")
    h.append(market_section(conn, aid, cid, env))
    return "".join(h)


def _status_badge(status):
    color = {"HUMAN_VERIFIED": "var(--good)", "DISPUTED": "var(--warn)"}.get(
        status, "var(--warn)")
    return f'<span style="color:{color};font-weight:600">{esc(status)}</span>'


def _kv(rows):
    return ('<dl class="kv">'
            + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>")


# ── POST ─────────────────────────────────────────────────────────────────
def action(conn, path, form, env):
    """콘솔 POST 라우팅 → ('redirect', location) 또는 ('error', html)."""
    try:
        if path == "/console/register":
            return _do_register(conn, form, env)
        if path == "/console/verify":
            return _do_verify(conn, form, env)
        if path == "/console/auth":
            return _do_auth(conn, form, env)
        handled = market_action(conn, path, form, env)
        if handled:
            return handled
    except (ValueError, KeyError) as e:
        return ("error", f'<div class="card"><h2 class="warn">입력 오류</h2>'
                         f'<p>{esc(e)}</p><p><a href="javascript:history.back()">돌아가기</a></p></div>')
    return None


def _do_register(conn, form, env):
    aid = ingest.register_asset(
        conn, source=form.get("source") or "drrrk", env=env,
        registered_by=form.get("registered_by") or None,
        listing_id=form.get("listing_id") or None,
        actor=form.get("registered_by") or "console")
    photo = form.get("_file_photo")
    if photo and photo["data"]:
        os.makedirs(UPLOADS, exist_ok=True)
        digest = hashlib.sha256(photo["data"]).hexdigest()
        name = f"{aid[:8]}_{os.path.basename(photo['filename']) or 'photo'}"
        path = os.path.join(UPLOADS, name)
        with open(path, "wb") as f:
            f.write(photo["data"])
        ingest.attach_image(conn, aid, os.path.join("uploads", name),
                            sha256=digest, actor="console")
    return ("redirect", f"/console/asset?id={aid}&msg="
            + urllib.parse.quote("등록 완료 — AI 후보 기록 후 검증하세요"))


def _do_verify(conn, form, env):
    aid = form["asset_id"]
    choice = (form.get("search") or "").strip() or form.get("choice") or ""
    if not choice:
        raise ValueError("후보 선택 또는 카탈로그 검색 중 하나는 필요합니다")
    cid, cands = baseline.find_asset(conn, choice)
    if not cid:
        raise ValueError("카탈로그에서 찾지 못했습니다: " + choice
                         + (f" (후보: {', '.join(cands[:5])})" if cands else ""))
    ai_top1 = form.get("ai_top1") or ""
    reason = form.get("correction_reason") or ""
    correction = None
    if ai_top1 and cid != ai_top1:
        if not reason:
            raise ValueError("AI top-1과 다른 모델로 확정합니다 — correction 사유를 선택하세요")
        correction = {"reason": reason, "before": ai_top1,
                      "note": form.get("correction_note") or None}
    elif reason:  # 같은 모델인데 사유 선택 — 등급·기타 correction으로 기록
        correction = {"reason": reason, "before": ai_top1 or None,
                      "note": form.get("correction_note") or None}
    verify.complete_verification(
        conn, aid, "identity", cid, form["verified_by"],
        started_at=form.get("started_at"),
        ai_prediction_id=form.get("ai_prediction_id") or None,
        evidence_used=form.get("evidence_used") or "", correction=correction,
        env=env)
    if form.get("grade"):
        verify.complete_verification(conn, aid, "condition", form["grade"],
                                     form["verified_by"],
                                     started_at=form.get("started_at"), env=env)
    return ("redirect", f"/console/asset?id={aid}&msg="
            + urllib.parse.quote(f"검증 완료: {cid}"
                                 + (" (correction 기록됨)" if correction else "")))


def _do_auth(conn, form, env):
    aid = form["asset_id"]
    _, dup = verify.add_authentication_evidence(
        conn, aid, form["evidence_type"], form["result"],
        form["auth_source"], serial=form.get("serial") or None, env=env)
    msg = "진위 evidence 기록됨"
    if dup:
        msg += f" · ⚠ 동일 시리얼이 다른 자산({dup[:8]}…)에 이미 등록됨"
    return ("redirect", f"/console/asset?id={aid}&msg={urllib.parse.quote(msg)}")


# ── T9: 시장 Evidence (bid·거래·비용·외부 comp) — market_section/market_action ──
def market_section(conn, aid, cid, env):
    return ""  # T9에서 구현


def market_action(conn, path, form, env):
    return None  # T9에서 구현
