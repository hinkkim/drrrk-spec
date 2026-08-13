"""AI 보조 — 후보 추천·필드 추출·anomaly 탐지 결과를 ai_predictions에 기록한다.

AI는 Source of Truth가 아니다 (§4):
  · AI 산출물은 human_verifications와 항상 별도 행으로 저장된다
  · 가격 필드는 스키마와 이 모듈 양쪽에서 거부된다
  · 최종 확정은 intake/verify.py (Human Expert)만 할 수 있다

실제 Gemini 연동(T16)은 이 모듈의 record_prediction을 그대로 사용한다.
"""
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit

PREDICTION_TYPES = ("identity", "condition", "authenticity_anomaly",
                    "field_extraction")
# 가격으로 해석될 수 있는 payload 키 조각 — 발견 시 기록 거부
BANNED_KEY_PARTS = ("price", "krw", "value", "amount", "ltv", "estimate_low",
                    "estimate_high")


def ensure_model_version(conn, name, kind, version, params_hash=None):
    mvid = f"{name}@{version}"
    conn.execute("insert or ignore into model_versions (model_version_id, name,"
                 " kind, version, params_hash) values (?,?,?,?,?)",
                 (mvid, name, kind, version, params_hash))
    return mvid


def record_prediction(conn, asset_id, prediction_type, payload, confidence,
                      model_name, model_version, env="REAL",
                      observed_at=None, actor=None):
    """AI 예측 1건 기록. payload는 dict — 가격성 키가 있으면 ValueError."""
    if prediction_type not in PREDICTION_TYPES:
        raise ValueError(f"prediction_type must be one of {PREDICTION_TYPES}")
    _reject_price_keys(payload)
    pid = str(uuid.uuid4())
    mvid = ensure_model_version(conn, model_name, "AI_MODEL", model_version)
    observed_at = observed_at or datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "insert into ai_predictions (prediction_id, asset_id, prediction_type,"
        " payload, confidence, model_version_id, data_environment, observed_at)"
        " values (?,?,?,?,?,?,?,?)",
        (pid, asset_id, prediction_type,
         json.dumps(payload, ensure_ascii=False), confidence, mvid, env,
         observed_at))
    # identity 예측이 들어오면 자산 상태를 AI_CANDIDATE로 (검증 전 단계)
    if prediction_type == "identity":
        row = conn.execute("select identity_status from assets where asset_id=?",
                           (asset_id,)).fetchone()
        if row and row[0] == "UNIDENTIFIED":
            conn.execute("update assets set identity_status='AI_CANDIDATE'"
                         " where asset_id=?", (asset_id,))
            audit.log(conn, actor or f"ai:{model_name}", "status_change",
                      "assets", asset_id,
                      before={"identity_status": "UNIDENTIFIED"},
                      after={"identity_status": "AI_CANDIDATE"},
                      reason=f"ai identity prediction {pid}")
    audit.log(conn, actor or f"ai:{model_name}", "insert", "ai_predictions", pid,
              after={"prediction_type": prediction_type, "confidence": confidence})
    conn.commit()
    return pid


def top_candidates(conn, asset_id):
    """가장 최근 identity 예측의 후보 목록 (검증 콘솔용)."""
    row = conn.execute(
        "select prediction_id, payload, confidence from ai_predictions"
        " where asset_id=? and prediction_type='identity'"
        " order by observed_at desc, created_at desc limit 1", (asset_id,)).fetchone()
    if not row:
        return None
    pid, payload, conf = row
    return {"prediction_id": pid, "confidence": conf,
            "candidates": json.loads(payload).get("candidates", [])}


def _reject_price_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(part in lk for part in BANNED_KEY_PARTS) and lk != "confidence":
                raise ValueError(
                    f"AI payload에 가격성 키 금지: {path}.{k} — 가격은 원장에서만 산출된다")
            _reject_price_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_price_keys(v, f"{path}[{i}]")


# ── Gemini 폐쇄형 분류 프롬프트 (T16 실연동 시 사용 — 가격 필드 없음) ──────
GEMINI_CLOSED_SET_PROMPT = """당신은 명품 자산 식별 전문가입니다. 가격은 절대 추정하지 마십시오.

첨부된 사진들을 보고 아래 후보 카탈로그 **안에서만** 가장 가능성 높은 모델 top-3를 고르세요.
후보에 확실히 없다면 candidates를 빈 배열로 반환하세요.

[후보 카탈로그]
{catalog_subset}

다음 JSON 스키마로만 응답:
{{
  "brand": "...",
  "candidates": [
    {{"canonical_asset_id": "...", "confidence": 0.0~1.0,
      "evidence": "판별 근거 (다이얼 각인, 베젤, 금구, 스티치 등)"}}
  ],
  "grade_estimate": "S|A|B|C",
  "grade_evidence": "...",
  "authenticity_flags": ["의심 포인트가 있으면 서술"],
  "photo_requests": ["판별에 더 필요한 부위 사진이 있으면 요청"]
}}"""
