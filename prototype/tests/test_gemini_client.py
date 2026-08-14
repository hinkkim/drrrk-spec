"""T16 Gemini 클라이언트 테스트 — 네트워크 없이 전체 로직 검증 (caller 주입)."""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake import ingest
from intake.gemini_client import (identify, validate_response, build_prompt,
                                  catalog_subset)

CID = "WATCH-ROLEX-SUBMARINER-126610LN"


def fresh():
    conn = sqlite3.connect(":memory:")
    coredb.init_schema(conn, "REAL", seed_catalog=True)
    return conn


def fake_caller(response):
    def _call(api_key, prompt, image_paths, model=None, timeout=None):
        return response
    return _call


class Validation(unittest.TestCase):
    def test_out_of_catalog_candidate_dropped(self):
        out = validate_response(
            {"brand": "Rolex", "candidates": [
                {"canonical_asset_id": "WATCH-FAKE-NOPE-1", "confidence": 0.9},
                {"canonical_asset_id": CID, "confidence": 0.8,
                 "evidence": "각인"}],
             "grade_estimate": "A"},
            {CID})
        self.assertEqual(len(out["candidates"]), 1)
        self.assertEqual(out["candidates"][0]["canonical_asset_id"], CID)

    def test_confidence_clamped_and_grade_validated(self):
        out = validate_response(
            {"candidates": [{"canonical_asset_id": CID, "confidence": 7}],
             "grade_estimate": "Z"}, {CID})
        self.assertEqual(out["candidates"][0]["confidence"], 1.0)
        self.assertIsNone(out["grade_estimate"])


class Identify(unittest.TestCase):
    def test_records_prediction_no_price(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        resp = {"brand": "Rolex",
                "candidates": [{"canonical_asset_id": CID, "confidence": 0.62,
                                "evidence": "세라믹 베젤"}],
                "grade_estimate": "A", "authenticity_flags": [],
                "photo_requests": ["케이스백"]}
        payload, pid = identify(conn, aid, ["x.jpg"], caller=fake_caller(resp))
        self.assertTrue(payload["needs_user_confirm"])  # 0.62 < 0.75
        row = conn.execute("select payload, confidence from ai_predictions"
                           " where prediction_id=?", (pid,)).fetchone()
        self.assertIn(CID, row[0])
        self.assertEqual(row[1], 0.62)
        st = conn.execute("select identity_status from assets where asset_id=?",
                          (aid,)).fetchone()[0]
        self.assertEqual(st, "AI_CANDIDATE")   # 자동 확정 없음

    def test_price_smuggling_rejected(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        resp = {"candidates": [{"canonical_asset_id": CID, "confidence": 0.9,
                                "evidence": "시세는 1500만원 정도"}]}
        # evidence 텍스트는 통과하지만, 키에 가격이 실리면 거부되는지 확인
        bad = {"candidates": [{"canonical_asset_id": CID, "confidence": 0.9}],
               "estimated_price_krw": 15000000}
        out = validate_response(bad, {CID})
        self.assertNotIn("estimated_price_krw", out)  # 화이트리스트 조립 — 유실
        payload, _ = identify(conn, aid, ["x.jpg"], caller=fake_caller(resp))
        self.assertEqual(payload["candidates"][0]["canonical_asset_id"], CID)

    def test_missing_api_key_clear_error(self):
        conn = fresh()
        aid = ingest.register_asset(conn, source="drrrk", env="REAL")
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                identify(conn, aid, ["x.jpg"])
        finally:
            if old:
                os.environ["GEMINI_API_KEY"] = old

    def test_brand_hint_narrows_catalog(self):
        conn = fresh()
        sub = catalog_subset(conn, "Rolex")
        self.assertTrue(all(r[1] == "Rolex" for r in sub))
        self.assertIn("서브마리너", build_prompt(sub))
        full = catalog_subset(conn, "NoSuchBrand")   # 안 맞으면 전체로 폴백
        self.assertGreater(len(full), len(sub))


if __name__ == "__main__":
    unittest.main()
