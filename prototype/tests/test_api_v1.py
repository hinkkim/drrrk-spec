"""T17 기관 API v1 테스트 — 버전드 envelope·인증·정책 분리."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake import ingest, verify as vfy
from market import bids

CID = "WATCH-ROLEX-SUBMARINER-126610LN"


class ApiV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as appmod
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "real.db")
        coredb.DB_FILES["REAL"] = path
        conn = coredb.connect("REAL", path=path)
        aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                    canonical_asset_id=CID, grade="A")
        vfy.complete_verification(conn, aid, "identity", CID, "expert:kim")
        bids.place_bid(conn, aid, "buyer:1", 12000000, "FIRM",
                       bid_time="2026-08-10")
        conn.close()
        appmod.Handler.env = "REAL"
        cls.srv = HTTPServer(("127.0.0.1", 0), appmod.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()
        os.environ.pop("DRRRK_API_KEY", None)

    def _get(self, path, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_asset_envelope(self):
        os.environ.pop("DRRRK_API_KEY", None)
        status, p = self._get("/api/v1/asset?q=%EC%84%9C%EB%B8%8C%EB%A7%88%EB%A6%AC%EB%84%88&grade=A")
        self.assertEqual(status, 200)
        self.assertEqual(p["api_version"], "v1")
        self.assertEqual(p["environment"], "REAL")
        self.assertIn("여신 정책", p["notice"])       # 기관 정책 분리 고지
        self.assertIn("generated_at", p)
        r = p["report"]
        self.assertEqual(r["asset"]["canonical_asset_id"], CID)
        self.assertIn(r["ltv"]["status"], ("AVAILABLE", "NOT_AVAILABLE"))
        self.assertIn("rule_version", r)

    def test_assets_coverage_list(self):
        os.environ.pop("DRRRK_API_KEY", None)
        status, p = self._get("/api/v1/assets")
        self.assertEqual(status, 200)
        self.assertEqual(p["count"], 22)
        sub = next(a for a in p["assets"] if a["canonical_asset_id"] == CID)
        self.assertEqual(sub["sample"]["firm_bids"], 1)

    def test_not_found_and_unknown_route(self):
        os.environ.pop("DRRRK_API_KEY", None)
        _, p = self._get("/api/v1/asset?q=nonexistent-model-xyz")
        self.assertEqual(p["error"], "not_found")

    def test_bearer_auth_when_key_set(self):
        os.environ["DRRRK_API_KEY"] = "sekrit"
        try:
            status, p = self._get("/api/v1/assets")
            self.assertEqual(status, 401)
            status, p = self._get("/api/v1/assets", token="wrong")
            self.assertEqual(status, 401)
            status, p = self._get("/api/v1/assets", token="sekrit")
            self.assertEqual(status, 200)
        finally:
            os.environ.pop("DRRRK_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
