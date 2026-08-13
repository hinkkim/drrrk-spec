"""환경별 DB 연결 — SIMULATION과 REAL 데이터는 물리적으로 다른 파일에 산다.

  connect('REAL')        → prototype/drrrk_real.db   (REAL + BACKFILL 허용)
  connect('SIMULATION')  → prototype/drrrk_sim.db    (SIMULATION만 허용)

각 DB에는 환경 가드 trigger가 걸려 있어, 다른 환경의 행은 INSERT 자체가 거부된다.
시뮬레이션 데이터가 실DB·실UI에 섞이는 것을 스키마 수준에서 차단한다 (§12).
"""
import csv
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_v1.sql")
CATALOG = os.path.join(ROOT, "catalog_seed.csv")

DB_FILES = {
    "REAL": os.path.join(ROOT, "drrrk_real.db"),
    "SIMULATION": os.path.join(ROOT, "drrrk_sim.db"),
}
# 환경별로 허용되는 data_environment 값
ALLOWED = {"REAL": ("REAL", "BACKFILL"), "SIMULATION": ("SIMULATION",)}


def connect(env="REAL", path=None, seed_catalog=True):
    """환경별 DB 연결. 없으면 schema_v1 적용 + 카탈로그 시드 + 가드 설치."""
    if env not in ALLOWED:
        raise ValueError(f"env must be one of {tuple(ALLOWED)}, got {env!r}")
    path = path or DB_FILES[env]
    existed = os.path.exists(path)
    conn = sqlite3.connect(path)
    conn.execute("pragma foreign_keys = on")
    if not existed:
        init_schema(conn, env, seed_catalog=seed_catalog)
    else:
        _check_env(conn, env, path)
    return conn


def init_schema(conn, env, seed_catalog=True):
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("insert or replace into db_meta values ('environment', ?)", (env,))
    install_env_guards(conn, env)
    if seed_catalog and os.path.exists(CATALOG):
        seed_catalog_from_csv(conn)
    conn.commit()


def seed_catalog_from_csv(conn, path=None):
    with open(path or CATALOG, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "insert or ignore into asset_master (canonical_asset_id, category,"
                " brand, model, reference_no, aliases) values (?,?,?,?,?,?)",
                (row["canonical_asset_id"], row["category"], row["brand"],
                 row["model"], row["reference_no"], row["aliases"]))
    conn.commit()


def install_env_guards(conn, env):
    """data_environment 컬럼을 가진 모든 테이블에 환경 가드 trigger 설치."""
    allowed = ALLOWED[env]
    cond = " and ".join(f"new.data_environment != '{v}'" for v in allowed)
    for (table,) in conn.execute(
            "select name from sqlite_master where type='table'").fetchall():
        cols = [r[1] for r in conn.execute(f"pragma table_info({table})")]
        if "data_environment" not in cols:
            continue
        msg = "this database only accepts data_environment: " + "/".join(allowed)
        conn.execute(
            f"create trigger if not exists trg_env_{table} before insert on {table} "
            f"when {cond} "
            f"begin select raise(ABORT, '{msg}'); end")


def environment(conn):
    row = conn.execute("select value from db_meta where key='environment'").fetchone()
    return row[0] if row else None


def _check_env(conn, env, path):
    stored = environment(conn)
    if stored and stored != env:
        raise RuntimeError(
            f"{path} 는 {stored} 환경 DB입니다 — connect(env={env!r})로 열 수 없습니다.")
