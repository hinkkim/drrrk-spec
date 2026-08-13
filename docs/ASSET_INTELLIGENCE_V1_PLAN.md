# DRRRK Asset Intelligence System — V1 전환 계획

작성일: 2026-08-13
대상 저장소: `hinkkim/drrrk-spec`
목표: 명품 가격/LTV 계산기 프로토타입 → **비정형 실물자산을 금융기관용 표준 데이터로 변환하는 Asset Intelligence System**

V1의 성공 기준은 단 하나다:

> 실제 자산 1건이 등록되어
> **AI 분석 → 전문가 검증 → 딜러 견적 → 실제 거래 → 비용 → Net Proceeds** 까지
> 하나의 `canonical_asset_id` 와 audit trail 로 연결되는 것.

이 흐름이 완성되기 전에는 고도화 ML, LTV 자동추천, 금융기관용 API를 개발하지 않는다.

---

## 1. 현재 코드 구조 (분석 결과)

먼저 중요한 사실부터: **이 저장소에는 실행 가능한 프로토타입 애플리케이션 코드가 없다.**
"사진 → Gemini → 자산 식별 → AI 시장가격 → LTV" 파이프라인은 코드가 아니라 **기획 문서로만** 존재한다.

```
drrrk-spec/
├── index.html                      # 명세서로 redirect 하는 16줄짜리 진입 페이지
├── 드르륵_기능명세서_v3.html        # 1.5MB / 10,167줄 — 핵심 자산
│   ├── 대부중개 플랫폼 기능명세서 (전당포 바이어 OS, 역경매 플로우)
│   ├── §2.5 감정가 3-tier 구조 (실시간 시세 / 입찰 기준 스냅샷 / 재평가)
│   ├── §7   데이터 모델 (Buyer, Deal, Collateral, Contract …)
│   │        └ Collateral.ai_valuation / confidence_score — "AI 감정가"가 1급 필드
│   ├── §8   외부 연동 (AI 감정 엔진 = "GOOGLE API" 한 줄뿐 — 상세 설계 없음)
│   ├── §11.4 AI 기능 도입 방향 (동적 LTV 알림, AI 담보물 가치 추정 등 — 전부 Phase 1 MVP로 명시)
│   ├── §16-B 담보 적합도 산정 (규칙 기반 100점 스코어 MVP)
│   ├── §17  상환 관리 상태머신 (연체 3축 지표, Shadow Accrual)
│   └── 문서 뷰어 JS (네비게이션, scroll-spy, File System Access API 기반 편집/저장)
└── test/
    ├── index.html                  # "내가 부자가 될 상인가?" 바이럴 퀴즈 (자산 감수성 테스트)
    └── images/                     # 퀴즈용 Figma export PNG 33장
```

시사점:

- **리팩터링 대상 코드가 없으므로, V1은 사실상 그린필드 구축이다.** 다만 "재사용"의 대상은
  코드가 아니라 **명세서 안의 도메인 지식**이며, 이것이 이 저장소의 실질 자산이다.
- 명세서의 방향(§7, §11.4)은 브리프가 지적한 "잘못된 방향" — AI 감정가를 Source of Truth로 쓰고
  LTV를 자동 추천하는 구조 — 을 그대로 담고 있다. 코드가 없을 때 방향을 바꾸는 것이 가장 싸다.
- 명세서가 참조하는 wireframe HTML들은 작성자 로컬 경로(`file:///Users/hink/...`)라 저장소에 없다.

## 2. 유지할 모듈 (재사용 자산)

| 자산 | 재사용 방식 |
|---|---|
| §2.5 감정가 3-tier 분리 원칙 | "하나의 시세 금지" 원칙의 선례. V1의 Retail Asking / Observed Sold / Dealer Firm / Expected LV 다층 가격 체계로 일반화 |
| §16-B 담보 적합도 규칙 엔진 | 규칙 기반 스코어 + 등급 + 룩업테이블 설계 패턴을 **Liquidity Engine V1** 규칙 엔진의 출발점으로 재사용. 단, 0~100 점수를 금융정책처럼 노출하지 않고 원시 지표+Confidence를 우선 노출하도록 수정 |
| §14.1 담보물 등록 입력 스펙 | Asset registration 폼 필드 정의(카테고리/브랜드/모델/상태/증빙)의 기반 |
| §7 엔티티 정의 | assets/dealer_bids/finance_cases 스키마 매핑의 입력 자료 (아래 §4 매핑표 참조) |
| §17 상환 상태머신, §16 Prime 점수 | **extension schema 참고 자료로 보존**. Prime 점수 → buyer_reliability 설계에, 상환 상태머신 → 향후 finance_events 에 매핑. V1 UX에서는 제외 |
| §4, §19 법적 컴플라이언스 정리 | 파트너 금융기관 연동 시 그대로 유효 |
| `test/` 바이럴 퀴즈 | 마케팅 퍼널로 유지. 단, Asset Intelligence 데이터와 완전 분리 (분석 데이터에 절대 혼입 금지) |
| 문서 뷰어 (명세서 HTML) | 사양 열람용으로 유지. 제품 코드로는 재사용하지 않음 |

## 3. 제거/비활성화할 기능 (설계 차원의 제거)

코드가 없으므로 "제거"는 명세서 방향의 폐기를 의미한다. V1에서 구현하지 않고, 명세서에 DEPRECATED 표기한다.

1. **`Collateral.ai_valuation` / `confidence_score` 를 1급 필드로 두는 설계** — AI 출력은 `ai_predictions` 테이블로 격리하고, 자산 레코드에는 human-verified 값만 canonical로 승격
2. **AI가 시장가격을 직접 "생성"하는 기능** (§11.4 "AI 담보물 가치 추정") — AI는 후보 추천/특징 추출/OCR/누락 필드 탐지만 수행
3. **검증되지 않은 LTV 자동추천** (§11.4 동적 LTV 알림, §16-B 권장 최대 대출금·예상 금리 범위) — 데이터 충족 전까지 `NOT AVAILABLE` 출력
4. **단일 "감정가" 숫자 출력** — 다층 가격 + range + confidence + 근거 수량으로 대체
5. **바이어 AI 입찰 어시스턴트 / 바잉 프로필 자동 매칭** (§11.4) — V2 이후로 연기
6. **대출 실행/연장/상환 워크플로우 전체** (§17, §18) — extension schema로만 설계, V1 UX 제외
7. **시뮬레이션 데이터의 실데이터 혼입** — 모든 데모/시뮬레이션 레코드는 `data_environment='SIMULATION'` 으로 격리, UI에서도 분리 표시

## 4. DB Schema (신규 설계 + 기존 엔티티 매핑)

기존 DB가 없으므로 "변경"은 §7 엔티티의 재매핑이다.

| 명세서 §7 엔티티 | V1 스키마 |
|---|---|
| Collateral | `assets` + `asset_master` (canonical) + `asset_images` 로 분해. `ai_valuation`/`confidence_score` 는 `ai_predictions` 로 이동 |
| Buyer | `dealers` (buyer_id 유지, Prime 점수는 reliability 지표 원천으로) |
| Deal / Contract | `finance_cases` / `finance_events` **extension schema** (V1 미구현) |
| 입찰 (역경매) | `dealer_bids` — INDICATIVE/FIRM/COMMITTED/SETTLED 4단계로 재설계 |

### 4.1 공통 규칙 (모든 evidence성 테이블에 적용)

```sql
-- 모든 데이터 포인트에 필수
source_type      TEXT NOT NULL,  -- AI_ESTIMATE | PUBLIC_LISTING | EXTERNAL_SOLD | EXPERT_ESTIMATE
                                 -- | DEALER_INDICATIVE_BID | DEALER_FIRM_BID | DEALER_COMMITTED_BID
                                 -- | ACTUAL_PURCHASE | ACTUAL_SALE | ACTUAL_LIQUIDATION
                                 -- | PARTNER_HISTORICAL | PARTNER_FINANCE_OUTCOME
evidence_grade   TEXT NOT NULL CHECK (evidence_grade IN ('OBSERVED','DERIVED','ESTIMATED')),
data_environment TEXT NOT NULL CHECK (data_environment IN ('SIMULATION','REAL','BACKFILL')),
source           TEXT NOT NULL,          -- 출처 식별 (dealer_id, url, partner_id …)
confidence       TEXT,                   -- HIGH | MEDIUM | LOW | INSUFFICIENT
recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

### 4.2 핵심 테이블

```sql
-- A. Asset Identity / Verification ─────────────────────────────
asset_master (            -- canonical 자산 카탈로그 (모델 단위)
  canonical_asset_id TEXT PRIMARY KEY,   -- CATEGORY-BRAND-MODEL-REFERENCE-VARIANT
  category, brand, model, reference, variant,
  attributes JSONB, created_at, updated_at
)
assets (                  -- 등록된 개별 실물 자산 (개체 단위)
  asset_id UUID PK,
  canonical_asset_id TEXT NULL REFERENCES asset_master,  -- human verification 후에만 확정
  serial_hash TEXT,                       -- 원본 serial은 저장하지 않거나 분리 보관
  registered_by, data_environment, status,
  -- status: REGISTERED → AI_ANALYZED → PENDING_VERIFICATION → VERIFIED → LISTED → SOLD/WITHDRAWN
  created_at
)
asset_images (image_id, asset_id FK, storage_url, kind, exif JSONB, uploaded_at)
asset_documents (document_id, asset_id FK, doc_type, storage_url, access_level)

-- AI 출력 격리 ──────────────────────────────────────────────────
ai_predictions (
  prediction_id UUID PK, asset_id FK,
  model_version_id FK, task,              -- IDENTIFY | OCR | CONDITION_HINT | ANOMALY | MISSING_FIELD
  candidates JSONB,                       -- top-3 후보 [{canonical_asset_id, score}]
  raw_output JSONB, ai_confidence NUMERIC,
  created_at
)

-- Human 검증 격리 ───────────────────────────────────────────────
human_verifications (
  verification_id UUID PK, asset_id FK, prediction_id FK NULL,
  field, ai_value JSONB, human_verified_value JSONB,
  verified_by, verification_started_at, verification_completed_at,  -- 검증 소요시간 KPI
  correction_flag BOOLEAN, evidence_used JSONB
)
verification_corrections (
  correction_id UUID PK, verification_id FK,
  correction_reason TEXT CHECK (correction_reason IN
    ('reference_mismatch','serial_mismatch','material','size','year','hardware',
     'stitching','logo','aftermarket_part','repair','condition',
     'insufficient_image','authenticity_issue')),
  note TEXT
)

-- B. Condition / Authenticity ──────────────────────────────────
condition_assessments (assessment_id, asset_id FK, grade, score, details JSONB,
                       assessed_by, source_type, evidence_grade, data_environment, recorded_at)
authentication_evidence (evidence_id, asset_id FK, evidence_type, result,
                         provider, fraud_flag BOOLEAN, duplicate_of NULL,
                         source_type, evidence_grade, data_environment, recorded_at)

-- C. Market Evidence ───────────────────────────────────────────
market_events (event_id, canonical_asset_id FK, event_type,   -- LISTING | SOLD
               price, currency, observed_at, url, condition_note,
               source_type, evidence_grade, data_environment, freshness_days)

-- D. Dealer Liquidity ──────────────────────────────────────────
dealers (dealer_id UUID PK, name, qualified BOOLEAN,
         payment_capacity_verified BOOLEAN, reliability JSONB, created_at)
dealer_bids (
  bid_id UUID PK, asset_id FK, buyer_id FK REFERENCES dealers,
  bid_type TEXT CHECK (bid_type IN ('INDICATIVE','FIRM','COMMITTED','SETTLED')),
  bid_price BIGINT, bid_time TIMESTAMPTZ, expiry TIMESTAMPTZ,
  status TEXT,        -- ACTIVE | EXPIRED | CANCELLED | SELECTED | REJECTED
  selected BOOLEAN, rejected_reason, settlement_status,
  source_type, evidence_grade, data_environment
)

-- E. Transaction / Outcome ─────────────────────────────────────
transactions (transaction_id UUID PK, asset_id FK, bid_id FK NULL, buyer_id FK,
              gross_price BIGINT, transacted_at, settled_at, days_to_sale INT,
              source_type, evidence_grade, data_environment)
transaction_costs (cost_id, transaction_id FK, cost_type, amount)   -- fee | shipping | authentication | refurb
outcomes (outcome_id, asset_id FK, transaction_id FK,
          net_proceeds BIGINT,                 -- gross - Σcosts
          expected_lv_7d_at_listing BIGINT NULL,  -- 백테스트용 스냅샷
          expected_lv_30d_at_listing BIGINT NULL,
          prediction_error NUMERIC NULL, recorded_at)

-- 파생 지표 (전부 DERIVED/ESTIMATED) ────────────────────────────
liquidity_snapshots (snapshot_id, canonical_asset_id FK, as_of,
  unique_qualified_bidders INT, bid_count INT, firm_bid_count INT,
  bid_dispersion NUMERIC, buyer_concentration NUMERIC,
  time_to_first_bid, time_to_first_firm_bid, time_to_best_bid,
  bid_to_sale_conversion NUMERIC, median_days_to_sale NUMERIC,
  failed_listing_count INT, rule_version)
liquidation_estimates (estimate_id, canonical_asset_id FK, asset_id FK NULL, as_of,
  horizon_days INT CHECK (horizon_days IN (7,30,60)),
  low BIGINT NULL, high BIGINT NULL,          -- NULL 허용 = INSUFFICIENT DATA 상태
  confidence TEXT NOT NULL,                    -- HIGH|MEDIUM|LOW|INSUFFICIENT
  insufficient_reason TEXT[],                  -- sample_too_small | identification_unverified
                                               -- | no_firm_bid | stale_market_evidence | authenticity_unresolved
  verified_txn_count INT, firm_bid_count INT, settled_count INT,
  data_freshness_days INT, method TEXT,        -- DEALER_MEDIAN_BASELINE | RULE_ENGINE_V1
  rule_or_model_version TEXT)

-- 거버넌스 ──────────────────────────────────────────────────────
model_versions (model_version_id, name, kind, version, config JSONB, deployed_at)
audit_logs (              -- append-only. UPDATE/DELETE 금지 (DB 권한으로 강제)
  audit_id BIGSERIAL PK, entity_type, entity_id, action,
  actor_type,             -- AI | HUMAN | SYSTEM | PARTNER
  actor_id, before JSONB, after JSONB, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- 향후 확장 (V1에서는 DDL만, UX 없음) ───────────────────────────
finance_cases, finance_events, recovery_events, institution_policies
```

설계 불변식:

- `assets.canonical_asset_id` 는 **human verification 을 통과해야만** 세팅/변경 가능. AI 추론은 절대 직접 쓰지 않는다.
- canonical 확정 이후의 모든 변경은 새 `human_verifications` + `audit_logs` 를 남긴다. 덮어쓰기 금지.
- `audit_logs` 는 append-only (DB role에서 UPDATE/DELETE revoke).
- 파생값(`liquidity_snapshots`, `liquidation_estimates`)은 언제든 원천 evidence에서 재계산 가능해야 한다.

## 5. Migration Plan

이관할 운영 데이터가 없으므로 마이그레이션 = **명세서 → 시스템 부트스트랩** 이다.

- **M0. 저장소 재구성** — 명세서/퀴즈를 `docs/`, `marketing/` 으로 이동, `app/`(제품 코드), `db/migrations/` 신설. 기존 URL 유지 필요 시 redirect 유지
- **M1. 스키마 부트스트랩** — §4의 DDL을 migration 도구(예: Supabase migrations)로 순서대로 적용: ① 거버넌스(audit_logs, model_versions) → ② Identity 계열 → ③ Evidence 계열 → ④ 파생 계열 → ⑤ extension DDL
- **M2. 시드 데이터** — 초기 카테고리 3개 이하(예: Rolex 시계 상위 모델, 금/귀금속, 특정 브랜드 백 일부)의 `asset_master` 시드. 처음부터 전 카테고리를 지원하지 않는다 (Category Expansion Risk 대응)
- **M3. 시뮬레이션 데이터 격리 이관** — 데모에 쓰던 가상 시나리오가 필요하면 전부 `data_environment='SIMULATION'` 으로만 생성. REAL 과 같은 테이블을 쓰되 모든 조회 경로에 environment 필터 강제
- **M4. Backfill 준비 (Phase 4 선행 설계)** — 파트너 장부 CSV 매핑 템플릿과 `data_environment='BACKFILL'` + `source_type='PARTNER_HISTORICAL'` 태깅 규약만 먼저 정의. 실제 import는 Phase 4
- **M5. 명세서 업데이트** — §7/§11.4 에 DEPRECATED 마킹, 본 계획 문서를 참조 문서로 링크

## 6. V1 Architecture

과도한 인프라 없이 단일 앱 + 단일 DB. (Non-goal: microservice/K8s)

```
[Consumer 등록 웹]        [Expert Verification Console]        [Dealer Bid 웹]
        │                          │                                │
        └──────────────┬───────────┴────────────────┬───────────────┘
                       ▼                            ▼
              ┌─────────────────────────────────────────────┐
              │        Web App (모놀리식, e.g. Next.js)       │
              │                                             │
              │  Registration → AI Assist → Verification    │
              │  → Evidence Ledger → Bidding → Settlement   │
              │                                             │
              │  ┌────────────────┐  ┌───────────────────┐  │
              │  │ AI Adapter     │  │ Liquidity/         │  │
              │  │ (후보추천·OCR    │  │ Liquidation        │  │
              │  │  전용, 격리 계층) │  │ Rule Engine V1     │  │
              │  └────────────────┘  │ + Confidence Gate  │  │
              │                      └───────────────────┘  │
              └──────────────┬──────────────────────────────┘
                             ▼
              Postgres (RLS + append-only audit) + Object Storage(이미지/문서)
```

- **AI Adapter 계층**: 외부 비전/LLM API 호출을 한 곳에 격리. 출력은 무조건 `ai_predictions` 에 기록 후 UI에 "후보"로만 표시. 프롬프트/모델 버전은 `model_versions` 로 추적
- **Confidence Gate**: 모든 추정 출력 직전에 최소 표본 규칙 검사 → 미달 시 `INSUFFICIENT DATA` + 사유 출력. "모른다"가 1급 응답
- **Evidence Report**: LTV 계산기 UI를 대체하는 핵심 화면 (§18 브리프 구조 그대로)
- **권한 분리**: 소비자/전문가/딜러/관리자 role. 원본 문서·serial 접근은 별도 권한 (Privacy Risk 대응)

## 7. 개발 티켓 목록 · 8. Priority · 9. 구현 순서

구현 순서 = 아래 표의 순번. 의존성이 없는 티켓끼리는 병렬 가능(같은 단계 묶음 내).

### Phase 0 — Foundation (Prototype Reset)

| # | ID | 티켓 | Priority |
|---|---|---|---|
| 1 | T-001 | 저장소 재구성 (docs/marketing/app/db 분리) + 개발환경 셋업 | P0 |
| 2 | T-002 | DB 부트스트랩: audit_logs(append-only)·model_versions + 공통 컬럼 규약 (source_type/evidence_grade/data_environment) | P0 |
| 3 | T-003 | asset_master + assets + asset_images + asset_documents 스키마 & canonical ID 규칙 (CATEGORY-BRAND-MODEL-REFERENCE-VARIANT) | P0 |
| 4 | T-004 | ai_predictions / human_verifications / verification_corrections 스키마 (AI·Human 분리 강제) | P0 |
| 5 | T-005 | 초기 카테고리 asset_master 시드 (3개 카테고리 이하) | P0 |
| 6 | T-006 | audit 트리거: canonical 변경·검증·입찰·거래 이벤트 자동 기록 + append-only 권한 강제 | P0 |

### Phase 1 — Expert Verification Console

| # | ID | 티켓 | Priority |
|---|---|---|---|
| 7 | T-101 | 자산 등록 플로우: 이미지/문서 업로드 + 기본 정보 입력 (§14.1 입력 스펙 재사용) | P0 |
| 8 | T-102 | AI Adapter: 이미지 특징 추출·OCR·top-3 canonical 후보 추천 (ai_predictions 기록) | P0 |
| 9 | T-103 | 검증 콘솔: 후보 확인/수정, correction_reason 입력, 검증 타이머, canonical 확정 | P0 |
| 10 | T-104 | Condition 평가 폼 + authentication_evidence 등록 (serial hash, 중복 탐지, fraud flag) | P0 |
| 11 | T-105 | 검증 KPI 대시보드 (Top-1 accuracy, Top-3 recall, correction rate, 검증 시간) | P1 |

### Phase 2 — Market Evidence Ledger

| # | ID | 티켓 | Priority |
|---|---|---|---|
| 12 | T-201 | market_events 수기/수집 입력 (외부 comps, freshness 추적) | P1 |
| 13 | T-202 | dealers + dealer_bids: 4단계 bid_type, expiry, 상태 전이 (INDICATIVE→FIRM→COMMITTED→SETTLED) | P0 |
| 14 | T-203 | 거래 확정 + transaction_costs + outcomes(net proceeds, days_to_sale) 기록 | P0 |
| 15 | T-204 | Evidence Report 화면 V1 (§18 구조: IDENTITY~DATA QUALITY 섹션, 시뮬레이션 배지 분리) | P0 |

### Phase 3 — Liquidity / Liquidation V1

| # | ID | 티켓 | Priority |
|---|---|---|---|
| 16 | T-301 | liquidity_snapshots 계산 잡 (unique bidders, dispersion, concentration, conversion …) | P1 |
| 17 | T-302 | Dealer Median baseline + Rule Engine V1 (liquidation_estimates, 7d/30d/60d range) | P1 |
| 18 | T-303 | Confidence Gate: 최소 표본 규칙, INSUFFICIENT DATA 상태 + 사유 출력 | **P0** |
| 19 | T-304 | 백테스트 하네스: listing 시점 추정 스냅샷 vs 실제 net proceeds 비교 (downside error) | P1 |

### Phase 4/5 — 후순위 (V1 범위 밖, 설계만 선행)

| # | ID | 티켓 | Priority |
|---|---|---|---|
| 20 | T-401 | 파트너 CSV import + 매핑 + data-quality score (BACKFILL 태깅) | P2 |
| 21 | T-402 | legacy asset ↔ asset_master 매칭 도구 | P2 |
| 22 | T-501 | finance_cases/finance_events/recovery_events extension DDL + 문서화 | P2 |
| 23 | T-502 | Asset Report API (기관용) — Evidence Report의 JSON 버전 | P2 |

주의: T-303(Confidence Gate)은 Phase 3 소속이지만 **P0** — 어떤 추정값도 gate 없이 노출하지 않는 것이 No-Fake-Confidence 원칙의 구현체이므로, T-302 배포 전 반드시 완료.

## 10. 테스트 전략

**a. 스키마/불변식 테스트 (DB 레벨)**
- CHECK 제약 검증: evidence_grade·data_environment·bid_type·correction_reason enum
- audit_logs append-only 검증: UPDATE/DELETE 시도가 권한 오류로 실패하는지
- canonical 보호: AI 경로로 `assets.canonical_asset_id` 직접 변경 시도 → 거부되는지, human verification 경로만 성공하는지

**b. 골든 패스 E2E (V1의 핵심 수용 테스트)**
등록 → AI top-3 → 전문가 확정(1건은 correction 포함) → indicative/firm bid → 낙찰 → settlement → costs → net proceeds 까지 실행 후 검증:
- 모든 레코드가 동일 `asset_id`/`canonical_asset_id` 로 조인되는지
- 각 단계의 audit_logs 가 시간순으로 완전한지
- ai_prediction 과 human_verified_value 가 별도 레코드로 남았는지

**c. Confidence Gate 테스트 (No-Fake-Confidence)**
- firm bid 2건·settled 0건 시나리오 → `INSUFFICIENT DATA` + 사유(`no_settled_transaction`) 출력 확인
- 검증 안 된 자산 → LV 추정 자체가 차단되는지 (`identification_unverified`)
- stale evidence (freshness 임계 초과) → confidence 강등 확인
- **숫자가 없어야 하는 곳에 숫자가 나오면 실패** — 이 방향의 테스트를 우선

**d. 환경 격리 테스트**
- SIMULATION 데이터가 REAL 조회·지표·추정 계산에 절대 섞이지 않는지 (모든 집계 쿼리 대상)

**e. 규칙 엔진 회귀 테스트**
- rule_version 별 스냅샷 테스트: 같은 입력 → 같은 출력, 버전 변경 시 diff 리포트
- Dealer Median baseline vs Rule Engine 비교 하네스 (향후 ML은 이 baseline을 out-of-sample로 이겨야만 배포)

**f. KPI 계측 테스트**
- 검증 타이머, correction rate, firm-to-settlement conversion 등 §20 KPI가 원천 테이블에서 재계산 가능한지

**테스트 데이터 원칙**: fixture는 전부 `data_environment='SIMULATION'`. 실데이터를 테스트에 쓰지 않고, 시뮬레이션 데이터를 실지표에 쓰지 않는다.
