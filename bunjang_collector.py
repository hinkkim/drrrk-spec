#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
번개장터 명품 매물 이미지 수집기 (DRRRK c2c market)

- 대상: 국내 거래 상위 명품 브랜드 15개, 200만원 이상 매물
- 브랜드당 매일 최대 10개 신규 매물 (매일 11:00, launchd com.drrrk.c2c-collector)
- 상품당 이미지 최소 2장 ~ 최대 10장. 실제 포맷대로 확장자를 붙여 저장하고
  webp 는 jpg 로 변환해 macOS 미리보기(Quick Look)에서 바로 선별 가능하게 한다.
- 저장 위치: 구글드라이브 데스크톱 동기화 폴더 내 '드르륵' (자동 탐지, C2C_BASE 로 재지정)
- 상태 파일(.state)은 Drive 동기화 경합을 피해 로컬(~/bunjang_c2c/.state)에 둔다.
- 표준 라이브러리 + macOS 내장 도구(sips, osascript)만 사용. 외부 패키지 불필요.

수집 제외 원칙 — 중고명품 판매 업체 매물을 걸러내고 개인 판매자 실사용 사진만 남긴다
  1. 업체 게시글: 매입/위탁/매장 운영/피팅 가능/사업자/오픈채팅 등 업체 신호 문구,
     API 의 프로샵 플래그가 있으면 매물 전체를 수집하지 않는다.
  2. 인물이 포함된 사진: macOS Vision 프레임워크(얼굴/사람 감지)로 이미지 단위 제외.
  3. 배경이 희거나 회색으로 깨끗한 사진(스튜디오/누끼): 테두리 픽셀 분석으로 제외.
  4. 유효 이미지가 2장 미만이면 매물 자체를 수집하지 않는다.

준수 사항
  - robots.txt 를 매 실행 시 확인하고, 금지된 경로는 요청하지 않는다.
  - 429 응답 시 Retry-After 를 존중하고, 4xx 는 재시도하지 않는다.
  - 상품 설명의 개인정보(전화번호·이메일·메신저ID·계좌번호·링크)는 마스킹 후 저장한다.
  - 판매자 식별정보는 저장하지 않는다.

환경변수
  C2C_LIMIT      브랜드당 신규 매물 수 (기본 10)
  C2C_BRANDS     처리할 브랜드 수 (기본 전체 15)
  C2C_TOTAL_MAX  실행당 총 신규 매물 상한 (기본 150, 0=무제한)
  C2C_IMG_MIN    상품당 유효 이미지 최소 (기본 2, 미달 시 매물 제외)
  C2C_IMG_MAX    상품당 이미지 상한 (기본 10)
  C2C_BASE       저장 루트 직접 지정 (기본: 구글드라이브 '드르륵/c2c market' 자동 탐지)
  C2C_VISION     인물 감지 사용 (기본 1, 0=끔)
  C2C_ROBOTS     robots.txt 준수 (기본 1, 0=무시 — 권장하지 않음)
"""

import json
import os
import re
import shutil
import subprocess
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


def resolve_base_dir():
    """저장 루트. 구글드라이브 데스크톱 동기화 경로를 자동 탐지한다."""
    env = os.environ.get("C2C_BASE")
    if env:
        return Path(env).expanduser()
    cloud = Path.home() / "Library" / "CloudStorage"
    for drive_name in ("My Drive", "내 드라이브"):
        for p in sorted(cloud.glob(f"GoogleDrive-*/{drive_name}")):
            return p / "드르륵" / "c2c market"
    return Path.home() / "bunjang_c2c" / "c2c market"


BASE_DIR = resolve_base_dir()
STATE_DIR = Path.home() / "bunjang_c2c" / ".state"   # Drive 밖 로컬 고정 (flock/동기화 경합 회피)
LOG_DIR = STATE_DIR / "logs"
TMP_DIR = STATE_DIR / "tmp"
PID_STATE = STATE_DIR / "downloaded_pids.json"
REJECT_STATE = STATE_DIR / "rejected_pids.json"
MASTER_CSV = BASE_DIR / "catalog.csv"
LOCK_FILE = STATE_DIR / ".lock"

PRICE_MIN = 2_000_000
DAILY_LIMIT = int(os.environ.get("C2C_LIMIT", "10"))       # 브랜드당 신규 매물 수
TOTAL_LIMIT = int(os.environ.get("C2C_TOTAL_MAX", "150"))  # 실행당 총 상한 (0=무제한)
IMAGE_MIN = int(os.environ.get("C2C_IMG_MIN", "2"))        # 미달 시 매물 제외
IMAGE_MAX = int(os.environ.get("C2C_IMG_MAX", "10"))
VISION_ENABLE = os.environ.get("C2C_VISION", "1") != "0"
ROBOTS_ENFORCE = os.environ.get("C2C_ROBOTS", "1") != "0"
MAX_PAGES = 10                                             # 검색 페이지네이션 상한 (100개/페이지)
REQUEST_DELAY = 0.4                                        # API 호출 간격 (초)
IMAGE_DELAY = 0.15                                         # 이미지 다운로드 간격 (초)
REJECT_TTL_DAYS = 30                                       # 거부 pid 재확인 주기

# 번개장터가 지원하는 리사이즈 폭. 앞에서부터 시도하고 유효한 이미지가 나오면 고정한다.
IMAGE_RES_CANDIDATES = ["1100", "800", "600", "425"]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 국내 거래 상위 15개 브랜드와 브랜드별 허용 카테고리.
# 에르메스·샤넬·디올·루이비통·롤렉스·프라다는 고정 포함.
BRANDS = [
    ("에르메스", ("가방", "패션잡화", "주얼리")),
    ("샤넬", ("가방", "패션잡화", "주얼리")),
    ("루이비통", ("가방", "패션잡화")),
    ("디올", ("가방", "패션잡화", "주얼리")),
    ("프라다", ("가방", "패션잡화")),
    ("구찌", ("가방", "패션잡화", "주얼리")),
    ("셀린느", ("가방", "패션잡화")),
    ("생로랑", ("가방", "패션잡화")),
    ("보테가베네타", ("가방", "패션잡화")),
    ("버버리", ("가방", "패션잡화")),
    ("미우미우", ("가방", "패션잡화")),
    ("롤렉스", ("시계",)),
    ("오메가", ("시계",)),
    ("까르띠에", ("시계", "주얼리")),
    ("반클리프아펠", ("주얼리",)),
]

# 번개장터 카테고리 경로에 이 단어가 있으면 해당 카테고리로 분류
CATEGORY_KEYWORDS = {
    "가방": ["가방", "백", "지갑", "파우치", "클러치", "토트", "숄더", "크로스"],
    "시계": ["시계", "워치"],
    "패션잡화": ["신발", "슈즈", "스니커즈", "로퍼", "구두", "힐", "샌들", "부츠",
               "플랫", "벨트", "스카프", "머플러", "모자", "선글라스"],
    "주얼리": ["주얼리", "쥬얼리", "귀금속", "반지", "목걸이", "네크리스", "팔찌",
             "브레이슬릿", "귀걸이", "이어링", "브로치", "펜던트"],
}

# 브랜드 동의어 (상품명에 하나라도 포함되면 해당 브랜드로 인정)
BRAND_ALIASES = {
    "에르메스": ["에르메스", "hermes"],
    "샤넬": ["샤넬", "chanel"],
    "루이비통": ["루이비통", "루이 비통", "louis vuitton", "louisvuitton"],
    "디올": ["디올", "dior"],
    "프라다": ["프라다", "prada"],
    "구찌": ["구찌", "gucci"],
    "셀린느": ["셀린느", "셀린", "celine", "céline"],
    "생로랑": ["생로랑", "입생로랑", "saint laurent", "ysl"],
    "보테가베네타": ["보테가", "bottega"],
    "버버리": ["버버리", "burberry"],
    "미우미우": ["미우미우", "miumiu", "miu miu"],
    "롤렉스": ["롤렉스", "rolex"],
    "오메가": ["오메가", "omega"],
    "까르띠에": ["까르띠에", "카르티에", "cartier"],
    "반클리프아펠": ["반클리프", "반클", "van cleef", "vca"],
}

# 업체(중고명품 판매/매입 업자) 신호 문구. 하나라도 걸리면 매물 전체 제외.
# 개인 판매자가 흔히 쓰는 표현("백화점 매장에서 구매", "2021년 구매입니다")과
# 겹치지 않도록 문맥을 좁혀 둔 패턴이다.
DEALER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"매입(?!니다)",                 # "명품매입", "매입 전문" — "구매입니다"는 제외
    r"삽니다", r"위탁", r"도매",
    r"(매장|쇼룸|스토어|부티크).{0,10}(운영|방문|오셔|오시|위치)",
    r"직접\s*오셔서", r"피팅\s*도?\s*가능",
    r"사업자", r"세금\s*계산서", r"현금\s*영수증",
    r"오픈\s*(채팅|톡)",
    r"정품만\s*(판매|취급)", r"100\s*%\s*정품.{0,12}(판매|취급)",
    r"전문\s*(매입|판매|취급)", r"명품\s*(샵|샾|스토어|부티크)",
    r"선입금", r"당일\s*(매입|현금)",
]]

# 판매자 프로필의 업체 플래그로 추정되는 키 (API 스펙 변동 대비 복수 후보)
DEALER_FLAG_KEYS = ("proshop", "proShop", "pro_shop", "bizseller", "bizSeller", "isProshop")

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

# macOS Vision 얼굴/사람 감지 (osascript JXA). 감지 수를 stdout 으로 반환.
VISION_JS = r"""
ObjC.import('Foundation');
ObjC.import('Vision');
function run(argv) {
  try {
    var url = $.NSURL.fileURLWithPath(argv[0]);
    var handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $.NSDictionary.dictionary);
    var total = 0;
    var reqs = [$.VNDetectFaceRectanglesRequest.alloc.init,
                $.VNDetectHumanRectanglesRequest.alloc.init];
    for (var i = 0; i < reqs.length; i++) {
      var err = Ref();
      handler.performRequestsError($.NSArray.arrayWithObject(reqs[i]), err);
      var res = reqs[i].results;
      if (res && !res.isNil()) total += res.count;
    }
    return String(total);
  } catch (e) {
    return 'ERR:' + e;
  }
}
"""

_robots_cache = {}
_warned = set()


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def warn_once(key, msg):
    if key not in _warned:
        _warned.add(key)
        log(msg)


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
    m = re.search(r"(19[89]\d|20[0-2]\d)\s*년?[가-힣\s]{0,6}(구매|구입|샀)", blob)
    if m:
        return m.group(1)
    m = re.search(r"(구매|구입)[^\d]{0,12}(19[89]\d|20[0-2]\d)", blob)
    if m:
        return m.group(2)
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


def classify_category(detail, allowed):
    """상세의 카테고리 경로를 허용 카테고리로 분류. 분류 불가면 None (수집 제외)."""
    names = " ".join(str(c.get("name", "")) for c in (detail.get("categories") or []))
    if not names.strip():
        return None
    for cat in ("시계", "주얼리", "패션잡화", "가방"):
        if cat in allowed and any(k in names for k in CATEGORY_KEYWORDS[cat]):
            return cat
    return None


def dealer_signal(*texts):
    """업체 신호 문구가 있으면 걸린 문구를, 없으면 None 을 반환."""
    blob = norm(" ".join(t for t in texts if t))
    for p in DEALER_PATTERNS:
        m = p.search(blob)
        if m:
            return m.group(0)
    return None


def dealer_flagged(*objs):
    """검색 결과/상세 응답의 프로샵(업체) 플래그 확인."""
    for o in objs:
        if not isinstance(o, dict):
            continue
        for k in DEALER_FLAG_KEYS:
            if o.get(k):
                return True
        shop = o.get("shop")
        if isinstance(shop, dict) and any(shop.get(k) for k in DEALER_FLAG_KEYS):
            return True
    return False


# ---------- 이미지 내용 필터 (깨끗한 배경 / 인물) ----------

def load_bmp_pixels(data):
    """비압축 24/32bpp BMP 를 [(r,g,b)] 행렬(top-down)로. 실패 시 None."""
    if not data or data[:2] != b"BM" or len(data) < 54:
        return None
    off = int.from_bytes(data[10:14], "little")
    w = int.from_bytes(data[18:22], "little", signed=True)
    h = int.from_bytes(data[22:26], "little", signed=True)
    bpp = int.from_bytes(data[28:30], "little")
    comp = int.from_bytes(data[30:34], "little")
    if w <= 0 or h == 0 or bpp not in (24, 32) or comp != 0:
        return None
    ah = abs(h)
    bypp = bpp // 8
    stride = (w * bypp + 3) // 4 * 4
    rows = []
    for r in range(ah):
        base = off + r * stride
        row = []
        for c in range(w):
            i = base + c * bypp
            if i + 3 > len(data):
                return None
            row.append((data[i + 2], data[i + 1], data[i]))  # BGR(A) → RGB
        rows.append(row)
    if h > 0:          # 양수 높이 = bottom-up 저장
        rows.reverse()
    return rows


def clean_background(pixels, ratio_threshold=0.85):
    """테두리가 흰색/회색으로 균일하면 True (스튜디오/누끼/매대 추정)."""
    h, w = len(pixels), len(pixels[0])
    t = max(1, min(w, h) // 8)
    clean = total = 0
    for y in range(h):
        for x in range(w):
            if t <= y < h - t and t <= x < w - t:
                continue
            r, g, b = pixels[y][x]
            mx, mn = max(r, g, b), min(r, g, b)
            light = (mx + mn) / 510
            sat = (mx - mn) / 255
            if (light > 0.82 and sat < 0.12) or (0.35 < light <= 0.82 and sat < 0.10):
                clean += 1
            total += 1
    return total > 0 and clean / total >= ratio_threshold


def pixels_for_analysis(path):
    """분석용 소형 픽셀 행렬. BMP 는 직접, 그 외엔 sips(macOS)로 변환. 불가 시 None."""
    data = path.read_bytes()
    if data[:2] == b"BM":
        return load_bmp_pixels(data)
    sips = shutil.which("sips")
    if not sips:
        warn_once("sips", "  sips 없음 — 배경 분석 생략 (macOS 외 환경)")
        return None
    out = Path(str(path) + ".an.bmp")
    try:
        subprocess.run(
            [sips, "-s", "format", "bmp", "--resampleHeightWidthMax", "64",
             str(path), "--out", str(out)],
            capture_output=True, timeout=30, check=True)
        return load_bmp_pixels(out.read_bytes())
    except Exception as e:
        warn_once("sips-fail", f"  sips 변환 실패 — 배경 분석 생략: {e}")
        return None
    finally:
        out.unlink(missing_ok=True)


_vision = {"script": None, "dead": not VISION_ENABLE}


def person_count(path):
    """macOS Vision 얼굴/사람 감지 수. 사용 불가 환경이면 None."""
    if _vision["dead"]:
        return None
    osa = shutil.which("osascript")
    if not osa:
        warn_once("vision", "  osascript 없음 — 인물 감지 생략 (macOS 외 환경)")
        _vision["dead"] = True
        return None
    if _vision["script"] is None:
        script = STATE_DIR / "vision_person.js"
        script.write_text(VISION_JS, encoding="utf-8")
        _vision["script"] = script
    try:
        r = subprocess.run([osa, "-l", "JavaScript", str(_vision["script"]), str(path)],
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
        if out.isdigit():
            return int(out)
        warn_once("vision-err", f"  Vision 감지 응답 이상 — 인물 감지 생략: {out or r.stderr.strip()}")
    except Exception as e:
        warn_once("vision-exc", f"  Vision 감지 실패 — 인물 감지 생략: {e}")
    _vision["dead"] = True
    return None


def image_reject_reason(path):
    """이미지 단위 제외 사유. 통과면 None."""
    px = pixels_for_analysis(path)
    if px and clean_background(px):
        return "배경 흰색/회색 (스튜디오·누끼 추정)"
    n = person_count(path)
    if n:
        return f"인물 포함 (감지 {n})"
    return None


def ensure_preview_friendly(path):
    """webp 는 macOS 미리보기 호환을 위해 jpg 로 변환 (sips, 실패 시 원본 유지)."""
    if path.suffix != ".webp":
        return path
    sips = shutil.which("sips")
    if not sips:
        return path
    out = path.with_suffix(".jpg")
    try:
        subprocess.run([sips, "-s", "format", "jpeg", str(path), "--out", str(out)],
                       capture_output=True, timeout=30, check=True)
        path.unlink()
        return out
    except Exception:
        out.unlink(missing_ok=True)
        return path


# ---------- 상태/기록 ----------

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


# ---------- 수집 ----------

def download_images(img_tpl, img_count, pid, folder, res_state):
    """이미지를 받아 내용 필터를 통과한 것만 저장. (저장 수, 제외 내역) 반환."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    kept = 0
    rejected = []
    for i in range(1, img_count + 1):
        if kept >= IMAGE_MAX:
            break
        candidates = [res_state["res"]] if res_state["res"] else IMAGE_RES_CANDIDATES
        tmp = None
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
            tmp = TMP_DIR / f"{pid}_{i:02d}.{fmt}"
            tmp.write_bytes(data)
            if not res_state["res"]:
                res_state["res"] = res
                log(f"    유효 해상도 확정: w{res} ({fmt})")
            break
        time.sleep(IMAGE_DELAY)
        if tmp is None:
            rejected.append({"index": i, "reason": "다운로드/포맷 실패"})
            continue

        reason = image_reject_reason(tmp)
        if reason:
            rejected.append({"index": i, "reason": reason})
            log(f"    이미지 제외 pid={pid} #{i}: {reason}")
            tmp.unlink(missing_ok=True)
            continue

        folder.mkdir(parents=True, exist_ok=True)
        final = folder / tmp.name
        os.replace(tmp, final)
        ensure_preview_friendly(final)
        kept += 1
    return kept, rejected


def collect_product(pid, brand, allowed_cats, downloaded, rejects, res_state):
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

    desc_raw = detail.get("description") or ""
    sig = dealer_signal(name, desc_raw)
    if sig:
        return reject(f"업체 추정 문구: '{sig}'")
    if dealer_flagged(detail):
        return reject("업체 플래그 (프로샵)")

    cat_label = classify_category(detail, allowed_cats)
    if not cat_label:
        return reject("카테고리 불일치")

    img_tpl = detail.get("imageUrl") or ""
    img_count = int(detail.get("imageCount") or 0)
    if not img_tpl or img_count < IMAGE_MIN:
        return reject(f"이미지 {img_count}장 (< {IMAGE_MIN})")

    year = extract_year(name, desc_raw)
    desc = redact_pii(desc_raw)

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

    saved, rejected_imgs = download_images(img_tpl, img_count, pid, folder, res_state)
    if saved < IMAGE_MIN:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return reject(f"유효 이미지 부족 ({saved}/{IMAGE_MIN}장)")

    meta = {
        "pid": pid, "brand": brand, "category": cat_label,
        "name": name, "price": price, "purchase_year": year,
        "image_count": saved, "image_total": img_count,
        "images_rejected": rejected_imgs,
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
    log(f"    저장: {folder.name} ({saved}/{img_count}장, 제외 {len(rejected_imgs)}장)")
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

    if "CloudStorage" not in str(BASE_DIR) and not os.environ.get("C2C_BASE"):
        log(f"주의: 구글드라이브 경로를 찾지 못해 로컬에 저장합니다 → {BASE_DIR}")

    brands = BRANDS[: int(os.environ.get("C2C_BRANDS", len(BRANDS)))]
    downloaded = load_state()
    rejects = load_rejects()
    res_state = {"res": None}   # 유효 이미지 해상도 (첫 성공 시 확정)
    today = datetime.now().strftime("%Y-%m-%d")

    log(f"=== 수집 시작 (브랜드 {len(brands)}개 × {DAILY_LIMIT}개, "
        f"이미지 {IMAGE_MIN}~{IMAGE_MAX}장, 저장: {BASE_DIR}, "
        f"기존 수집 {len(downloaded)}건, 거부 캐시 {len(rejects)}건) ===")

    total = 0
    stop = False
    for brand, allowed_cats in brands:
        if stop:
            break
        got = 0
        cache_skip = dealer_skip = 0
        log(f"[{brand}] 검색 시작 (허용: {', '.join(allowed_cats)})")
        for page in range(MAX_PAGES):
            if got >= DAILY_LIMIT or stop:
                break
            try:
                items = search_products(brand, page)
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
                    cache_skip += 1
                    continue
                if to_won(item.get("price")) < PRICE_MIN:
                    continue
                if item.get("ad"):
                    continue
                item_name = item.get("name", "")
                if not matches_brand(item_name, brand):
                    continue
                # 검색 결과 단계에서 업체 신호가 보이면 상세 API를 아예 부르지 않는다
                if dealer_signal(item_name) or dealer_flagged(item):
                    rejects[pid] = today
                    dealer_skip += 1
                    continue
                try:
                    ok, reason = collect_product(
                        pid, brand, allowed_cats, downloaded, rejects, res_state)
                    if ok:
                        got += 1
                    elif reason:
                        log(f"    건너뜀 pid={pid}: {reason}")
                except Exception as e:
                    log(f"    상품 실패 pid={pid}: {e}")
        save_state(downloaded)
        save_rejects(rejects)
        total += got
        log(f"[{brand}] 완료: 신규 {got}건 (업체 제외 {dealer_skip}건, 캐시 생략 {cache_skip}건)")

    log(f"=== 수집 종료: 오늘 총 {total}건 (누적 {len(downloaded)}건, "
        f"거부 캐시 {len(rejects)}건) ===")


if __name__ == "__main__":
    run()
