"""T7 인수 테스트 — 관통 시나리오를 unittest로 상시 실행."""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
import e2e_scenario


class EndToEnd(unittest.TestCase):
    def test_full_flow(self):
        conn = sqlite3.connect(":memory:")
        coredb.init_schema(conn, "REAL", seed_catalog=True)
        out = e2e_scenario.run(conn, quiet=True)
        checks = e2e_scenario.verify_result(conn, out)
        for step, n in checks.items():
            self.assertGreater(n, 0, f"{step} 누락")
        # 사전 추정은 표본이 얇으므로 HIGH가 나오면 안 된다 (No-Fake-Confidence)
        self.assertIn(out["estimate"]["confidence"],
                      ("LOW", "MEDIUM", "INSUFFICIENT"))
        # 리포트의 outcome에 net proceeds가 실려 있다
        txs = out["report"]["outcome"]["recent_transactions"]
        self.assertEqual(txs[0]["net_proceeds_krw"], 12100000 - 393000)


if __name__ == "__main__":
    unittest.main()
