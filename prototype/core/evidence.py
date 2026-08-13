"""Evidence 분류 체계와 공용 상수 — V1 설계 §9·§13.

모든 데이터 포인트는 세 축으로 분류한다:
  source_type      어디서 온 데이터인가 (딜러 FIRM bid, 외부 sold, AI 추정 …)
  evidence_class   OBSERVED(관측) / DERIVED(파생) / ESTIMATED(추정)
  data_environment SIMULATION / REAL / BACKFILL — 물리적으로 섞이지 않는다 (core/db.py)

AI estimate와 actual transaction을 같은 신뢰도로 취급하지 않기 위한 최소 장치다.
"""

SOURCE_TYPES = (
    "AI_ESTIMATE", "PUBLIC_LISTING", "EXTERNAL_SOLD", "EXPERT_ESTIMATE",
    "DEALER_INDICATIVE_BID", "DEALER_FIRM_BID", "DEALER_COMMITTED_BID",
    "ACTUAL_PURCHASE", "ACTUAL_SALE", "ACTUAL_LIQUIDATION",
    "PARTNER_HISTORICAL", "PARTNER_FINANCE_OUTCOME",
)

EVIDENCE_CLASSES = ("OBSERVED", "DERIVED", "ESTIMATED")

ENVIRONMENTS = ("SIMULATION", "REAL", "BACKFILL")

BID_TYPES = ("INDICATIVE", "FIRM", "COMMITTED", "SETTLED")

# bid_type → source_type 매핑 (dealer_bids 입력 시 자동 결정)
BID_SOURCE_TYPE = {
    "INDICATIVE": "DEALER_INDICATIVE_BID",
    "FIRM": "DEALER_FIRM_BID",
    "COMMITTED": "DEALER_COMMITTED_BID",
    "SETTLED": "ACTUAL_PURCHASE",
}

CORRECTION_REASONS = (
    "reference_mismatch", "serial_mismatch", "material", "size", "year",
    "hardware", "stitching", "logo", "aftermarket_part", "repair",
    "condition", "insufficient_image", "authenticity_issue",
)

IDENTITY_STATUSES = ("UNIDENTIFIED", "AI_CANDIDATE", "HUMAN_VERIFIED", "DISPUTED")

# 산출 불가 사유 코드 (§12 No-Fake-Confidence)
REASON_CODES = (
    "sample_too_small",           # 표본 부족
    "no_firm_bid",                # FIRM bid 없음
    "no_settled_transaction",     # 정산 완료 거래 없음
    "identification_unverified",  # 전문가 식별 확정 전
    "stale_market_evidence",      # 최신 증거 없음 (freshness 초과)
    "authenticity_unresolved",    # 진위 미해결
)

# ── 가격·등급 상수 (구 simulate.py/metrics.py에서 이동 — 실측으로 교체 대상) ──
GRADE_MULT = {"S": 1.08, "A": 1.00, "B": 0.88, "C": 0.72}
DISPOSAL_COST = 0.05
PURITY = {"24K": 0.999, "22K": 0.916, "18K": 0.750, "14K": 0.585}
GOLD_BUY_SPREAD = 0.05   # 귀금속 매입 스프레드 (실측으로 교체할 것)

MIN_SAMPLE = 5
STALE_DAYS = 90          # 이 일수보다 오래된 증거만 있으면 stale


def pct(values, p):
    """수동 분위수 (표준 라이브러리만 사용). 값이 없으면 None."""
    if not values:
        return None
    vs = sorted(values)
    k = (len(vs) - 1) * p
    f, c = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[f] + (vs[c] - vs[f]) * (k - f)
