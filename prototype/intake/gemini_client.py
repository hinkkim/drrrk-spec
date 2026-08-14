#!/usr/bin/env python3
"""Gemini 폐쇄형 식별 실연동 (T16) — AI는 후보만 내고, 가격은 절대 내지 않는다.

  export GEMINI_API_KEY=...
  python3 intake/gemini_client.py <asset_id> photo1.jpg [photo2.jpg ...] [--brand Rolex]

흐름 (§4 목표 구조의 1단계):
  1) asset_master에서 후보 카탈로그 서브셋 구성 (brand 힌트가 있으면 좁힘)
  2) 폐쇄형 프롬프트(ai_assist.GEMINI_CLOSED_SET_PROMPT) + 사진으로 호출
     — 구조화 JSON 강제, 가격 필드는 스키마에 아예 없다
  3) 응답 검증: 카탈로그 밖 canonical ID는 폐기, 가격성 키는 이중 가드
     (ai_assist + 스키마 CHECK)가 거부
  4) ai_predictions에 기록 → 최종 확정은 전문가 검증 콘솔(/console)

표준 라이브러리만 사용 (urllib). 네트워크 계층은 주입 가능해서
API 키 없이도 전 로직이 테스트된다.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intake import ai_assist

API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent")
DEFAULT_MODEL = "gemini-2.0-flash"
CONFIRM_THRESHOLD = 0.75   # 미만이면 콘솔에서 후보 선택 필수 (자동 확정 없음)


def catalog_subset(conn, brand_hint=None):
    q = ("select canonical_asset_id, brand, model, reference_no, aliases"
         " from asset_master where status='active'")
    args = []
    if brand_hint:
        q += " and brand like ?"
        args.append(f"%{brand_hint}%")
    rows = conn.execute(q, args).fetchall()
    if not rows and brand_hint:          # 힌트가 안 맞으면 전체 카탈로그
        return catalog_subset(conn, None)
    return rows


def build_prompt(rows):
    lines = "\n".join(
        f"- {cid} | {brand} {model} ({ref or '-'})"
        + (f" | 별칭: {aliases}" if aliases else "")
        for cid, brand, model, ref, aliases in rows)
    return ai_assist.GEMINI_CLOSED_SET_PROMPT.format(catalog_subset=lines)


def _encode_image(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return {"inline_data": {"mime_type": mime,
                                "data": base64.b64encode(f.read()).decode()}}


def call_api(api_key, prompt, image_paths, model=DEFAULT_MODEL, timeout=60):
    """실제 Gemini REST 호출. 테스트에서는 이 함수를 주입으로 대체한다."""
    body = {
        "contents": [{"parts": [{"text": prompt}]
                      + [_encode_image(p) for p in image_paths]}],
        "generationConfig": {"temperature": 0,
                             "response_mime_type": "application/json"},
    }
    req = urllib.request.Request(
        API_URL.format(model=model),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": api_key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini API 오류 {e.code}: {e.read().decode()[:300]}")
    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])


def validate_response(raw, catalog_ids):
    """카탈로그 폐쇄성 강제 — 목록 밖 ID·범위 밖 confidence는 폐기."""
    cands = []
    for c in (raw.get("candidates") or [])[:3]:
        cid = c.get("canonical_asset_id")
        if cid not in catalog_ids:
            continue
        conf = c.get("confidence")
        conf = round(min(max(float(conf), 0.0), 1.0), 3) if conf is not None else None
        cands.append({"canonical_asset_id": cid, "confidence": conf,
                      "evidence": str(c.get("evidence") or "")[:300]})
    grade = raw.get("grade_estimate")
    return {
        "brand": str(raw.get("brand") or "")[:60],
        "candidates": cands,
        "grade_estimate": grade if grade in ("S", "A", "B", "C") else None,
        "grade_evidence": str(raw.get("grade_evidence") or "")[:300],
        "authenticity_flags": [str(f)[:200] for f in
                               (raw.get("authenticity_flags") or [])[:5]],
        "photo_requests": [str(p)[:200] for p in
                           (raw.get("photo_requests") or [])[:5]],
    }


def identify(conn, asset_id, image_paths, brand_hint=None,
             model=DEFAULT_MODEL, api_key=None, caller=call_api):
    """자산 1건 식별 → ai_predictions 기록. (payload, prediction_id) 반환."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if caller is call_api and not api_key:
        raise RuntimeError("GEMINI_API_KEY가 없습니다 — export GEMINI_API_KEY=... "
                           "후 재실행하세요.")
    row = conn.execute("select data_environment from assets where asset_id=?",
                       (asset_id,)).fetchone()
    if not row:
        raise ValueError(f"미등록 asset_id: {asset_id}")
    env = row[0]
    subset = catalog_subset(conn, brand_hint)
    raw = caller(api_key, build_prompt(subset), image_paths, model=model)
    payload = validate_response(raw, {r[0] for r in subset})
    top_conf = (payload["candidates"][0]["confidence"]
                if payload["candidates"] else 0.0)
    pid = ai_assist.record_prediction(
        conn, asset_id, "identity", payload, top_conf,
        model, "live", env=env, actor=f"ai:{model}")
    payload["needs_user_confirm"] = (top_conf or 0) < CONFIRM_THRESHOLD
    return payload, pid


def main():
    from core import db as coredb
    ap = argparse.ArgumentParser()
    ap.add_argument("asset_id")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--brand", help="브랜드 힌트 (카탈로그 서브셋 축소)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    conn = coredb.connect("REAL")
    payload, pid = identify(conn, args.asset_id, args.images,
                            brand_hint=args.brand, model=args.model)
    conn.close()
    print(f"\n■ Gemini 식별 후보 기록됨 (prediction {pid[:8]}…)")
    for i, c in enumerate(payload["candidates"], 1):
        print(f"  {i}. {c['canonical_asset_id']}  conf {c['confidence']}"
              f"  — {c['evidence']}")
    if not payload["candidates"]:
        print("  후보 없음 — 카탈로그에 없는 모델일 수 있음 (콘솔에서 직접 확정)")
    if payload["authenticity_flags"]:
        print(f"  ⚠ 진위 의심: {'; '.join(payload['authenticity_flags'])}")
    if payload["photo_requests"]:
        print(f"  📷 추가 사진 요청: {'; '.join(payload['photo_requests'])}")
    print("  → 최종 확정은 검증 콘솔에서: python3 app.py 후 /console/asset?id=" +
          args.asset_id)


if __name__ == "__main__":
    main()
