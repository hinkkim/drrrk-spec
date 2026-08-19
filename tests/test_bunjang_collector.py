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


def smudge_border(px, n, color=(70, 55, 40)):
    """테두리 영역(clean_background 가 보는 범위)의 앞 n 픽셀을 어둡게 만든다.

    흰 종이 위에 놓고 찍어 그림자·책상 모서리가 남은 실사를 흉내낸다.
    """
    h, w = len(px), len(px[0])
    t = max(1, min(w, h) // 8)
    marked = 0
    for y in range(h):
        for x in range(w):
            if t <= y < h - t and t <= x < w - t:
                continue
            if marked >= n:
                return px
            px[y][x] = color
            marked += 1
    return px


class TestJewelryBackgroundThreshold(unittest.TestCase):
    """주얼리는 개인 판매자도 흰 종이 위에 놓고 찍어 오탐이 잦다.

    테두리가 거의 완전히 균일한 진짜 누끼만 걸러내도록 기준을 따로 둔다.
    """

    def _px(self, dirty):
        return b.load_bmp_pixels(bmp_bytes(
            smudge_border(solid(32, 32, (246, 246, 246), center=(180, 140, 60)), dirty)))

    def test_border_pixel_count(self):
        # 32x32, t=4 → 테두리 448px. 아래 테스트들의 비율 계산 근거.
        self.assertEqual(32 * 32 - 24 * 24, 448)

    def test_shadowed_white_paper_kept_for_jewelry(self):
        # 448 중 45px 오염 → clean 비율 약 0.90
        px = self._px(45)
        self.assertTrue(b.clean_background(px, b.BG_RATIO))            # 기본 기준: 제외
        self.assertFalse(b.clean_background(px, b.BG_RATIO_BY_CAT["주얼리"]))  # 주얼리: 통과

    def test_true_cutout_still_rejected_for_jewelry(self):
        # 448 중 9px 오염 → clean 비율 약 0.98, 사실상 누끼
        px = self._px(9)
        self.assertTrue(b.clean_background(px, b.BG_RATIO_BY_CAT["주얼리"]))

    def test_threshold_lookup_by_category(self):
        self.assertEqual(b.BG_RATIO_BY_CAT.get("주얼리", b.BG_RATIO), b.BG_RATIO_BY_CAT["주얼리"])
        for cat in ("가방", "시계", "패션잡화", None):
            self.assertEqual(b.BG_RATIO_BY_CAT.get(cat, b.BG_RATIO), b.BG_RATIO)
        self.assertGreater(b.BG_RATIO_BY_CAT["주얼리"], b.BG_RATIO)


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

    def test_wallet_is_fashion_goods_not_bag(self):
        # 번개장터는 지갑을 '가방/지갑' 상위 노드 아래 두지만, 잡화로 분류해야 한다
        allowed = ("가방", "패션잡화")
        self.assertEqual(
            b.classify_category(self._detail("가방/지갑", "여성지갑", "장지갑"), allowed),
            "패션잡화")
        self.assertEqual(
            b.classify_category(self._detail("가방/지갑", "남성지갑", "카드케이스"), allowed),
            "패션잡화")

    def test_half_wallet_not_mistaken_for_ring(self):
        # '반지갑' 은 '반지' 를 포함한다 — 잡화 판정이 주얼리보다 앞서야 한다
        self.assertEqual(
            b.classify_category(self._detail("가방/지갑", "남성지갑", "반지갑"),
                                ("가방", "패션잡화", "주얼리")),
            "패션잡화")

    def test_bag_under_same_parent_still_bag(self):
        # 같은 '가방/지갑' 상위 노드지만 말단이 가방이면 가방이어야 한다
        self.assertEqual(
            b.classify_category(self._detail("가방/지갑", "여성가방", "숄더백"),
                                ("가방", "패션잡화")),
            "가방")

    def test_belt_and_shoes(self):
        allowed = ("가방", "패션잡화")
        for leaf in ("벨트", "스니커즈", "구두", "샌들", "플랫슈즈", "로퍼", "키링"):
            self.assertEqual(
                b.classify_category(self._detail("패션잡화", leaf), allowed),
                "패션잡화", leaf)

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

    def test_category_queries_are_known_categories(self):
        for cat, terms in b.CATEGORY_QUERIES.items():
            self.assertIn(cat, b.CATEGORY_KEYWORDS, f"{cat} 는 알 수 없는 카테고리")
            self.assertTrue(terms, f"{cat} 검색어가 비어 있다")

    def test_every_category_is_ordered(self):
        # 새 카테고리를 추가하고 CATEGORY_ORDER 에 넣는 걸 잊으면 영영 분류되지 않는다
        self.assertEqual(set(b.CATEGORY_ORDER), set(b.CATEGORY_KEYWORDS))

    def test_fashion_goods_precede_jewelry(self):
        # '반지갑' 오분류 방지 — 순서가 뒤집히면 지갑이 주얼리로 간다
        order = list(b.CATEGORY_ORDER)
        self.assertLess(order.index("패션잡화"), order.index("주얼리"))
        self.assertEqual(order[-1], "가방", "가방은 가장 넓어서 맨 뒤여야 한다")

    def test_brands_allowing_fashion_goods(self):
        # 잡화 수집 대상 브랜드가 실제로 존재해야 한다
        cats = [c for _, allowed in b.BRANDS for c in allowed]
        self.assertGreaterEqual(cats.count("패션잡화"), 10)


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


class TestHttpRetry(unittest.TestCase):
    """본문 수신 중 끊기는 오류도 재시도 대상이어야 한다.

    resp.read() 중 발생하는 read timeout 은 TimeoutError 로 올라오고
    URLError 로 감싸이지 않는다. 이걸 안 잡으면 이미지 한 장이
    재시도 없이 그대로 유실된다(실제 수집 로그에서 발생).
    """

    URL = "https://media.example.com/product/1_1.jpg"

    def _run(self, side_effect):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            exc = side_effect(calls["n"])
            if exc:
                raise exc

            class Resp:
                headers = {"Content-Type": "image/jpeg"}

                def read(self):
                    return b"\xff\xd8\xffdata"

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return Resp()

        with mock.patch.object(b, "robots_allows", return_value=True), \
             mock.patch.object(b.urllib.request, "urlopen", fake_urlopen), \
             mock.patch.object(b.time, "sleep", lambda s: None):
            body, ctype = b.http_get(self.URL)
        return body, calls["n"]

    def test_read_timeout_is_retried(self):
        body, n = self._run(lambda i: TimeoutError("The read operation timed out")
                            if i < 3 else None)
        self.assertEqual(body[:3], b"\xff\xd8\xff")
        self.assertEqual(n, 3)

    def test_connection_reset_is_retried(self):
        body, n = self._run(lambda i: ConnectionResetError("reset") if i < 2 else None)
        self.assertEqual(body[:3], b"\xff\xd8\xff")
        self.assertEqual(n, 2)

    def test_incomplete_read_is_retried(self):
        body, n = self._run(lambda i: b.http.client.IncompleteRead(b"", 10)
                            if i < 2 else None)
        self.assertEqual(body[:3], b"\xff\xd8\xff")
        self.assertEqual(n, 2)

    def test_persistent_timeout_exhausts_retries(self):
        with self.assertRaises(RuntimeError):
            self._run(lambda i: TimeoutError("timed out"))


class TestCategoryHarvest(unittest.TestCase):
    """브랜드명만 검색하면 최신순 상위를 가방이 채워 잡화가 한 건도 안 들어온다.

    카테고리 검색어로 최소 물량을 먼저 확보하는 1차 패스가 이를 막아야 한다.
    네트워크 없이 search_products / collect_product 를 가짜로 바꿔 검증한다.
    """

    BRAND = "구찌"

    def setUp(self):
        # 브랜드 전체 검색은 가방만, 카테고리 검색은 해당 잡화/주얼리만 돌려준다
        self.catalog = {}
        self.feeds = {}

        def add(query, prefix, cat, name, n=40):
            items = []
            for i in range(n):
                pid = f"{prefix}{i:03d}"
                self.catalog[pid] = cat
                items.append({"pid": pid, "name": f"{self.BRAND} {name} {i}",
                              "price": "3,000,000"})
            self.feeds[query] = items

        add(self.BRAND, "1", "가방", "GG마몽 숄더백")
        add(f"{self.BRAND} 지갑", "2", "패션잡화", "마몽 장지갑")
        add(f"{self.BRAND} 벨트", "3", "패션잡화", "인터로킹 벨트")
        add(f"{self.BRAND} 목걸이", "4", "주얼리", "인터로킹 목걸이")

        self.collected = []

        def fake_search(query, page):
            return self.feeds.get(query, [])[page * 100:(page + 1) * 100]

        def fake_collect(pid, brand, allowed_cats, downloaded, rejects, res_state):
            cat = self.catalog.get(pid)
            if cat not in allowed_cats:
                rejects[pid] = "2026-08-06"
                return False, "카테고리 불일치"
            downloaded.add(pid)
            self.collected.append((pid, cat))
            return cat, None

        self.patches = [
            mock.patch.object(b, "search_products", fake_search),
            mock.patch.object(b, "collect_product", fake_collect),
            mock.patch.object(b.time, "sleep", lambda s: None),
            mock.patch.object(b, "log", lambda m: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _run(self, allowed=("가방", "패션잡화", "주얼리"), total=0):
        state = {"downloaded": set(), "rejects": {},
                 "res_state": {"res": None}, "today": "2026-08-06"}
        ctx = b.new_ctx(total)
        b.collect_brand(self.BRAND, allowed, ctx, state)
        return ctx

    def test_fashion_goods_are_guaranteed(self):
        ctx = self._run()
        self.assertGreaterEqual(ctx["cat_got"].get("패션잡화", 0), b.CATEGORY_MIN,
                                f"잡화가 확보되지 않았다: {ctx['cat_got']}")
        self.assertGreaterEqual(ctx["cat_got"].get("주얼리", 0), b.CATEGORY_MIN)

    def test_brand_wide_search_alone_would_miss_them(self):
        # 1차 패스가 없으면(=카테고리 검색어 없음) 전량 가방이 된다 — 회귀 대비 대조군
        with mock.patch.object(b, "CATEGORY_QUERIES", {}):
            ctx = self._run()
        self.assertEqual(ctx["cat_got"], {"가방": b.DAILY_LIMIT})

    def test_exact_mix_and_daily_limit(self):
        ctx = self._run()
        self.assertEqual(ctx["got"], b.DAILY_LIMIT)
        self.assertEqual(sum(ctx["cat_got"].values()), b.DAILY_LIMIT)
        # 잡화·주얼리를 최소치만 채우고 나머지는 브랜드 전체 검색(가방)이 메운다
        self.assertEqual(ctx["cat_got"]["패션잡화"], b.CATEGORY_MIN)
        self.assertEqual(ctx["cat_got"]["주얼리"], b.CATEGORY_MIN)
        self.assertEqual(ctx["cat_got"]["가방"],
                         b.DAILY_LIMIT - 2 * b.CATEGORY_MIN)

    def test_disallowed_category_is_not_harvested(self):
        # 주얼리를 허용하지 않는 브랜드는 주얼리 검색 자체를 돌지 않는다
        ctx = self._run(allowed=("가방", "패션잡화"))
        self.assertNotIn("주얼리", ctx["cat_got"])
        self.assertEqual(ctx["cat_got"]["패션잡화"], b.CATEGORY_MIN)

    def test_total_limit_stops_run(self):
        ctx = self._run(total=b.TOTAL_LIMIT - 3)
        self.assertTrue(ctx["stop"])
        self.assertEqual(ctx["got"], 3)

    def test_no_duplicate_pids(self):
        ctx = self._run()
        pids = [p for p, _ in self.collected]
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(pids), ctx["got"])


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
