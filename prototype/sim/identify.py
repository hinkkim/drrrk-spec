"""1차 단계 — 자산 식별 · 상태판별 · 정가품 판별.

이 프로토타입에서 가장 중요한 모듈. 원장에 들어가는 모든 이벤트는
여기서 결정된 canonical_asset_id 에 귀속되므로, 이 단계의 오류율이
곧 데이터 표준화 품질의 상한이다 (시나리오 비교로 정량 확인 가능).

실서비스 대응:
  - identify_mock()  : 시뮬레이션용. 오류율을 파라미터로 주입해 영향 측정.
  - identify_gemini(): 실제 Gemini 연동 자리. 폐쇄형 분류(카탈로그 매칭) 프롬프트
                       구조만 정의해 둠 (GEMINI_API_KEY 있을 때 교체 사용).
"""
import random
from dataclasses import dataclass


@dataclass
class IdentifyResult:
    canonical_asset_id: str      # 관측된(플랫폼이 믿는) 자산 ID
    confidence: float            # top-1 confidence
    grade: str                   # 관측된 상태등급
    fake_detected: bool          # 정가품 판별 결과 (True = 가품 판정 → 등록 거절)
    needs_user_confirm: bool     # confidence 낮음 → 유저 후보 선택 UI로 폴백


GRADES = ["S", "A", "B", "C"]


def identify_mock(true_asset, true_grade, is_fake, catalog, rng: random.Random,
                  id_accuracy=0.95, grade_accuracy=0.80, fake_detection=0.90,
                  confirm_threshold=0.75):
    """시뮬레이션용 1차 단계. 실제 오류 패턴을 모사한다:
    - 오식별: 같은 브랜드/카테고리의 '이웃 모델'로 헷갈린다 (전혀 다른 물건 X)
    - 상태 오판: 한 등급 위/아래로 틀린다
    - 가품: fake_detection 확률로 잡아낸다. 놓치면 원장에 유입된다.
    """
    # ── 정가품 판별 ──
    fake_detected = bool(is_fake and rng.random() < fake_detection)

    # ── 자산 식별 (폐쇄형: 카탈로그 안에서 고른다) ──
    if rng.random() < id_accuracy:
        observed = true_asset
        confidence = rng.uniform(0.82, 0.99)
    else:
        neighbors = [a for a in catalog
                     if a["canonical_asset_id"] != true_asset["canonical_asset_id"]
                     and (a["brand"] == true_asset["brand"]
                          or a["category"] == true_asset["category"])]
        observed = rng.choice(neighbors) if neighbors else true_asset
        confidence = rng.uniform(0.40, 0.80)

    # ── 상태등급 판별 ──
    gi = GRADES.index(true_grade)
    if rng.random() < grade_accuracy:
        observed_grade = true_grade
    else:
        observed_grade = GRADES[max(0, min(3, gi + rng.choice([-1, 1])))]

    return IdentifyResult(
        canonical_asset_id=observed["canonical_asset_id"],
        confidence=round(confidence, 3),
        grade=observed_grade,
        fake_detected=fake_detected,
        needs_user_confirm=confidence < confirm_threshold,
    )


# ── 실서비스용: Gemini 폐쇄형 분류 프롬프트 구조 (자리만 정의) ──────────────
GEMINI_CLOSED_SET_PROMPT = """당신은 명품 자산 식별 전문가입니다. 가격은 절대 추정하지 마십시오.

첨부된 사진들을 보고 아래 후보 카탈로그 **안에서만** 가장 가능성 높은 모델 top-3를 고르세요.
후보에 확실히 없다면 candidates를 빈 배열로 반환하세요.

[후보 카탈로그]
{catalog_subset}

다음 JSON 스키마로만 응답:
{{
  "brand": "...",
  "candidates": [
    {{"canonical_asset_id": "...", "confidence": 0.0~1.0,
      "evidence": "판별 근거 (다이얼 각인, 베젤, 금구, 스티치 등)"}}
  ],
  "grade_estimate": "S|A|B|C",
  "grade_evidence": "...",
  "authenticity_flags": ["의심 포인트가 있으면 서술"],
  "photo_requests": ["판별에 더 필요한 부위 사진이 있으면 요청"]
}}"""


def identify_gemini(photo_paths, brand_hint, catalog):  # pragma: no cover
    """실제 연동 자리. 흐름:
    1) 사진에서 브랜드/카테고리 1차 추출 (또는 유저 입력 brand_hint)
    2) catalog에서 해당 브랜드 후보 서브셋 구성 (aliases 포함)
    3) GEMINI_CLOSED_SET_PROMPT 로 폐쇄형 분류 호출 (구조화 출력 강제)
    4) top-1 confidence < 0.75 → 후보 3개 유저 선택 UI 폴백
    5) authenticity_flags 존재 → 검수 대기 상태로 전환
    가격 필드는 스키마에 아예 없다 — 가격은 원장(metrics)에서만 나온다.
    """
    raise NotImplementedError("GEMINI_API_KEY 연동 시 구현 — 프로토타입은 identify_mock 사용")
