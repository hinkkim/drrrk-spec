"""audit_logs 기록기 — 상태를 바꾸는 모든 쓰기 경로가 경유한다.

audit_logs 자체는 append-only (schema_v1.sql trigger가 UPDATE/DELETE를 차단).
canonical_asset_id 변경·bid 상태 전이·검증 확정 등은 반드시 log()와 함께 수행한다.
"""
import json
import uuid


def log(conn, actor, action, table_name, record_id,
        before=None, after=None, reason=None):
    """감사 이벤트 1건 기록. before/after는 dict 또는 None."""
    audit_id = str(uuid.uuid4())
    conn.execute(
        "insert into audit_logs (audit_id, actor, action, table_name, record_id,"
        " before_json, after_json, reason) values (?,?,?,?,?,?,?,?)",
        (audit_id, actor, action, table_name, record_id,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         reason))
    return audit_id


def trail(conn, record_id=None, table_name=None, limit=100):
    """감사 이력 조회 — record_id 또는 table_name으로 필터."""
    q, args = "select actor, action, table_name, record_id, before_json, after_json, reason, created_at from audit_logs", []
    conds = []
    if record_id:
        conds.append("record_id=?")
        args.append(record_id)
    if table_name:
        conds.append("table_name=?")
        args.append(table_name)
    if conds:
        q += " where " + " and ".join(conds)
    q += " order by created_at limit ?"
    args.append(limit)
    cols = ("actor", "action", "table_name", "record_id",
            "before", "after", "reason", "at")
    return [dict(zip(cols, r)) for r in conn.execute(q, args)]
