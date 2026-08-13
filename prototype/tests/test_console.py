"""T8·T9 콘솔 테스트 — HTTP로 등록→AI→검증(correction)→bid→거래 흐름."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import db as coredb
from intake import ai_assist

CID = "WATCH-ROLEX-SUBMARINER-126610LN"
WRONG = "WATCH-ROLEX-GMT-126710BLNR"


class ConsoleFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as appmod
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp.name, "real.db")
        coredb.DB_FILES["REAL"] = cls.db_path      # 테스트 전용 DB로 라우팅
        coredb.connect("REAL", path=cls.db_path).close()
        appmod.Handler.env = "REAL"
        cls.srv = HTTPServer(("127.0.0.1", 0), appmod.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def _post(self, path, data, follow=False):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=urllib.parse.urlencode(data).encode(), method="POST")
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, resp.geturl()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _get(self, path):
        return urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}").read().decode()

    def conn(self):
        return coredb.connect("REAL", path=self.db_path)

    def test_full_console_flow(self):
        # ① 등록 (urlencoded — 사진 없음)
        status, loc = self._post("/console/register",
                                 {"source": "drrrk", "registered_by": "staff:t"})
        self.assertEqual(status, 200)  # 303 redirect follow 후 200
        aid = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["id"][0]

        # ② AI 후보 기록 (오답 top-1)
        c = self.conn()
        pid = ai_assist.record_prediction(
            c, aid, "identity",
            {"candidates": [
                {"canonical_asset_id": WRONG, "confidence": 0.6, "evidence": "베젤"},
                {"canonical_asset_id": CID, "confidence": 0.3, "evidence": "각인"}]},
            0.6, "gemini-mock", "0.1")
        c.close()

        # 콘솔 페이지에 AI 후보가 보인다
        page = self._get(f"/console/asset?id={aid}")
        self.assertIn(WRONG, page)
        self.assertIn("correction", page.lower())

        # ③ correction 사유 없이 다른 모델 확정 → 400 오류
        status, body = self._post("/console/verify", {
            "asset_id": aid, "choice": CID, "ai_top1": WRONG,
            "ai_prediction_id": pid, "verified_by": "expert:kim",
            "started_at": "2026-08-13T10:00:00"})
        self.assertEqual(status, 400)
        self.assertIn("correction", body)

        # ④ 사유와 함께 확정 + 등급
        status, loc = self._post("/console/verify", {
            "asset_id": aid, "choice": CID, "ai_top1": WRONG,
            "ai_prediction_id": pid, "verified_by": "expert:kim",
            "correction_reason": "reference_mismatch", "grade": "A",
            "started_at": "2026-08-13T10:00:00"})
        self.assertEqual(status, 200)
        c = self.conn()
        st, cid2, grade = c.execute(
            "select identity_status, canonical_asset_id, grade from assets"
            " where asset_id=?", (aid,)).fetchone()
        self.assertEqual((st, cid2, grade), ("HUMAN_VERIFIED", CID, "A"))
        n_corr = c.execute(
            "select count(*) from verification_corrections vc join"
            " human_verifications v using (verification_id) where v.asset_id=?",
            (aid,)).fetchone()[0]
        self.assertEqual(n_corr, 1)
        # 검증 시간 기록됨
        started = c.execute("select started_at from human_verifications"
                            " where asset_id=? and field='identity'",
                            (aid,)).fetchone()[0]
        self.assertEqual(started, "2026-08-13T10:00:00")

        # ⑤ 진위 evidence
        status, _ = self._post("/console/auth", {
            "asset_id": aid, "evidence_type": "serial", "result": "pass",
            "serial": "S123", "auth_source": "expert:kim"})
        self.assertEqual(status, 200)
        n_auth = c.execute("select count(*) from authentication_evidence"
                           " where asset_id=?", (aid,)).fetchone()[0]
        self.assertEqual(n_auth, 1)
        c.close()
        self.__class__.verified_aid = aid  # T9 테스트에서 이어서 사용

    def test_multipart_register_with_photo(self):
        boundary = "XBOUND"
        parts = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="source"\r\n\r\n'
            f'drrrk\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
            f'filename="dial.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode() \
            + b"\xff\xd8FAKEJPEG" + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/console/register", data=parts,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        resp = urllib.request.urlopen(req)
        aid = urllib.parse.parse_qs(
            urllib.parse.urlparse(resp.geturl()).query)["id"][0]
        c = self.conn()
        path, sha = c.execute("select file_path, sha256 from asset_images"
                              " where asset_id=?", (aid,)).fetchone()
        c.close()
        self.assertIn("dial.jpg", path)
        self.assertTrue(os.path.exists(os.path.join(ROOT, path)))
        self.assertEqual(len(sha), 64)


if __name__ == "__main__":
    unittest.main()


class MarketFlow(ConsoleFlow):
    """T9 — 콘솔 HTTP로 bid 수명주기·거래·비용·외부 comp."""

    def test_market_flow(self):
        _, loc = self._post("/console/register", {"source": "drrrk"})
        aid = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["id"][0]
        c = self.conn()
        from intake import verify as vfy
        vfy.complete_verification(c, aid, "identity", CID, "expert:kim")
        c.close()

        # bid 등록 → FIRM 승격 → COMMITTED → 낙찰 → 정산
        self._post("/console/bid", {"asset_id": aid, "buyer_id": "buyer:B",
                                    "price_krw": "12000000",
                                    "bid_time": "2026-08-10"})
        c = self.conn()
        b1 = c.execute("select bid_id from dealer_bids where asset_id=?",
                       (aid,)).fetchone()[0]
        c.close()
        self._post("/console/bid-action", {"asset_id": aid, "bid_id": b1,
                                           "act": "promote_FIRM"})
        c = self.conn()
        b2 = c.execute("select bid_id from dealer_bids where asset_id=?"
                       " and bid_type='FIRM'", (aid,)).fetchone()[0]
        c.close()
        self._post("/console/bid-action", {"asset_id": aid, "bid_id": b2,
                                           "act": "promote_COMMITTED"})
        c = self.conn()
        b3 = c.execute("select bid_id from dealer_bids where asset_id=?"
                       " and bid_type='COMMITTED'", (aid,)).fetchone()[0]
        c.close()
        self._post("/console/bid-action", {"asset_id": aid, "bid_id": b3,
                                           "act": "select"})
        self._post("/console/bid-action", {"asset_id": aid, "bid_id": b3,
                                           "act": "settle_ok"})

        # 거래 + 비용 + 외부 comp
        self._post("/console/transaction", {
            "asset_id": aid, "transaction_type": "sale",
            "gross_price_krw": "12000000", "contracted_at": "2026-08-13",
            "settled_at": "2026-08-14", "days_to_sale": "3"})
        c = self.conn()
        tid = c.execute("select transaction_id from transactions where asset_id=?",
                        (aid,)).fetchone()[0]
        c.close()
        self._post("/console/cost", {"asset_id": aid, "transaction_id": tid,
                                     "cost_type": "platform_fee",
                                     "amount_krw": "360000"})
        self._post("/console/external", {
            "asset_id": aid, "canonical_asset_id": CID,
            "kind": "EXTERNAL_SOLD", "price_krw": "14900000",
            "ext_source": "kream", "observed_at": "2026-08-12"})

        c = self.conn()
        types = {r[0] for r in c.execute(
            "select bid_type from dealer_bids where asset_id=?", (aid,))}
        self.assertEqual(types, {"INDICATIVE", "FIRM", "COMMITTED", "SETTLED"})
        from market import transactions as mtx
        np_ = mtx.net_proceeds(c, tid)
        self.assertEqual(np_["net_proceeds_krw"], 12000000 - 360000)
        n_ext = c.execute("select count(*) from market_events where"
                          " canonical_asset_id=? and source_type='EXTERNAL_SOLD'",
                          (CID,)).fetchone()[0]
        self.assertGreaterEqual(n_ext, 1)
        # 자산 페이지에 net proceeds가 표시된다
        page = self._get(f"/console/asset?id={aid}")
        self.assertIn("11,640,000", page)
        c.close()

    # 부모 클래스 테스트 중복 실행 방지
    test_full_console_flow = None
    test_multipart_register_with_photo = None
