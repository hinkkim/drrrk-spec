#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bunjang_collector 순수 함수 테스트 (네트워크 호출 없음)

실행: python3 -m unittest discover -s tests -v
"""

import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bunjang_collector as b  # noqa: E402


class TestPriceParsing(unittest.TestCase):
    """기존 코드에서 콤마 포함 문자열이 ValueError 로 매물을 잃던 문제."""

    def test_plain_and_formatted(self):
        self.assertEqual(b.to_won("2500000"), 2_500_000)
        self.assertEqual(b.to_won("2,500,000"), 2_500_000)
        self.assertEqual(b.to_won("2,500,000원"), 2_500_000)

    def test_none_and_numeric(self):
        self.assertEqual(b.to_won(None), 0)
        self.assertEqual(b.to_won(3_000_000), 3_000_000)


class TestImageSniffing(unittest.TestCase):
    """확장자만 .jpg 로 붙여 저장하던 탓에 미리보기가 안 되던 문제."""

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
    """개인정보보호법 대응 — 설명 원문을 그대로 저장하지 않는다."""

    def test_masks_contacts(self):
        self.assertEqual(b.redact_pii("연락처 010-1234-5678 로 주세요"),
                         "연락처 [전화번호] 로 주세요")
        self.assertEqual(b.redact_pii("01012345678"), "[전화번호]")
        self.assertEqual(b.redact_pii("메일 abc.d@naver.com"), "메일 [이메일]")
        self.assertEqual(b.redact_pii("카톡 hong_gil2"), "[메신저ID]")
        self.assertEqual(b.redact_pii("https://open.kakao.com/o/abc 참고"), "[링크] 참고")
        self.assertEqual(b.redact_pii("국민 123456-01-234567 입금"), "국민 [계좌번호] 입금")

    def test_does_not_over_redact(self):
        # 시계 레퍼런스와 가격 표기는 감정 데이터라 보존되어야 한다
        self.assertEqual(b.redact_pii("롤렉스 116610LN 풀세트"), "롤렉스 116610LN 풀세트")
        self.assertEqual(b.redact_pii("가격 2,500,000원"), "가격 2,500,000원")

    def test_empty(self):
        self.assertEqual(b.redact_pii(""), "")
        self.assertEqual(b.redact_pii(None), "")


class TestYearExtraction(unittest.TestCase):
    def test_four_digit(self):
        self.assertEqual(b.extract_year("2021년 구매"), "2021")
        self.assertEqual(b.extract_year("구매 2018"), "2018")

    def test_pre_2010_and_vintage(self):
        self.assertEqual(b.extract_year("2009년 구매"), "2009")
        self.assertEqual(b.extract_year("1998년 구입"), "1998")

    def test_two_digit_with_adjacent_hangul(self):
        self.assertEqual(b.extract_year("19년 구매"), "2019")
        self.assertEqual(b.extract_year("샤넬19년 구매"), "2019")

    def test_no_match(self):
        self.assertIsNone(b.extract_year("정품 보증서 있습니다"))


class TestBrandMatching(unittest.TestCase):
    def test_unicode_normalization(self):
        nfc = "Céline 클래식백"
        self.assertTrue(b.matches_brand(nfc, "셀린느"))
        self.assertTrue(b.matches_brand(unicodedata.normalize("NFD", nfc), "셀린느"))

    def test_alias_and_spacing(self):
        self.assertTrue(b.matches_brand("VAN CLEEF 알함브라", "반클리프아펠"))
        self.assertFalse(b.matches_brand("구찌 마몬트", "샤넬"))


class TestCategoryMatching(unittest.TestCase):
    def test_mismatch_rejected(self):
        self.assertFalse(b.matches_category({"categories": [{"name": "가방"}]}, "시계"))

    def test_match_accepted(self):
        self.assertTrue(b.matches_category({"categories": [{"name": "명품시계"}]}, "시계"))

    def test_missing_category_passes(self):
        self.assertTrue(b.matches_category({}, "시계"))


class TestConfigConsistency(unittest.TestCase):
    def test_targets_have_definitions(self):
        self.assertEqual(len(b.TARGETS), 17)
        for brand, cat in b.TARGETS:
            self.assertIn(brand, b.BRAND_ALIASES, f"{brand} alias 누락")
            self.assertIn(cat, b.CATEGORY_KEYWORDS, f"{cat} 키워드 누락")

    def test_docstring_matches_targets(self):
        self.assertIn("17쌍", b.__doc__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
