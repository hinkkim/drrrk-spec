"""T6 게이팅 테스트 — No-Fake-Confidence (§12).

빈 원장 → 전부 산출 불가 + 사유. FIRM·정산 실측·식별 확정이 갖춰져야 LTV가 나온다.
"""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake import ingest
from market import bids, transactions as tx
from engine import baseline, liquidation
from report import asset_report

CID = "WATCH-ROLEX-SUBMARINER-126610LN"


def fresh():
    conn = sqlite3.connect(":memory:")
    coredb.init_schema(conn, "REAL", seed_catalog=False)
    conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                 f" model, aliases) values ('{CID}','WATCH','Rolex','Submariner',"
                 "'서브마리너')")
    return conn


def rich(firm_bids=6, settled_sales=3, day="2026-08"):
    """FIRM bid·정산 실측이 충분한 원장."""
    conn = fresh()
    for i in range(firm_bids):
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID, grade="A")
        bids.place_bid(conn, aid, f"buyer:{i%4}", 11800000 + i * 90000, "FIRM",
                       bid_time=f"{day}-{i+1:02d}")
    for i in range(settled_sales):
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID, grade="A")
        t = tx.record_transaction(conn, aid, "sale", 12100000 + i * 50000,
                                  f"{day}-{i+10:02d}",
                                  settled_at=f"{day}-{i+12:02d}", days_to_sale=3)
        tx.add_cost(conn, t, "platform_fee", 363000)
    conn.execute("insert into market_events (market_event_id, canonical_asset_id,"
                 " source_type, price_krw, source, data_environment, observed_at)"
                 f" values ('m1','{CID}','EXTERNAL_SOLD',14900000,'kream','REAL',"
                 f"'{day}-05')")
    return conn


class EmptyLedger(unittest.TestCase):
    def test_compat_insufficient(self):
        conn = fresh()
        r = baseline.analyze_asset_compat(conn, CID)
        self.assertEqual(r["confidence"], "insufficient")
        self.assertIsNone(r["recommended_ltv_pct"])
        self.assertIn("no_firm_bid", r["ltv_reasons"])
        self.assertIsNone(r["market_value_krw"])
        self.assertIn("note", r)

    def test_estimate_insufficient_no_numbers(self):
        conn = fresh()
        e = liquidation.estimate(conn, CID, 30)
        self.assertEqual(e["confidence"], "INSUFFICIENT")
        self.assertIsNone(e["range_low_krw"])
        self.assertIsNone(e["range_mid_krw"])
        self.assertTrue(e["reason_codes"])

    def test_report_ltv_not_available(self):
        conn = fresh()
        r = asset_report.build(conn, CID)
        self.assertEqual(r["ltv"]["status"], "NOT_AVAILABLE")
        self.assertTrue(r["ltv"]["reasons"])
        self.assertEqual(r["data_quality"]["evidence_grade"], "D")


class RichLedger(unittest.TestCase):
    def test_ltv_available_with_firm_and_settled(self):
        conn = rich()
        r = baseline.analyze_asset_compat(conn, CID)
        self.assertEqual(r["ltv_reasons"], [])
        self.assertIsNotNone(r["recommended_ltv_pct"])
        self.assertGreater(r["recommended_ltv_pct"], 0)
        self.assertLess(r["recommended_ltv_pct"], 100)

    def test_estimate_has_range_and_confidence(self):
        conn = rich()
        e = liquidation.estimate(conn, CID, 30)
        self.assertIn(e["confidence"], ("MEDIUM", "HIGH"))
        self.assertLessEqual(e["range_low_krw"], e["range_mid_krw"])
        self.assertLessEqual(e["range_mid_krw"], e["range_high_krw"])
        # 7일 급처분 범위는 30일보다 보수적이어야 한다
        e7 = liquidation.estimate(conn, CID, 7)
        self.assertLessEqual(e7["range_mid_krw"], e["range_mid_krw"])

    def test_grade_adjustment(self):
        conn = rich()
        ea = liquidation.estimate(conn, CID, 30, grade="A")
        ec = liquidation.estimate(conn, CID, 30, grade="C")
        self.assertLess(ec["range_mid_krw"], ea["range_mid_krw"])

    def test_persist_estimate(self):
        conn = rich()
        e = liquidation.estimate(conn, CID, 30, persist=True, env="REAL")
        row = conn.execute("select confidence, evidence_class from"
                           " liquidation_estimates where estimate_id=?",
                           (e["estimate_id"],)).fetchone()
        self.assertEqual(row[1], "ESTIMATED")

    def test_outcome_reconciliation(self):
        conn = rich()
        e = liquidation.estimate(conn, CID, 30, persist=True, env="REAL")
        tid = conn.execute("select transaction_id from transactions limit 1"
                           ).fetchone()[0]
        oid = tx.record_outcome(conn, e["estimate_id"], tid)
        err = conn.execute("select error_pct from outcomes where outcome_id=?",
                           (oid,)).fetchone()[0]
        self.assertIsNotNone(err)


class IdentityGate(unittest.TestCase):
    def test_unverified_asset_blocks_ltv(self):
        conn = rich()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID)  # AI_CANDIDATE
        r = asset_report.build(conn, CID, asset_id=aid)
        self.assertEqual(r["ltv"]["status"], "NOT_AVAILABLE")
        self.assertIn("identification_unverified", r["ltv"]["reasons"])
        e = liquidation.estimate(conn, CID, 30, asset_id=aid)
        self.assertIn("identification_unverified", e["reason_codes"])
        self.assertEqual(e["confidence"], "LOW")


class StaleGate(unittest.TestCase):
    def test_stale_market_evidence(self):
        conn = rich(day="2025-01")
        # 최신 관측이 2026-08 (market event 없이 bid만 오래됨) — as_of 강제
        from datetime import date
        r = baseline.analyze_asset_compat(conn, CID, as_of=date(2026, 8, 1))
        self.assertIn("stale_market_evidence", r["ltv_reasons"])
        self.assertIsNone(r["recommended_ltv_pct"])


if __name__ == "__main__":
    unittest.main()
