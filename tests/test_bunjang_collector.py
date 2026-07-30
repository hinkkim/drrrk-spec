#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bunjang_collector 순수 함수 테스트 (네트워크 호출 없음)

실행: python3 -m unittest discover -s tests -v
업체 판별 테스트의 예문은 실제 번개장터 업체/개인 게시글 패턴에서 가져왔다.
"""

import os
import sys
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bunjang_collector as b  # noqa: E402


def bmp_bytes(pixels):
    """[(r,g,b)] 행렬(top-down) → 24bpp 비압축 BMP 바이트."""
    h, w = len(pixels), len(pixels[0])
    row_size = (w * 3 + 3) // 4 * 4
    body = b""
    for row in reversed(pixels):           # BMP 는 bottom-up 저장
        line = b"".join(bytes((px[2], px[1], px[0])) for px in row)
        body += line + b"\x00" * (row_size - len(line))
    header = (b"BM" + (54 + len(body)).to_bytes(4, "little")
              + b"\x00" * 4 + (54).to_bytes(4, "little"))
    dib = ((40).to_bytes(4, "little")
           + w.to_bytes(4, "little", signed=True)
           + h.to_bytes(4, "little", signed=True)
           + (1).to_bytes(2, "little") + (24).to_bytes(2, "little")
           + (0).to_bytes(4, "little") + len(body).to_bytes(4, "little")
           + b"\x00" * 16)
    return header + dib + body


def solid(w, h, color, center=None):
    """단색 배경 이미지. center=(색) 지정 시 중앙 1/3 영역을 그 색으로 채운다."""
    px = [[color for _ in range(w)] for _ in range(h)]
    if center:
        for y in range(h // 3, 2 * h // 3):
            for x in range(w // 3, 2 * w // 3):
                px[y][x] = center
    return px


class TestDealerDetection(unittest.TestCase):
    """금지사항 핵심 — 중고명품 업체 게시글 판별."""

    def test_dealer_texts_from_real_listings(self):
        # 실제 업체 게시글 패턴 (스크린샷 예시)
        dealer_texts = [
            "◆중고 명품 ADEL입니다◆ 저희 상품은 수 차례 정밀한 검수 후 "
            "100% 정품인 제품만 판매를 진행하고 있으니 걱정 없이 편하게 구매하셔도 됩니다^^",
            "충주에서 매장(에이비투) 운영중입니다 직접오셔서 피팅도 가능합니다~! "
            "100% 정품만 판매합니다",
            "중고명품! 명품매입!! 부당한 감가 없이 최고가 매입",
            "중고 명품매입 크롬하츠.루이비통. 에르메스 24시간 문의 가능",
            "위탁 판매 진행합니다. 오픈채팅으로 문의주세요",
            "사업자 운영, 세금계산서 발행 가능합니다",
        ]
        for t in dealer_texts:
            self.assertIsNotNone(b.dealer_signal(t), f"업체 문구를 놓침: {t[:30]}...")

    def test_individual_texts_pass(self):
        # 개인 판매자가 흔히 쓰는 표현은 걸리면 안 된다
        individual_texts = [
            "샤넬 클미 백화점 매장에서 구매했어요. 정품입니다. 기스 없어요",
            "2021년 구매입니다. 사용감 적고 상태 좋아요",
            "선물 받았는데 스타일이 안 맞아서 내놓습니다. 네고 가능",
            "정품이고 더스트백 보증서 다 있습니다. 직거래 선호",
            "작년에 구매한 가방입니다 급처해요",
        ]
        for t in individual_texts:
            self.assertIsNone(b.dealer_signal(t), f"개인 문구를 오탐: {t[:30]}...")

    def test_dealer_flags(self):
        self.assertTrue(b.dealer_flagged({"proshop": True}))
        self.assertTrue(b.dealer_flagged({"bizseller": 1}))
        self.assertTrue(b.dealer_flagged({"shop": {"proShop": True}}))
        self.assertFalse(b.dealer_flagged({"proshop": False}, {"name": "샤넬백"}))
        self.assertFalse(b.dealer_flagged(None, {}))


class TestCleanBackground(unittest.TestCase):
    """금지사항 — 배경이 희거나 회색으로 깨끗한 사진 (스튜디오/누끼)."""

    def test_white_studio_rejected(self):
        px = b.load_bmp_pixels(bmp_bytes(solid(32, 32, (245, 245, 245), center=(139, 90, 43))))
        self.assertTrue(b.clean_background(px))

    def test_gray_studio_rejected(self):
        px = b.load_bmp_pixels(bmp_bytes(solid(32, 32, (150, 150, 152), center=(20, 20, 20))))
        self.assertTrue(b.clean_background(px))

    def test_busy_home_background_kept(self):
        # 방/옷장 등 색이 섞인 실사용 배경
        colors = [(180, 120, 60), (60, 90, 140), (120, 160, 80), (200, 80, 90)]
        px = [[colors[(x + y) % 4] for x in range(32)] for y in range(32)]
        self.assertFalse(b.clean_background(b.load_bmp_pixels(bmp_bytes(px))))

    def test_dark_background_kept(self):
        # 어두운 천 위 촬영 (개인 판매자 흔한 패턴) — 회색 아님, 통과해야 함
        px = b.load_bmp_pixels(bmp_bytes(solid(32, 32, (40, 40, 42), center=(200, 150, 100))))
        self.assertFalse(b.clean_background(px))

    def test_bmp_parser_rejects_garbage(self):
        self.assertIsNone(b.load_bmp_pixels(b"<!DOCTYPE html>"))
        self.assertIsNone(b.load_bmp_pixels(b""))
        self.assertIsNone(b.load_bmp_pixels(None))


class TestCategoryClassification(unittest.TestCase):
    def _detail(self, *names):
        return {"categories": [{"name": n} for n in names]}

    def test_bag(self):
        d = self._detail("가방/지갑", "여성가방", "크로스백")
        self.assertEqual(b.classify_category(d, ("가방", "패션잡화")), "가방")

    def test_fashion_goods(self):
        self.assertEqual(
            b.classify_category(self._detail("패션잡화", "벨트"), ("가방", "패션잡화")),
            "패션잡화")
        self.assertEqual(
            b.classify_category(self._detail("여성신발", "스니커즈"), ("가방", "패션잡화")),
            "패션잡화")

    def test_jewelry_and_watch(self):
        self.assertEqual(
            b.classify_category(self._detail("쥬얼리", "팔찌", "패션 팔찌"), ("주얼리",)),
            "주얼리")
        self.assertEqual(
            b.classify_category(self._detail("남성시계"), ("시계",)), "시계")

    def test_disallowed_or_unknown_rejected(self):
        # 의류는 대상 카테고리가 아니다
        self.assertIsNone(b.classify_category(self._detail("여성의류", "티셔츠"), ("가방",)))
        # 허용 목록에 없는 카테고리 (롤렉스에 가방이 잡히는 경우)
        self.assertIsNone(b.classify_category(self._detail("여성가방"), ("시계",)))
        # 카테고리 정보 없음 → 분류 불가 → 제외
        self.assertIsNone(b.classify_category({}, ("가방",)))


class TestPriceParsing(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(b.to_won("2500000"), 2_500_000)
        self.assertEqual(b.to_won("2,500,000"), 2_500_000)
        self.assertEqual(b.to_won("2,500,000원"), 2_500_000)
        self.assertEqual(b.to_won(None), 0)
        self.assertEqual(b.to_won(3_000_000), 3_000_000)


class TestImageSniffing(unittest.TestCase):
    def test_real_formats(self):
        self.assertEqual(b.sniff_image(b"\xff\xd8\xff\xe0" + b"\x00" * 20), "jpg")
        self.assertEqual(b.sniff_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20), "png")
        self.assertEqual(b.sniff_image(b"RIFF\x24\x00\x00\x00WEBPVP8 "), "webp")

    def test_non_image_rejected(self):
        self.assertIsNone(b.sniff_image(b"<!DOCTYPE html><html><head>err"))
        self.assertIsNone(b.sniff_image(b""))

    def test_unsupported_resolution_dropped(self):
        # w1197 은 번개장터 지원 목록에 없어 에러 응답이 내려오던 값
        self.assertNotIn("1197", b.IMAGE_RES_CANDIDATES)


class TestPiiRedaction(unittest.TestCase):
    def test_masks_contacts(self):
        self.assertEqual(b.redact_pii("연락처 010-1234-5678 로 주세요"),
                         "연락처 [전화번호] 로 주세요")
        self.assertEqual(b.redact_pii("메일 abc.d@naver.com"), "메일 [이메일]")
        self.assertEqual(b.redact_pii("카톡 hong_gil2"), "[메신저ID]")
        self.assertEqual(b.redact_pii("국민 123456-01-234567 입금"), "국민 [계좌번호] 입금")

    def test_does_not_over_redact(self):
        self.assertEqual(b.redact_pii("롤렉스 116610LN 풀세트"), "롤렉스 116610LN 풀세트")
        self.assertEqual(b.redact_pii("가격 2,500,000원"), "가격 2,500,000원")


class TestYearExtraction(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(b.extract_year("2021년 구매"), "2021")
        self.assertEqual(b.extract_year("2009년 구매"), "2009")
        self.assertEqual(b.extract_year("1998년 구입"), "1998")
        self.assertEqual(b.extract_year("샤넬19년 구매"), "2019")
        self.assertIsNone(b.extract_year("정품 보증서 있습니다"))


class TestBrandMatching(unittest.TestCase):
    def test_unicode_normalization(self):
        nfc = "Céline 클래식백"
        self.assertTrue(b.matches_brand(nfc, "셀린느"))
        self.assertTrue(b.matches_brand(unicodedata.normalize("NFD", nfc), "셀린느"))

    def test_new_brands(self):
        self.assertTrue(b.matches_brand("루이 비통 스피디30", "루이비통"))
        self.assertTrue(b.matches_brand("GUCCI 마몬트 숄더", "구찌"))
        self.assertTrue(b.matches_brand("생로랑 카바스", "생로랑"))
        self.assertTrue(b.matches_brand("보테가 조디백", "보테가베네타"))
        self.assertFalse(b.matches_brand("실버 팔찌 silver", "루이비통"))  # 'lv' 오탐 방지


class TestConfigConsistency(unittest.TestCase):
    def test_top15_with_mandatory_brands(self):
        self.assertEqual(len(b.BRANDS), 15)
        names = {brand for brand, _ in b.BRANDS}
        for must in ("에르메스", "샤넬", "디올", "루이비통", "롤렉스", "프라다"):
            self.assertIn(must, names, f"필수 브랜드 누락: {must}")

    def test_brands_have_definitions(self):
        for brand, cats in b.BRANDS:
            self.assertIn(brand, b.BRAND_ALIASES, f"{brand} alias 누락")
            for c in cats:
                self.assertIn(c, b.CATEGORY_KEYWORDS, f"{c} 키워드 누락")

    def test_image_limits(self):
        self.assertEqual(b.IMAGE_MIN, 2)
        self.assertEqual(b.IMAGE_MAX, 10)
        self.assertEqual(b.DAILY_LIMIT, 10)

    def test_docstring_matches(self):
        self.assertIn("15개", b.__doc__)


class TestRobotsSemantics(unittest.TestCase):
    """RFC 9309 — 4xx 는 제한 없음, 명시 규칙은 존중, 5xx/네트워크 오류는 보수적 차단."""

    URL = "https://api.example.com/api/1/find_v2.json"

    def setUp(self):
        b._robots_cache.clear()

    def tearDown(self):
        b._robots_cache.clear()

    def test_missing_robots_allows(self):
        # robots.txt 가 404/403 → _fetch_robots 가 빈 문자열 반환 → 전체 허용
        with mock.patch.object(b, "_fetch_robots", return_value=""):
            self.assertTrue(b.robots_allows(self.URL))

    def test_explicit_disallow_blocks(self):
        body = "User-agent: *\nDisallow: /api/"
        with mock.patch.object(b, "_fetch_robots", return_value=body):
            self.assertFalse(b.robots_allows(self.URL))

    def test_unrelated_disallow_allows(self):
        body = "User-agent: *\nDisallow: /admin/\nDisallow: /private/"
        with mock.patch.object(b, "_fetch_robots", return_value=body):
            self.assertTrue(b.robots_allows(self.URL))

    def test_server_error_blocks_conservatively(self):
        with mock.patch.object(b, "_fetch_robots", side_effect=RuntimeError("HTTP 503")):
            self.assertFalse(b.robots_allows(self.URL))

    def test_specific_bot_rule_does_not_apply_to_us(self):
        # 특정 봇만 막는 규칙은 우리(일반 UA)에게 적용되지 않아야 한다
        body = "User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nAllow: /"
        with mock.patch.object(b, "_fetch_robots", return_value=body):
            self.assertTrue(b.robots_allows(self.URL))


class TestBaseDirResolution(unittest.TestCase):
    def test_env_override(self):
        old = os.environ.get("C2C_BASE")
        os.environ["C2C_BASE"] = "/tmp/drrrk-test"
        try:
            self.assertEqual(b.resolve_base_dir(), Path("/tmp/drrrk-test"))
        finally:
            if old is None:
                del os.environ["C2C_BASE"]
            else:
                os.environ["C2C_BASE"] = old

    def test_fallback_without_drive(self):
        # 이 컨테이너에는 CloudStorage 가 없으므로 로컬 폴백이어야 한다
        old = os.environ.pop("C2C_BASE", None)
        try:
            p = b.resolve_base_dir()
            self.assertTrue(str(p).endswith("c2c market"))
        finally:
            if old is not None:
                os.environ["C2C_BASE"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
