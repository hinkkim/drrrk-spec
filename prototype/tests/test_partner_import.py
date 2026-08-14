"""T15 파트너 백필 임포터 테스트 — 매칭·BACKFILL 태깅·quality score·멱등."""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake.partner_import import import_ledger, TEMPLATE


def fresh():
    conn = sqlite3.connect(":memory:")
    coredb.init_schema(conn, "REAL", seed_catalog=True)  # 실 카탈로그 22종
    return conn


def write_csv(content):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                    encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


class PartnerImport(unittest.TestCase):
    def test_template_rows_import(self):
        conn = fresh()
        path = write_csv(TEMPLATE)
        r = import_ledger(conn, path, "종로B")
        self.assertEqual(r["imported"], 3)          # 서브마리너·클미·문워치 전부 매칭
        self.assertEqual(len(r["unmatched"]), 0)
        envs = {e for (e,) in conn.execute("select data_environment from assets")}
        self.assertEqual(envs, {"BACKFILL"})
        n_liq = conn.execute("select count(*) from transactions"
                             " where transaction_type='liquidation'").fetchone()[0]
        self.assertEqual(n_liq, 1)
        n_cases = conn.execute("select count(*) from finance_cases").fetchone()[0]
        self.assertEqual(n_cases, 3)
        kinds = {k for (k,) in conn.execute("select event_kind from finance_events")}
        self.assertEqual(kinds, {"origination", "repayment", "default"})
        sh = conn.execute("select serial_hash from authentication_evidence"
                          " limit 1").fetchone()[0]
        self.assertNotIn("7218", sh)
        q = r["quality"]
        self.assertEqual(q["match_pct"], 100.0)
        self.assertEqual(q["liquidation_completeness_pct"], 100.0)
        os.unlink(path)

    def test_unmatched_reported_not_guessed(self):
        conn = fresh()
        path = write_csv(
            "row_id,pawn_date,item_description,brand,model_hint,serial,grade,"
            "appraisal_krw,loan_krw,outcome,liquidation_krw,liquidation_date\n"
            "9,2025-01-01,알 수 없는 물건,,,,A,1000000,600000,open,,\n")
        r = import_ledger(conn, path, "P1")
        self.assertEqual(r["imported"], 0)
        self.assertEqual(len(r["unmatched"]), 1)
        self.assertEqual(conn.execute("select count(*) from assets"
                                      ).fetchone()[0], 0)
        os.unlink(path)

    def test_rerun_skips_duplicates(self):
        conn = fresh()
        path = write_csv(TEMPLATE)
        import_ledger(conn, path, "종로B")
        r2 = import_ledger(conn, path, "종로B")
        self.assertEqual(r2["imported"], 0)
        self.assertEqual(r2["duplicates_skipped"], 3)
        self.assertEqual(conn.execute("select count(*) from assets"
                                      ).fetchone()[0], 3)
        os.unlink(path)

    def test_dry_run_writes_nothing(self):
        conn = fresh()
        path = write_csv(TEMPLATE)
        r = import_ledger(conn, path, "종로B", dry_run=True)
        self.assertEqual(r["imported"], 3)
        self.assertEqual(conn.execute("select count(*) from assets"
                                      ).fetchone()[0], 0)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
