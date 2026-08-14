"""T14 캘리브레이션 루프 테스트 — 추정↔정산 자동 대사·멱등성."""
import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import liquidation
from engine.calibration import reconcile, summary
from tests.test_engine_gating import rich, CID


def ledger_with_prior_estimate():
    """bid(08-01~06) 이후, 거래(08-10 계약·08-12 정산) 이전 시점의 추정."""
    conn = rich(firm_bids=6, settled_sales=3)
    liquidation.estimate(conn, CID, 30, as_of=date(2026, 8, 7),
                         persist=True, env="REAL")
    return conn


class Reconcile(unittest.TestCase):
    def test_matches_and_records_outcome(self):
        conn = ledger_with_prior_estimate()
        res = reconcile(conn)
        self.assertEqual(res["matched"], 1)
        n = conn.execute("select count(*) from outcomes").fetchone()[0]
        self.assertEqual(n, 1)
        err = conn.execute("select error_pct from outcomes").fetchone()[0]
        self.assertIsNotNone(err)

    def test_idempotent(self):
        conn = ledger_with_prior_estimate()
        reconcile(conn)
        res2 = reconcile(conn)
        self.assertEqual(res2["matched"], 0)
        self.assertEqual(conn.execute("select count(*) from outcomes"
                                      ).fetchone()[0], 1)

    def test_insufficient_estimates_skipped(self):
        conn = rich()
        # 데이터가 전혀 없는 시점의 추정 → INSUFFICIENT → 대사 대상 아님
        e = liquidation.estimate(conn, CID, 30, as_of=date(2025, 1, 1),
                                 persist=True, env="REAL")
        self.assertEqual(e["confidence"], "INSUFFICIENT")
        res = reconcile(conn)
        self.assertEqual(res["matched"], 0)

    def test_deadline_respected(self):
        conn = rich(settled_sales=1)
        liquidation.estimate(conn, CID, 7, as_of=date(2026, 8, 6),
                             persist=True, env="REAL")
        # 7일 horizon + 30일 유예 = 09-12까지 유효 → 08-12 정산은 매칭됨
        res = reconcile(conn)
        self.assertEqual(res["matched"], 1)

    def test_summary_by_confidence(self):
        conn = ledger_with_prior_estimate()
        reconcile(conn)
        cal = summary(conn)
        self.assertEqual(cal["outcomes_n"], 1)
        self.assertTrue(cal["calibration_by_confidence"])


if __name__ == "__main__":
    unittest.main()
