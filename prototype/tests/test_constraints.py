"""T1 제약·불변식 테스트 — 스키마 수준에서 원칙이 강제되는지 확인.

실행: python3 -m unittest discover -s tests  (prototype/ 에서)
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fresh_conn():
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(HERE, "core", "schema_v1.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("insert into asset_master (canonical_asset_id, category, brand, model)"
                 " values ('WATCH-X-Y-1','WATCH','X','Y')")
    conn.execute("insert into assets (asset_id, canonical_asset_id, data_environment,"
                 " source) values ('a1','WATCH-X-Y-1','REAL','drrrk')")
    return conn


class AuditAppendOnly(unittest.TestCase):
    def test_no_update(self):
        conn = fresh_conn()
        audit.log(conn, "tester", "insert", "assets", "a1")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update audit_logs set actor='hacker'")

    def test_no_delete(self):
        conn = fresh_conn()
        audit.log(conn, "tester", "insert", "assets", "a1")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("delete from audit_logs")


class AiPredictionNoPrice(unittest.TestCase):
    """AI 산출물에 가격이 존재할 수 없다 — 스키마 CHECK."""

    def _insert(self, conn, payload):
        conn.execute(
            "insert into ai_predictions (prediction_id, asset_id, prediction_type,"
            " payload, data_environment, observed_at)"
            " values ('p1','a1','identity',?,'REAL','2026-08-13')", (payload,))

    def test_price_key_rejected(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert(conn, '{"price": 1000}')

    def test_krw_key_rejected(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert(conn, '{"estimate_krw": 1000}')

    def test_clean_payload_accepted(self):
        conn = fresh_conn()
        self._insert(conn, '{"candidates": [{"canonical_asset_id": "WATCH-X-Y-1",'
                           ' "confidence": 0.94, "evidence": "다이얼 각인"}]}')

    def test_immutable(self):
        conn = fresh_conn()
        self._insert(conn, '{"candidates": []}')
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update ai_predictions set confidence=1.0")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("delete from ai_predictions")


class EvidenceClassEnforced(unittest.TestCase):
    def test_firm_bid_must_be_observed(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into dealer_bids (bid_id, asset_id, buyer_id, bid_type,"
                " bid_price_krw, bid_time, source, source_type, evidence_class,"
                " data_environment) values ('b1','a1','buyer:1','FIRM',100,"
                "'2026-08-13','buyer:1','DEALER_FIRM_BID','ESTIMATED','REAL')")

    def test_snapshot_must_be_derived(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into liquidity_snapshots (snapshot_id, snapshot_date,"
                " canonical_asset_id, window_days, evidence_class, data_environment)"
                " values ('s1','2026-08-13','WATCH-X-Y-1',180,'OBSERVED','REAL')")

    def test_estimate_must_be_estimated(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into liquidation_estimates (estimate_id, canonical_asset_id,"
                " horizon_days, confidence, rule_version, evidence_class,"
                " data_environment, estimated_at) values ('e1','WATCH-X-Y-1',30,"
                "'LOW','rule-v1','OBSERVED','REAL','2026-08-13')")


class BidImmutability(unittest.TestCase):
    def _bid(self, conn):
        conn.execute(
            "insert into dealer_bids (bid_id, asset_id, buyer_id, bid_type,"
            " bid_price_krw, bid_time, source, source_type, data_environment)"
            " values ('b1','a1','buyer:1','INDICATIVE',100,'2026-08-13',"
            "'buyer:1','DEALER_INDICATIVE_BID','REAL')")

    def test_price_immutable(self):
        conn = fresh_conn()
        self._bid(conn)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update dealer_bids set bid_price_krw=999 where bid_id='b1'")

    def test_type_immutable(self):
        conn = fresh_conn()
        self._bid(conn)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update dealer_bids set bid_type='FIRM' where bid_id='b1'")

    def test_status_mutable(self):
        conn = fresh_conn()
        self._bid(conn)
        conn.execute("update dealer_bids set status='expired' where bid_id='b1'")

    def test_no_delete(self):
        conn = fresh_conn()
        self._bid(conn)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("delete from dealer_bids where bid_id='b1'")


class TransactionCosts(unittest.TestCase):
    def test_net_proceeds_derived(self):
        conn = fresh_conn()
        conn.execute(
            "insert into transactions (transaction_id, asset_id, canonical_asset_id,"
            " transaction_type, gross_price_krw, contracted_at, source, source_type,"
            " data_environment) values ('t1','a1','WATCH-X-Y-1','sale',12100000,"
            "'2026-08-13','drrrk','ACTUAL_SALE','REAL')")
        conn.execute("insert into transaction_costs (cost_id, transaction_id, cost_type,"
                     " amount_krw) values ('c1','t1','platform_fee',363000)")
        conn.execute("insert into transaction_costs (cost_id, transaction_id, cost_type,"
                     " amount_krw) values ('c2','t1','shipping',30000)")
        row = conn.execute("select total_costs_krw, net_proceeds_krw from v_net_proceeds"
                           " where transaction_id='t1'").fetchone()
        self.assertEqual(row, (393000, 12100000 - 393000))

    def test_gross_immutable(self):
        conn = fresh_conn()
        conn.execute(
            "insert into transactions (transaction_id, asset_id, transaction_type,"
            " gross_price_krw, contracted_at, source, source_type, data_environment)"
            " values ('t1','a1','sale',100,'2026-08-13','drrrk','ACTUAL_SALE','REAL')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update transactions set gross_price_krw=1 where transaction_id='t1'")


class HumanVerificationImmutable(unittest.TestCase):
    def test_no_update(self):
        conn = fresh_conn()
        conn.execute(
            "insert into human_verifications (verification_id, asset_id, field,"
            " verified_value, verified_by, completed_at, data_environment)"
            " values ('v1','a1','identity','WATCH-X-Y-1','expert:kim',"
            "'2026-08-13T10:00','REAL')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("update human_verifications set verified_value='OTHER'")


if __name__ == "__main__":
    unittest.main()
