"""전문가 검증 — 최종 Asset ID·상태·진위는 Human Expert만 확정한다 (§5).

저장되는 것:
  human_verifications      검증값·검증자·소요시간·사용 근거
  verification_corrections AI 오류를 고친 경우 사유 코드 (최고 가치 학습 데이터)
  assets                   identity_status / canonical_asset_id / grade 갱신 (audit 필수)
  condition_assessments    상태 확정 시 병행 기록
  authentication_evidence  진위 근거 (시리얼은 해시로 저장)
"""
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit
from core.evidence import CORRECTION_REASONS


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def start_verification():
    """검증 시작 시각 — complete_verification의 started_at으로 전달 (KPI: 소요시간)."""
    return now_iso()


def complete_verification(conn, asset_id, field, verified_value, verified_by,
                          started_at=None, ai_prediction_id=None,
                          evidence_used="", correction=None, env="REAL",
                          completed_at=None):
    """검증 1건 확정. field: identity | condition | authenticity.

    correction: AI 예측을 고친 경우 {"reason": CORRECTION_REASONS 중 하나,
                "before": AI값, "note": 설명}. AI가 맞았다면 None.
    """
    if field not in ("identity", "condition", "authenticity"):
        raise ValueError(f"field must be identity/condition/authenticity, got {field}")
    vid = str(uuid.uuid4())
    completed_at = completed_at or now_iso()
    conn.execute(
        "insert into human_verifications (verification_id, asset_id, field,"
        " ai_prediction_id, verified_value, verified_by, started_at, completed_at,"
        " evidence_used, data_environment) values (?,?,?,?,?,?,?,?,?,?)",
        (vid, asset_id, field, ai_prediction_id, verified_value, verified_by,
         started_at, completed_at, evidence_used, env))
    audit.log(conn, verified_by, "verify", "human_verifications", vid,
              after={"field": field, "verified_value": verified_value,
                     "asset_id": asset_id})

    if correction:
        reason = correction["reason"]
        if reason not in CORRECTION_REASONS:
            raise ValueError(f"correction_reason must be one of {CORRECTION_REASONS}")
        cid = str(uuid.uuid4())
        conn.execute(
            "insert into verification_corrections (correction_id, verification_id,"
            " correction_reason, before_value, after_value, note)"
            " values (?,?,?,?,?,?)",
            (cid, vid, reason, correction.get("before"), verified_value,
             correction.get("note")))
        audit.log(conn, verified_by, "correction", "verification_corrections", cid,
                  before={"value": correction.get("before")},
                  after={"value": verified_value}, reason=reason)

    if field == "identity":
        _apply_identity(conn, asset_id, verified_value, verified_by)
    elif field == "condition":
        _apply_condition(conn, asset_id, verified_value, verified_by, env,
                         completed_at)
    conn.commit()
    return vid


def _apply_identity(conn, asset_id, canonical_asset_id, verified_by):
    if not conn.execute("select 1 from asset_master where canonical_asset_id=?"
                        " and status='active'", (canonical_asset_id,)).fetchone():
        raise ValueError(f"asset_master에 없는 canonical ID: {canonical_asset_id}")
    before = conn.execute("select canonical_asset_id, identity_status from assets"
                          " where asset_id=?", (asset_id,)).fetchone()
    if before is None:
        raise ValueError(f"미등록 asset_id: {asset_id}")
    conn.execute("update assets set canonical_asset_id=?, identity_status="
                 "'HUMAN_VERIFIED' where asset_id=?", (canonical_asset_id, asset_id))
    audit.log(conn, verified_by, "identity_confirm", "assets", asset_id,
              before={"canonical_asset_id": before[0], "identity_status": before[1]},
              after={"canonical_asset_id": canonical_asset_id,
                     "identity_status": "HUMAN_VERIFIED"})


def _apply_condition(conn, asset_id, grade, verified_by, env, observed_at):
    if grade not in ("S", "A", "B", "C"):
        raise ValueError(f"grade must be S/A/B/C, got {grade}")
    before = conn.execute("select grade from assets where asset_id=?",
                          (asset_id,)).fetchone()
    conn.execute("update assets set grade=? where asset_id=?", (grade, asset_id))
    conn.execute(
        "insert into condition_assessments (assessment_id, asset_id, grade,"
        " assessed_by, source_type, data_environment, observed_at)"
        " values (?,?,?,?,'EXPERT_ESTIMATE',?,?)",
        (str(uuid.uuid4()), asset_id, grade, verified_by, env, observed_at))
    audit.log(conn, verified_by, "condition_confirm", "assets", asset_id,
              before={"grade": before[0] if before else None},
              after={"grade": grade})


def add_authentication_evidence(conn, asset_id, evidence_type, result,
                                source, serial=None, detail=None, env="REAL",
                                observed_at=None):
    """진위 근거 기록. serial 원문은 저장하지 않고 sha256 해시만 남긴다 (§16-H)."""
    eid = str(uuid.uuid4())
    serial_hash = (hashlib.sha256(serial.encode()).hexdigest() if serial else None)
    observed_at = observed_at or now_iso()
    dup = None
    if serial_hash:  # 동일 시리얼 중복 등록 탐지 (§16-B)
        dup = conn.execute(
            "select asset_id from authentication_evidence where serial_hash=?"
            " and asset_id != ? limit 1", (serial_hash, asset_id)).fetchone()
    conn.execute(
        "insert into authentication_evidence (evidence_id, asset_id, evidence_type,"
        " result, serial_hash, detail, source, data_environment, observed_at)"
        " values (?,?,?,?,?,?,?,?,?)",
        (eid, asset_id, evidence_type, result, serial_hash,
         json.dumps(detail or {}, ensure_ascii=False), source, env, observed_at))
    audit.log(conn, source, "insert", "authentication_evidence", eid,
              after={"evidence_type": evidence_type, "result": result,
                     "duplicate_serial_of": dup[0] if dup else None})
    conn.commit()
    return eid, (dup[0] if dup else None)


def authenticity_status(conn, asset_id):
    """진위 상태 요약: fail 있으면 FAILED, pass만 있으면 VERIFIED, 없으면 UNRESOLVED."""
    rows = [r[0] for r in conn.execute(
        "select result from authentication_evidence where asset_id=?", (asset_id,))]
    if any(r == "fail" for r in rows):
        return "FAILED"
    if rows and all(r == "pass" for r in rows):
        return "VERIFIED"
    return "UNRESOLVED"
