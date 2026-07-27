#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
번개장터 명품 매물 이미지 수집기 (DRRRK c2c market)

- 대상: 200만원 이상 명품 매물 (브랜드/카테고리 14쌍)
- 카테고리당 매일 최대 40개 신규 매물, 상품당 등록 이미지 전부 (w1197 해상도)
- 폴더 구조: c2c market/<카테고리>/<브랜드_제품명_구매연도>/
- 중복 방지: .state/downloaded_pids.json 에 수집한 pid 기록
- 표준 라이브러리만 사용 (외부 패키지 불필요)
"""

import json
import os
import re
import sys
import time
import csv
import fcntl
import unicodedata
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

BASE_DIR = Path.home() / "bunjang_c2c" / "c2c market"
STATE_DIR = BASE_DIR / ".state"
LOG_DIR = STATE_DIR / "logs"
PID_STATE = STATE_DIR / "downloaded_pids.json"
MASTER_CSV = BASE_DIR / "catalog.csv"
LOCK_FILE = STATE_DIR / ".lock"

PRICE_MIN = 2_000_000
DAILY_LIMIT = int(os.environ.get("C2C_LIMIT", "40"))   # 카테고리당 신규 매물 수
MAX_PAGES = 10                                          # 검색 페이지네이션 상한 (100개/페이지)
REQUEST_DELAY = 0.4                                     # API 호출 간격 (초)
IMAGE_DELAY = 0.15                                      # 이미지 다운로드 간격 (초)
IMAGE_RES = "1197"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (브랜드, 카테고리 라벨, 카테고리 매칭 키워드)
TARGETS = [
    ("샤넬", "가방"), ("샤넬", "신발"),
    ("에르메스", "가방"), ("에르메스", "주얼리"), ("에르메스", "신발"),
    ("디올", "가방"),
    ("롤렉스", "시계"),
    ("까르띠에", "시계"), ("까르띠에", "주얼리"),
    ("예거르쿨트르", "시계"),
    ("오메가", "시계"),
    ("미우미우", "가방"),
    ("파텍필립", "시계"),
    ("반클리프아펠", "주얼리"),
    ("프라다", "가방"),
    ("멀버리", "가방"),
    ("셀린느", "가방"),
]

# 검색 노이즈 제거용: 번개장터 카테고리 경로에 이 단어가 있으면 해당 카테고리로 인정
CATEGORY_KEYWORDS = {
    "가방": ["가방", "백", "지갑/잡화"],
    "신발": ["신발", "슈즈", "스니커즈", "로퍼", "구두", "힐", "샌들", "부츠", "플랫"],
    "시계": ["시계"],
    "주얼리": ["주얼리", "쥬얼리", "귀금속", "반지", "목걸이", "팔찌", "귀걸이", "브로치"],
}

# 브랜드 동의어 (상품명에 하나라도 포함되면 해당 브랜드로 인정)
BRAND_ALIASES = {
    "샤넬": ["샤넬", "chanel"],
    "에르메스": ["에르메스", "hermes"],
    "디올": ["디올", "dior"],
    "롤렉스": ["롤렉스", "rolex"],
    "까르띠에": ["까르띠에", "카르티에", "cartier"],
    "예거르쿨트르": ["예거", "jaeger", "lecoultre"],
    "오메가": ["오메가", "omega"],
    "미우미우": ["미우미우", "miumiu", "miu miu"],
    "파텍필립": ["파텍", "patek"],
    "반클리프아펠": ["반클리프", "반클", "van cleef", "vca"],
    "프라다": ["프라다", "prada"],
    "멀버리": ["멀버리", "mulberry"],
    "셀린느": ["셀린느", "셀린", "celine", "céline"],
}


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_get(url, retries=3, as_json=True):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            return json.loads(data) if as_json else data
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET 실패 ({url}): {last_err}")


def search_products(query, page):
    q = urllib.parse.quote(query)
    url = (f"https://api.bunjang.co.kr/api/1/find_v2.json"
           f"?q={q}&order=date&page={page}&n=100&f_price_min={PRICE_MIN}")
    d = http_get(url)
    return d.get("list", []) or []


def product_detail(pid):
    url = f"https://api.bunjang.co.kr/api/pms/v3/products-detail/{pid}?viewerUid=-1"
    d = http_get(url)
    return (d.get("data") or {}).get("product") or {}


def extract_year(*texts):
    """상품명/설명에서 구매 연도 추출. 못 찾으면 None."""
    blob = " ".join(t for t in texts if t)
    # "2021년 구매", "2021년에 구입", "구매시기 2021", "구매: 2021"
    m = re.search(r"(20[12]\d)\s*년?[가-힣\s]{0,6}(구매|구입|샀)", blob)
    if m:
        return m.group(1)
    m = re.search(r"(구매|구입)[^\d]{0,12}(20[12]\d)", blob)
    if m:
        return m.group(2)
    # "21년 구매" (2자리 연도)
    m = re.search(r"\b([12]\d)\s*년\s*[가-힣\s]{0,4}(구매|구입)", blob)
    if m:
        return "20" + m.group(1)
    return None


def sanitize(name, max_len=70):
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r'[/\\:*?"<>|\n\r\t]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len].strip()


def matches_brand(name, brand):
    low = name.lower().replace(" ", "")
    return any(a.replace(" ", "") in low for a in BRAND_ALIASES[brand])


def matches_category(detail, cat_label):
    cats = detail.get("categories") or []
    names = " ".join(str(c.get("name", "")) for c in cats)
    if not names.strip():
        return True  # 카테고리 정보가 없으면 통과 (과잉 필터 방지)
    return any(k in names for k in CATEGORY_KEYWORDS[cat_label])


def load_state():
    if PID_STATE.exists():
        return set(json.loads(PID_STATE.read_text()))
    return set()


def save_state(pids):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_STATE.write_text(json.dumps(sorted(pids)))


def append_catalog(row):
    new_file = not MASTER_CSV.exists()
    with open(MASTER_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["수집일", "브랜드", "카테고리", "pid", "상품명", "가격",
                        "구매연도", "이미지수", "검수상태", "폴더", "상품URL"])
        w.writerow(row)


def collect_product(pid, brand, cat_label, downloaded):
    detail = product_detail(pid)
    time.sleep(REQUEST_DELAY)
    if not detail:
        return False

    name = detail.get("name", "")
    price = int(detail.get("price") or 0)
    if price < PRICE_MIN:
        return False
    if not matches_brand(name, brand):
        return False
    if not matches_category(detail, cat_label):
        return False

    img_tpl = detail.get("imageUrl") or ""
    img_count = int(detail.get("imageCount") or 0)
    if not img_tpl or img_count == 0:
        return False

    desc = detail.get("description") or ""
    year = extract_year(name, desc)

    # 상품명이 브랜드명으로 시작하면 중복 제거 ("샤넬_샤넬 19백" → "샤넬_19백")
    name_clean = name
    for alias in sorted(BRAND_ALIASES[brand], key=len, reverse=True):
        name_clean = re.sub(rf"^\s*{re.escape(alias)}\s*", "", name_clean, flags=re.IGNORECASE)
    name_clean = name_clean.strip() or name

    folder_name = sanitize(f"{brand}_{name_clean}" + (f"_{year}" if year else ""))
    cat_dir = BASE_DIR / f"{brand}_{cat_label}"
    folder = cat_dir / folder_name
    if folder.exists():
        folder = cat_dir / f"{folder_name}_{pid}"
    folder.mkdir(parents=True, exist_ok=True)

    saved = 0
    for i in range(1, img_count + 1):
        url = img_tpl.replace("{cnt}", str(i)).replace("{res}", IMAGE_RES)
        try:
            data = http_get(url, as_json=False)
            (folder / f"{pid}_{i:02d}.jpg").write_bytes(data)
            saved += 1
        except Exception as e:
            log(f"    이미지 실패 pid={pid} #{i}: {e}")
        time.sleep(IMAGE_DELAY)

    if saved == 0:
        return False

    meta = {
        "pid": pid, "brand": brand, "category": cat_label,
        "name": name, "price": price, "purchase_year": year,
        "image_count": saved,
        "inspection": detail.get("inspectionStatus"),
        "condition": detail.get("condition"),
        "description": desc,
        "product_url": f"https://m.bunjang.co.kr/products/{pid}",
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }
    (folder / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    append_catalog([meta["collected_at"][:10], brand, cat_label, pid, name, price,
                    year or "", saved, meta["inspection"] or "",
                    str(folder.relative_to(BASE_DIR)), meta["product_url"]])
    downloaded.add(pid)
    log(f"    저장: {folder.name} ({saved}장)")
    return True


def run():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # 동시 실행 방지
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("이미 실행 중 — 종료")
        return

    targets = TARGETS[: int(os.environ.get("C2C_CATS", len(TARGETS)))]
    downloaded = load_state()
    log(f"=== 수집 시작 (카테고리 {len(targets)}개, 목표 {DAILY_LIMIT}개/카테고리, "
        f"기존 수집 {len(downloaded)}건) ===")

    total = 0
    for brand, cat_label in targets:
        query = f"{brand} {cat_label}"
        got = 0
        log(f"[{brand} {cat_label}] 검색 시작")
        for page in range(MAX_PAGES):
            if got >= DAILY_LIMIT:
                break
            try:
                items = search_products(query, page)
            except Exception as e:
                log(f"  검색 실패 page={page}: {e}")
                break
            time.sleep(REQUEST_DELAY)
            if not items:
                break
            for item in items:
                if got >= DAILY_LIMIT:
                    break
                pid = str(item.get("pid"))
                if not pid or pid in downloaded:
                    continue
                if int(item.get("price") or 0) < PRICE_MIN:
                    continue
                if item.get("ad"):
                    continue
                if not matches_brand(item.get("name", ""), brand):
                    continue
                try:
                    if collect_product(pid, brand, cat_label, downloaded):
                        got += 1
                except Exception as e:
                    log(f"    상품 실패 pid={pid}: {e}")
        save_state(downloaded)
        total += got
        log(f"[{brand} {cat_label}] 완료: 신규 {got}건")

    log(f"=== 수집 종료: 오늘 총 {total}건 (누적 {len(downloaded)}건) ===")


if __name__ == "__main__":
    run()
