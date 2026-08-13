"""T2 환경 분리 테스트 — 시뮬레이션 데이터가 실DB에 물리적으로 못 들어가는지."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db


class EnvSeparation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _conn(self, env, name):
        return db.connect(env, path=os.path.join(self.tmp.name, name),
                          seed_catalog=False)

    def _asset(self, conn, env):
        conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                     " model) values ('WATCH-X-Y-1','WATCH','X','Y')")
        conn.execute("insert into assets (asset_id, canonical_asset_id,"
                     " data_environment, source) values (?,?,?,?)",
                     (f"a-{env}", "WATCH-X-Y-1", env, "test"))

    def test_real_db_rejects_simulation_rows(self):
        conn = self._conn("REAL", "real.db")
        with self.assertRaises(sqlite3.IntegrityError):
            self._asset(conn, "SIMULATION")

    def test_real_db_accepts_real_and_backfill(self):
        conn = self._conn("REAL", "real.db")
        self._asset(conn, "REAL")
        conn.execute("insert into assets (asset_id, canonical_asset_id,"
                     " data_environment, source) values ('a2','WATCH-X-Y-1',"
                     "'BACKFILL','backfill:p1')")

    def test_sim_db_rejects_real_rows(self):
        conn = self._conn("SIMULATION", "sim.db")
        with self.assertRaises(sqlite3.IntegrityError):
            self._asset(conn, "REAL")

    def test_env_mismatch_on_reopen(self):
        path = os.path.join(self.tmp.name, "real.db")
        db.connect("REAL", path=path, seed_catalog=False).close()
        with self.assertRaises(RuntimeError):
            db.connect("SIMULATION", path=path)

    def test_environment_recorded(self):
        conn = self._conn("REAL", "real.db")
        self.assertEqual(db.environment(conn), "REAL")

    def test_guard_covers_every_env_table(self):
        conn = self._conn("REAL", "real.db")
        tables = [t for (t,) in conn.execute(
            "select name from sqlite_master where type='table'")
            if "data_environment" in
            [r[1] for r in conn.execute(f"pragma table_info({t})")]]
        triggers = [t for (t,) in conn.execute(
            "select name from sqlite_master where type='trigger'"
            " and name like 'trg_env_%'")]
        for t in tables:
            self.assertIn(f"trg_env_{t}", triggers,
                          f"{t} 테이블에 환경 가드 trigger가 없습니다")


if __name__ == "__main__":
    unittest.main()
