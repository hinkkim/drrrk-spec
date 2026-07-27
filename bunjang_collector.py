#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
번개장터 명품 매물 이미지 수집기 (DRRRK c2c market)

- 대상: 200만원 이상 명품 매물 (브랜드/카테고리 17쌍, 브랜드 13종)
- 카테고리당 매일 최대 40개 신규 매물, 상품당 이미지 상한 적용
- 폴더 구조: c2c market/<브랜드_카테고리>/<브랜드_제품명_구매연도>/
- 중복 방지: .state/downloaded_pids.json (수집 성공) + .state/rejected_pids.json (거부)
- 표준 라이브러리만 사용 (외부 패키지 불필요)

수집 원칙 (준수 사항)
  1. robots.txt 를 매 실행 시 확인하고, 금지된 경로는 요청하지 않는다.
  2. 429 응답 시 Retry-After 를 존중하고, 4xx 는 재시도하지 않는다.
  3. 상품 설명에서 개인정보(전화번호·이메일·메신저ID·계좌번호·링크)를 마스킹한 뒤 저장한다.
  4. 상품당 이미지 수와 실행당 총 수집량에 상한을 둔다.
  5. 판매자 식별정보(uid·닉네임·연락처)는 저장하지 않는다.

환경변수
  C2C_LIMIT      카테고리당 신규 매물 수 (기본 40)
  C2C_CATS       처리할 TARGETS 개수 (기본 전체)
  C2C_IMG_MAX    상품당 이미지 상한 (기본 5, 0=무제한)
  C2C_TOTAL_MAX  실행당 총 신규 매물 상한 (기본 200, 0=무제한)
  C2C_ROBOTS     robots.txt 준수 (기본 1, 0=무시 — 권장하지 않음)
"""

import json
import os
import re
import time
import csv
import fcntl
import random
import unicodedata
import urllib.request
import urllib.error
import urllib.parse
import urllib.robotparser
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path.home() / "bunjang_c2c" / "c2c market"
STATE_DIR = BASE_DIR / ".state"
LOG_DIR = STATE_DIR / "logs"
PID_STATE = STATE_DIR / "downloaded_pids.json"
REJECT_STATE = STATE_DIR / "rejected_pids.json"
MASTER_CSV = BASE_DIR / "catalog.csv"
LOCK_FILE = STATE_DIR / ".lock"

PRICE_MIN = 2_000_000
DAILY_LIMIT = int(os.environ.get("C2C_LIMIT", "40"))    # 카테고리당 신규 매물 수
TOTAL_LIMIT = int(os.environ.get("C2C_TOTAL_MAX", "200"))  # 실행당 총 상한 (0=무제한)
IMAGE_MAX = int(os.environ.get("C2C_IMG_MAX", "5"))     # 상품당 이미지 상한 (0=무제한)
ROBOTS_ENFORCE = os.environ.get("C2C_ROBOTS", "1") != "0"
MAX_PAGES = 10                                          # 검색 페이지네이션 상한 (100개/페이지)
REQUEST_DELAY = 0.4                                     # API 호출 간격 (초)
IMAGE_DELAY = 0.15                                      # 이미지 다운로드 간격 (초)
REJECT_TTL_DAYS = 30                                    # 거부 pid 재확인 주기

# 번개장터가 지원하는 리사이즈 폭. 앞에서부터 시도하고 유효한 이미지가 나오면 고정한다.
# (기존 코드의 1197 은 지원 목록에 없어 에러 응답이 .jpg 로 저장되던 원인)
IMAGE_RES_CANDIDATES = ["1100", "800", "600", "425"]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (브랜드, 카테고리 라벨)
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

# 개인정보 마스킹 패턴. 순서 중요 — 전화번호를 계좌번호보다 먼저 처리한다.
PII_PATTERNS = [
    (re.compile(r"01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}"), "[전화번호]"),
    (re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}"), "[전화번호]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[이메일]"),
    (re.compile(r"(카톡|카카오톡|오픈채팅|오카|kakao|kakaotalk|텔레|telegram)"
                r"\s*(아이디|id)?\s*[:：]?\s*[\w.-]{2,}", re.I), "[메신저ID]"),
    (re.compile(r"(https?://|www\.)\S+", re.I), "[링크]"),
    # 3개 숫자 그룹이 하이픈으로 이어진 형태만 계좌번호로 본다 (시계 레퍼런스 오탐 방지)
    (re.compile(r"\b\d{3,6}-\d{2,6}-\d{2,7}\b"), "[계좌번호]"),
]

_robots_cache = {}


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def robots_allows(url):
    """robots.txt 확인. 조회 실패 시에는 보수적으로 허용하지 않는다."""
    if not ROBOTS_ENFORCE:
        return True
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            rp.read()
        except Exception as e:
            log(f"  robots.txt 조회 실패 ({origin}): {e} — 해당 호스트 수집 보류")
            rp = False
        _robots_cache[origin] = rp
    if rp is False:
        return False
    return rp.can_fetch(UA, url)


def http_get(url, retries=3):
    """(본문 bytes, Content-Type) 반환. 4xx 는 재시도하지 않고, 429 는 Retry-After 를 따른다."""
    if not robots_allows(url):
        raise PermissionError(f"robots.txt 가 허용하지 않는 경로: {url}")

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60
                try:
                    wait = max(1, min(300, int(e.headers.get("Retry-After") or 60)))
                except (TypeError, ValueError):
                    pass
                log(f"  429 요청 제한 — {wait}초 대기 후 재시도")
                time.sleep(wait)
                last_err = e
                continue
            if 400 <= e.code < 500:
                raise RuntimeError(f"GET {e.code} ({url})") from e
            last_err = e
        except urllib.error.URLError as e:
            last_err = e
        time.sleep(2 * (attempt + 1) + random.uniform(0, 0.5))
    raise RuntimeError(f"GET 실패 ({url}): {last_err}")


def http_json(url):
    data, _ = http_get(url)
    return json.loads(data)


def sniff_image(data):
    """매직바이트로 실제 이미지 포맷 판별. 이미지가 아니면 None."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def search_products(query, page):
    q = urllib.parse.quote(query)
    url = (f"https://api.bunjang.co.kr/api/1/find_v2.json"
           f"?q={q}&order=date&page={page}&n=100&f_price_min={PRICE_MIN}")
    d = http_json(url)
    return d.get("list", []) or []


def product_detail(pid):
    url = f"https://api.bunjang.co.kr/api/pms/v3/products-detail/{pid}?viewerUid=-1"
    d = http_json(url)
    return (d.get("data") or {}).get("product") or {}


def to_won(value):
    """가격을 정수로. '2,500,000' 같은 문자열도 처리한다."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0


def extract_year(*texts):
    """상품명/설명에서 구매 연도 추출. 못 찾으면 None."""
    blob = " ".join(t for t in texts if t)
    # "2021년 구매", "2021년에 구입", "구매시기 2021", "구매: 2021"
    m = re.search(r"(19[89]\d|20[0-2]\d)\s*년?[가-힣\s]{0,6}(구매|구입|샀)", blob)
    if m:
        return m.group(1)
    m = re.search(r"(구매|구입)[^\d]{0,12}(19[89]\d|20[0-2]\d)", blob)
    if m:
        return m.group(2)
    # "21년 구매" / "샤넬19년 구매" (2자리 연도, 앞에 한글이 붙어도 인식)
    m = re.search(r"(?<!\d)([0-2]\d)\s*년\s*[가-힣\s]{0,4}(구매|구입)", blob)
    if m:
        return "20" + m.group(1)
    return None


def redact_pii(text):
    """상품 설명에서 개인정보를 마스킹한다."""
    if not text:
        return ""
    out = text
    for pattern, repl in PII_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def norm(text):
    return unicodedata.normalize("NFC", text or "")


def sanitize(name, max_len=70):
    name = norm(name)
    name = re.sub(r'[/\\:*?"<>|\n\r\t]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len].strip()


def matches_brand(name, brand):
    low = norm(name).lower().replace(" ", "")
    return any(norm(a).lower().replace(" ", "") in low for a in BRAND_ALIASES[brand])


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
    PID_STATE.write_text(json.dumps(sorted(pids)))


def load_rejects():
    """거부 pid → 거부일. TTL 지난 항목은 버려서 재확인 기회를 준다."""
    if not REJECT_STATE.exists():
        return {}
    try:
        raw = json.loads(REJECT_STATE.read_text())
    except (ValueError, OSError):
        return {}
    cutoff = (datetime.now() - timedelta(days=REJECT_TTL_DAYS)).strftime("%Y-%m-%d")
    return {pid: day for pid, day in raw.items() if day >= cutoff}


def save_rejects(rejects):
    REJECT_STATE.write_text(json.dumps(rejects, sort_keys=True))


def append_catalog(row):
    new_file = not MASTER_CSV.exists()
    with open(MASTER_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["수집일", "브랜드", "카테고리", "pid", "상품명", "가격",
                        "구매연도", "이미지수", "검수상태", "폴더", "상품URL"])
        w.writerow(row)


def download_images(img_tpl, img_count, pid, folder, res_state):
    """이미지를 내려받아 실제 포맷에 맞는 확장자로 저장. 저장한 장수를 반환."""
    limit = img_count if IMAGE_MAX == 0 else min(img_count, IMAGE_MAX)
    saved = 0
    for i in range(1, limit + 1):
        # 유효 해상도가 확정되기 전에는 후보를 순서대로 시도한다.
        candidates = [res_state["res"]] if res_state["res"] else IMAGE_RES_CANDIDATES
        for res in candidates:
            url = img_tpl.replace("{cnt}", str(i)).replace("{res}", res)
            try:
                data, ctype = http_get(url)
            except Exception as e:
                log(f"    이미지 실패 pid={pid} #{i} res={res}: {e}")
                continue

            fmt = sniff_image(data)
            if not fmt:
                head = data[:60].decode("utf-8", "replace").replace("\n", " ")
                log(f"    이미지 아님 pid={pid} #{i} res={res} "
                    f"(content-type={ctype or '?'}, {len(data)}B, 시작: {head!r})")
                continue

            (folder / f"{pid}_{i:02d}.{fmt}").write_bytes(data)
            saved += 1
            if not res_state["res"]:
                res_state["res"] = res
                log(f"    유효 해상도 확정: w{res} ({fmt})")
            break
        time.sleep(IMAGE_DELAY)
    return saved


def collect_product(pid, brand, cat_label, downloaded, rejects, res_state):
    detail = product_detail(pid)
    time.sleep(REQUEST_DELAY)
    today = datetime.now().strftime("%Y-%m-%d")

    def reject(reason):
        rejects[pid] = today
        return False, reason

    if not detail:
        return reject("상세 없음")

    name = detail.get("name", "")
    price = to_won(detail.get("price"))
    if price < PRICE_MIN:
        return reject("가격 미달")
    if not matches_brand(name, brand):
        return reject("브랜드 불일치")
    if not matches_category(detail, cat_label):
        return reject("카테고리 불일치")

    img_tpl = detail.get("imageUrl") or ""
    img_count = int(detail.get("imageCount") or 0)
    if not img_tpl or img_count == 0:
        return reject("이미지 없음")

    year = extract_year(name, detail.get("description") or "")
    desc = redact_pii(detail.get("description") or "")

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

    saved = download_images(img_tpl, img_count, pid, folder, res_state)
    if saved == 0:
        return reject("이미지 저장 실패")

    meta = {
        "pid": pid, "brand": brand, "category": cat_label,
        "name": name, "price": price, "purchase_year": year,
        "image_count": saved, "image_total": img_count,
        "inspection": detail.get("inspectionStatus"),
        "condition": detail.get("condition"),
        "description_redacted": desc,
        "product_url": f"https://m.bunjang.co.kr/products/{pid}",
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }
    (folder / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    append_catalog([meta["collected_at"][:10], brand, cat_label, pid, name, price,
                    year or "", saved, meta["inspection"] or "",
                    str(folder.relative_to(BASE_DIR)), meta["product_url"]])
    downloaded.add(pid)
    log(f"    저장: {folder.name} ({saved}/{img_count}장)")
    return True, None


def run():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 동시 실행 방지
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("이미 실행 중 — 종료")
        return

    if not ROBOTS_ENFORCE:
        log("경고: C2C_ROBOTS=0 — robots.txt 를 무시하도록 설정되어 있습니다")
    elif not robots_allows("https://api.bunjang.co.kr/api/1/find_v2.json"):
        log("robots.txt 가 검색 API 수집을 허용하지 않습니다 — 수집을 중단합니다")
        return

    targets = TARGETS[: int(os.environ.get("C2C_CATS", len(TARGETS)))]
    downloaded = load_state()
    rejects = load_rejects()
    res_state = {"res": None}   # 유효 이미지 해상도 (첫 성공 시 확정)

    log(f"=== 수집 시작 (카테고리 {len(targets)}개, 목표 {DAILY_LIMIT}개/카테고리, "
        f"이미지 상한 {IMAGE_MAX or '무제한'}장, 기존 수집 {len(downloaded)}건, "
        f"거부 캐시 {len(rejects)}건) ===")

    total = 0
    stop = False
    for brand, cat_label in targets:
        if stop:
            break
        query = f"{brand} {cat_label}"
        got = 0
        skipped = 0
        log(f"[{brand} {cat_label}] 검색 시작")
        for page in range(MAX_PAGES):
            if got >= DAILY_LIMIT or stop:
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
                if TOTAL_LIMIT and total + got >= TOTAL_LIMIT:
                    log(f"  실행당 총 상한 {TOTAL_LIMIT}건 도달 — 수집 종료")
                    stop = True
                    break
                pid = str(item.get("pid"))
                if not pid or pid in downloaded:
                    continue
                if pid in rejects:      # 이전에 거부된 매물은 상세 API를 부르지 않는다
                    skipped += 1
                    continue
                if to_won(item.get("price")) < PRICE_MIN:
                    continue
                if item.get("ad"):
                    continue
                if not matches_brand(item.get("name", ""), brand):
                    continue
                try:
                    ok, reason = collect_product(
                        pid, brand, cat_label, downloaded, rejects, res_state)
                    if ok:
                        got += 1
                    elif reason:
                        log(f"    건너뜀 pid={pid}: {reason}")
                except Exception as e:
                    log(f"    상품 실패 pid={pid}: {e}")
        save_state(downloaded)
        save_rejects(rejects)
        total += got
        log(f"[{brand} {cat_label}] 완료: 신규 {got}건 (거부 캐시로 상세조회 생략 {skipped}건)")

    log(f"=== 수집 종료: 오늘 총 {total}건 (누적 {len(downloaded)}건, "
        f"거부 캐시 {len(rejects)}건) ===")


if __name__ == "__main__":
    run()
