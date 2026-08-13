"""T12 KPI 테스트 — 관통 시나리오 원장에서 §20 지표가 정확히 잡히는지."""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
import e2e_scenario
import kpi


class KpiOnE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(":memory:")
        coredb.init_schema(cls.conn, "REAL", seed_catalog=True)
        e2e_scenario.run(cls.conn, quiet=True)
        cls.k = kpi.compute(cls.conn)

    def test_data_section(self):
        d = self.k["data"]
        self.assertEqual(d["verified_assets"], 1)
        self.assertEqual(d["verification_coverage_pct"], 100.0)
        # e2e에서 AI top-1은 오답(GMT), top-3 안에는 정답 존재
        self.assertEqual(d["ai_top1_identity_accuracy_pct"], 0.0)
        self.assertEqual(d["ai_top3_recall_pct"], 100.0)
        self.assertEqual(d["human_correction_rate_pct"], 100.0)
        self.assertEqual(d["evidence_completeness_pct"], 100.0)  # 사진·상태·진위 모두

    def test_ops_section(self):
        o = self.k["ops"]
        self.assertEqual(o["verifications_total"], 2)  # identity + condition
        self.assertEqual(o["human_review_ratio_pct"], 100.0)
        self.assertIsNotNone(o["median_verification_minutes"])

    def test_market_section(self):
        m = self.k["market"]
        self.assertGreaterEqual(m["unique_buyers"], 3)
        self.assertEqual(m["firm_to_settlement_conversion_pct"], 100.0)
        self.assertEqual(m["settlement_failures"], 0)
        self.assertEqual(m["days_to_sale_median"], 4)

    def test_valuation_calibration(self):
        v = self.k["valuation"]
        self.assertEqual(v["outcomes_n"], 1)
        self.assertIn("LOW", v["calibration_by_confidence"])
        self.assertIsNotNone(v["mean_abs_error_pct"])

    def test_render_runs(self):
        text = kpi.render(self.k)
        self.assertIn("Data", text)
        self.assertIn("FIRM→정산 전환", text)


class KpiEmptyLedger(unittest.TestCase):
    def test_no_fake_numbers(self):
        conn = sqlite3.connect(":memory:")
        coredb.init_schema(conn, "REAL", seed_catalog=False)
        k = kpi.compute(conn)
        self.assertIsNone(k["data"]["verification_coverage_pct"])
        self.assertIsNone(k["data"]["ai_top1_identity_accuracy_pct"])
        self.assertIsNone(k["ops"]["median_verification_minutes"])
        self.assertEqual(k["valuation"]["outcomes_n"], 0)
        kpi.render(k)  # 빈 원장에서도 렌더가 죽지 않는다


if __name__ == "__main__":
    unittest.main()
