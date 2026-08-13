"""T4·T5 테스트 — AI/Human 분리, bid 상태기계, 거래·비용·net proceeds."""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake import ai_assist, verify, ingest
from market import bids, transactions as tx


def fresh():
    conn = sqlite3.connect(":memory:")
    coredb.init_schema(conn, "REAL", seed_catalog=False)
    conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                 " model) values ('WATCH-ROLEX-SUBMARINER-126610LN','WATCH',"
                 "'Rolex','Submariner')")
    conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                 " model) values ('WATCH-ROLEX-GMT-126710BLNR','WATCH',"
                 "'Rolex','GMT-Master II')")
    return conn


class AiHumanSeparation(unittest.TestCase):
    def test_prediction_and_verification_are_separate_rows(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        pid = ai_assist.record_prediction(
            conn, aid, "identity",
            {"candidates": [{"canonical_asset_id": "WATCH-ROLEX-GMT-126710BLNR",
                             "confidence": 0.81, "evidence": "베젤"}]},
            0.81, "gemini-mock", "0.1")
        verify.complete_verification(
            conn, aid, "identity", "WATCH-ROLEX-SUBMARINER-126610LN",
            "expert:kim", ai_prediction_id=pid,
            correction={"reason": "reference_mismatch",
                        "before": "WATCH-ROLEX-GMT-126710BLNR"})
        # AI 예측은 그대로, 검증은 별도 행, 자산은 인간 확정값
        ai_val = conn.execute("select payload from ai_predictions"
                              " where prediction_id=?", (pid,)).fetchone()[0]
        self.assertIn("GMT", ai_val)
        hv = conn.execute("select verified_value from human_verifications"
                          " where asset_id=?", (aid,)).fetchone()[0]
        self.assertEqual(hv, "WATCH-ROLEX-SUBMARINER-126610LN")
        st, cid = conn.execute("select identity_status, canonical_asset_id"
                               " from assets where asset_id=?", (aid,)).fetchone()
        self.assertEqual((st, cid),
                         ("HUMAN_VERIFIED", "WATCH-ROLEX-SUBMARINER-126610LN"))
        # correction 사유 저장 + audit trail 존재
        reason = conn.execute("select correction_reason from"
                              " verification_corrections").fetchone()[0]
        self.assertEqual(reason, "reference_mismatch")
        n_audit = conn.execute("select count(*) from audit_logs"
                               " where record_id=?", (aid,)).fetchone()[0]
        self.assertGreaterEqual(n_audit, 2)  # register + identity_confirm

    def test_ai_payload_price_rejected_in_code(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        with self.assertRaises(ValueError):
            ai_assist.record_prediction(conn, aid, "identity",
                                        {"expected_price": 15000000},
                                        0.9, "gemini-mock", "0.1")

    def test_unknown_correction_reason_rejected(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        with self.assertRaises(ValueError):
            verify.complete_verification(
                conn, aid, "identity", "WATCH-ROLEX-SUBMARINER-126610LN",
                "expert:kim", correction={"reason": "vibes"})

    def test_serial_hash_and_duplicate_detection(self):
        conn = fresh()
        a1 = ingest.register_asset(conn, source="drrrk", env="REAL")
        a2 = ingest.register_asset(conn, source="drrrk", env="REAL")
        _, dup1 = verify.add_authentication_evidence(
            conn, a1, "serial", "pass", "expert:kim", serial="X99123")
        _, dup2 = verify.add_authentication_evidence(
            conn, a2, "serial", "pass", "expert:kim", serial="X99123")
        self.assertIsNone(dup1)
        self.assertEqual(dup2, a1)  # 같은 시리얼 재등록 탐지
        stored = conn.execute("select serial_hash from authentication_evidence"
                              " limit 1").fetchone()[0]
        self.assertNotIn("X99123", stored)  # 원문 미저장


class BidStateMachine(unittest.TestCase):
    def setUp(self):
        self.conn = fresh()
        self.aid = ingest.register_asset(
            self.conn, source="drrrk", env="REAL",
            canonical_asset_id="WATCH-ROLEX-SUBMARINER-126610LN", grade="A")

    def test_full_lifecycle(self):
        c, aid = self.conn, self.aid
        b1 = bids.place_bid(c, aid, "buyer:강남A", 11800000, "INDICATIVE")
        b2 = bids.promote_bid(c, b1, "FIRM", price_krw=12100000,
                              expiry="2026-08-20", actor="buyer:강남A")
        b3 = bids.promote_bid(c, b2, "COMMITTED", payment_capacity_verified=1,
                              actor="buyer:강남A")
        bids.select_bid(c, b3, actor="drrrk")
        b4 = bids.settle_bid(c, b3, actor="drrrk")
        rows = dict(c.execute("select bid_id, status from dealer_bids"))
        self.assertEqual(rows[b1], "superseded")
        self.assertEqual(rows[b2], "superseded")
        self.assertEqual(rows[b3], "superseded")
        self.assertEqual(rows[b4], "settled")
        chain = c.execute("select bid_type from dealer_bids order by created_at,"
                          " bid_type").fetchall()
        self.assertEqual({r[0] for r in chain},
                         {"INDICATIVE", "FIRM", "COMMITTED", "SETTLED"})

    def test_backward_promotion_rejected(self):
        b = bids.place_bid(self.conn, self.aid, "buyer:1", 100, "FIRM")
        with self.assertRaises(ValueError):
            bids.promote_bid(self.conn, b, "INDICATIVE")

    def test_skip_to_settled_rejected(self):
        b = bids.place_bid(self.conn, self.aid, "buyer:1", 100, "INDICATIVE")
        with self.assertRaises(ValueError):
            bids.promote_bid(self.conn, b, "SETTLED")

    def test_settle_requires_committed(self):
        b = bids.place_bid(self.conn, self.aid, "buyer:1", 100, "FIRM")
        bids.select_bid(self.conn, b, actor="drrrk")
        with self.assertRaises(ValueError):
            bids.settle_bid(self.conn, b, actor="drrrk")

    def test_expire_stale(self):
        b = bids.place_bid(self.conn, self.aid, "buyer:1", 100, "FIRM",
                           expiry="2026-08-01")
        n = bids.expire_stale(self.conn, as_of="2026-08-10")
        self.assertEqual(n, 1)
        st = self.conn.execute("select status from dealer_bids where bid_id=?",
                               (b,)).fetchone()[0]
        self.assertEqual(st, "expired")

    def test_settlement_failure_recorded(self):
        b = bids.place_bid(self.conn, self.aid, "buyer:1", 100, "COMMITTED")
        bids.select_bid(self.conn, b, actor="drrrk")
        bids.settle_bid(self.conn, b, actor="drrrk", settled=False)
        ss = self.conn.execute("select settlement_status from dealer_bids"
                               " where bid_id=?", (b,)).fetchone()[0]
        self.assertEqual(ss, "failed")


class TransactionsAndCosts(unittest.TestCase):
    def test_net_proceeds_flow(self):
        conn = fresh()
        aid = ingest.register_asset(
            conn, source="drrrk", env="REAL",
            canonical_asset_id="WATCH-ROLEX-SUBMARINER-126610LN")
        tid = tx.record_transaction(conn, aid, "sale", 12100000,
                                    "2026-08-04", days_to_sale=3)
        tx.add_cost(conn, tid, "platform_fee", 363000)
        tx.add_cost(conn, tid, "shipping", 30000)
        np_ = tx.net_proceeds(conn, tid)
        self.assertEqual(np_["net_proceeds_krw"], 12100000 - 393000)
        self.assertFalse(np_["costs_unknown"])

    def test_bad_cost_type_rejected(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id="WATCH-ROLEX-SUBMARINER-126610LN")
        tid = tx.record_transaction(conn, aid, "sale", 100, "2026-08-04")
        with self.assertRaises(sqlite3.IntegrityError):
            tx.add_cost(conn, tid, "bribe", 1)


if __name__ == "__main__":
    unittest.main()
