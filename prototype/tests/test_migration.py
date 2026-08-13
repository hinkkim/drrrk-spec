"""T3 마이그레이션 대사 테스트 — legacy → v1 이식의 무손실·멱등성."""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sim"))

from migrate_v1 import migrate

_conn = None      # 시뮬레이션이 느리므로 클래스 간 공유 (읽기 전용 대사)
_counts = None


def sim_legacy_db():
    """작은 legacy 시뮬레이션 DB를 메모리에 생성 (migrate 미적용)."""
    from simulate import run_simulation
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(ROOT, "sim", "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("create table _seed_meta (canonical_asset_id text primary key,"
                 " base_retail_krw integer, popularity integer)")
    import csv
    with open(os.path.join(ROOT, "catalog_seed.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("insert into asset_master (canonical_asset_id, category,"
                         " brand, model, reference_no, aliases) values (?,?,?,?,?,?)",
                         (row["canonical_asset_id"], row["category"], row["brand"],
                          row["model"], row["reference_no"], row["aliases"]))
            conn.execute("insert into _seed_meta values (?,?,?)",
                         (row["canonical_asset_id"], int(row["base_retail_krw"]),
                          int(row["popularity"])))
    run_simulation(conn, days=45, listings_per_day=2.0, seed=7,
                   backfill_pawn_deals=40)
    return conn


def shared():
    global _conn, _counts
    if _conn is None:
        _conn = sim_legacy_db()
        _counts = migrate(_conn, "SIMULATION")
    return _conn, _counts


class Reconciliation(unittest.TestCase):
    def test_every_event_migrated(self):
        conn, counts = shared()
        for etype, n in counts["legacy"].items():
            self.assertEqual(counts["migrated"].get(etype, 0), n,
                             f"{etype} 이식 누락")

    def test_compat_view_row_counts_match(self):
        conn, counts = shared()
        legacy = dict(conn.execute(
            "select event_type, count(*) from valuation_event group by event_type"))
        v1 = dict(conn.execute(
            "select event_type, count(*) from valuation_event_v group by event_type"))
        legacy.pop("correction", None)  # correction은 audit_logs로 이관 (뷰 제외)
        self.assertEqual(legacy, v1)

    def test_instances_become_assets(self):
        conn, _ = shared()
        n_inst = conn.execute("select count(*) from asset_instance").fetchone()[0]
        n_assets = conn.execute("select count(*) from assets").fetchone()[0]
        self.assertEqual(n_inst, n_assets)

    def test_idempotent(self):
        conn, _ = shared()
        before = conn.execute("select count(*) from dealer_bids").fetchone()[0]
        counts2 = migrate(conn, "SIMULATION")
        after = conn.execute("select count(*) from dealer_bids").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(sum(counts2["migrated"].values()), 0)

    def test_quotes_are_indicative_observed(self):
        conn, _ = shared()
        row = conn.execute(
            "select count(*) from dealer_bids where bid_type != 'INDICATIVE'"
            " or evidence_class != 'OBSERVED'"
            " or source_type != 'DEALER_INDICATIVE_BID'").fetchone()
        self.assertEqual(row[0], 0)

    def test_migrated_sales_flag_costs_unknown(self):
        conn, _ = shared()
        row = conn.execute("select count(*) from transactions"
                           " where costs_unknown != 1").fetchone()
        self.assertEqual(row[0], 0)

    def test_environment_all_simulation(self):
        conn, _ = shared()
        for table in ("assets", "dealer_bids", "transactions", "market_events",
                      "appraisals", "finance_events"):
            n = conn.execute(f"select count(*) from {table}"
                             " where data_environment != 'SIMULATION'").fetchone()[0]
            self.assertEqual(n, 0, f"{table}에 SIMULATION이 아닌 행 존재")


class RealEnvRefusesAiEstimates(unittest.TestCase):
    def test_refuse(self):
        conn = sqlite3.connect(":memory:")
        with open(os.path.join(ROOT, "sim", "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                     " model) values ('WATCH-X-Y-1','WATCH','X','Y')")
        conn.execute("insert into valuation_event (event_id, canonical_asset_id,"
                     " deal_type, event_type, value_krw, observed_at, source)"
                     " values ('e1','WATCH-X-Y-1','sale','ai_estimate',100,"
                     "'2026-01-01','ledger:v0')")
        with self.assertRaises(SystemExit):
            migrate(conn, "REAL")


if __name__ == "__main__":
    unittest.main()
