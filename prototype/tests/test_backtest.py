"""T13 백테스트 테스트 — 시간 절단·누출 차단·baseline 비교."""
import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import liquidation
from engine.backtest import run_backtest
from tests.test_engine_gating import fresh, rich, CID
from intake import ingest
from market import bids, transactions as tx


class NoFutureLeak(unittest.TestCase):
    def test_estimate_ignores_future_bids(self):
        conn = rich(day="2026-08")               # bid 2026-08-01~06
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID, grade="A")
        bids.place_bid(conn, aid, "buyer:F", 99_000_000, "FIRM",
                       bid_time="2026-09-15")    # 미래의 비정상 고가 bid
        past = liquidation.estimate(conn, CID, 30, as_of=date(2026, 8, 20))
        full = liquidation.estimate(conn, CID, 30)
        self.assertEqual(past["input_sample"]["firm_bids"], 6)   # 미래 bid 제외
        self.assertEqual(full["input_sample"]["firm_bids"], 7)   # 전체는 포함
        self.assertLess(past["range_high_krw"], 20_000_000)

    def test_settled_sales_bounded(self):
        conn = rich()
        e = liquidation.estimate(conn, CID, 30, as_of=date(2026, 8, 5))
        # 정산(08-12~)은 as_of 이후 → 표본 0
        self.assertEqual(e["input_sample"]["settled_transactions"], 0)


class BacktestRun(unittest.TestCase):
    def test_backtest_on_rich_ledger(self):
        conn = rich(firm_bids=8, settled_sales=4)
        bt = run_backtest(conn, horizon_days=30, min_prior_quotes=2)
        # 첫 거래(08-10 계약)는 08-01~06 bid를 사전 데이터로 갖는다
        self.assertGreaterEqual(bt["n_transactions"], 3)
        self.assertIsNotNone(bt["baseline_mae_pct"])
        self.assertIsNotNone(bt["rule_mae_pct"])
        self.assertIn("rule_beats_baseline", bt)
        for r in bt["rows"]:      # cutoff은 항상 계약 전일
            self.assertLess(r["cutoff"], "2026-08-15")

    def test_thin_history_skipped(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID, grade="A")
        t = tx.record_transaction(conn, aid, "sale", 100, "2026-08-10",
                                  settled_at="2026-08-11")
        bt = run_backtest(conn)
        self.assertEqual(bt["n_transactions"], 0)
        self.assertEqual(bt["n_skipped_thin_history"], 1)


if __name__ == "__main__":
    unittest.main()
