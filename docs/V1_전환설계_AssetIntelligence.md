# V1 전환 설계 — Asset Intelligence System (2026-08-13)

프로토타입("명품 가격/LTV 계산기")을 **Evidence 축적 중심의 Asset Intelligence System**으로
전환하기 위한 분석과 실행 계획. 대규모 재작성이 아니라 **기존 코드 최대 재사용 + 스키마
증축(additive) + 단계별 마이그레이션**을 원칙으로 한다.

V1의 성공 기준은 단 하나다:

> **실제 자산 1건이 등록 → AI 후보 추천 → 전문가 검증 → 딜러 견적(단계 구분) → 실제 거래
> → 비용 → Net Proceeds까지 하나의 canonical_asset_id와 audit trail로 연결되는 것.**

이 흐름이 완성되기 전에는 ML 고도화·LTV 자동추천·금융기관용 기능을 개발하지 않는다.

---

## 1. 현재 코드 구조 분석

전체 약 1,900줄, 파이썬 표준 라이브러리 + SQLite만 사용 (외부 의존성 0).

```
prototype/
├─ schema.sql            # 테이블 4개: asset_master / asset_instance /
│                        #   valuation_event(append-only) / metric_snapshot
│                        #   + sim_truth (시뮬레이션 전용 정답지)
├─ catalog_seed.csv      # 22개 모델 카탈로그 (한국어 별칭 포함)
│
│  ── 데이터 생성 (시뮬레이션) ──
├─ identify.py           # identify_mock(식별 오류 모사) + Gemini 폐쇄형 프롬프트 상수
├─ simulate.py           # 365일 등록·호가·성사·외부시세·전당 백필 생성
├─ metrics.py            # 분위수 통계 → metric_snapshot
├─ report.py             # 오염률·MAPE 리포트
├─ run.py                # 시뮬레이션 오케스트레이터 (--compare 포함)
│
│  ── 분석 프로그램 (실사용 지향) ──
├─ analyze.py            # 분석 엔진 + CLI: MV/LV/스프레드/회수율/권장LTV, 신뢰도 게이트
├─ app.py                # 로컬 웹 앱 (localhost:8765) + /api/asset JSON
├─ ingest.py             # 실데이터 CSV 입력 + 금 시세 저장 (시뮬레이션 없이 DB 생성 가능)
│
│  ── 웹 배포 ──
├─ export_web.py + analyzer_template.html    # 공개 URL용 단일 HTML 분석기
└─ dashboard.py  + dashboard_template.html   # 시뮬레이션 결과 대시보드
```

### 구조적 진단 (V1 관점의 갭)

| # | 갭 | 위반하는 원칙 |
|---|---|---|
| G1 | `valuation_event` 하나에 AI 추정·호가·성사가·외부시세·백필이 전부 혼재 | Evidence 분류(§9), AI/Human 분리(§4) |
| G2 | `ai_estimate`가 **가격 이벤트로 원장에 기록됨** — AI가 가격을 생성 | AI는 Source of Truth 아님(§4), Non-goal(§21) |
| G3 | 시뮬레이션과 실데이터가 **같은 DB 파일·같은 테이블**에 쌓임 | data_environment 완전 분리(§12) |
| G4 | 호가가 단일 `buyer_quote` — INDICATIVE/FIRM/COMMITTED/SETTLED 구분 없음, 만료·취소·낙찰 없음 | Dealer Bid 설계(§10) |
| G5 | Human verification·correction·검증 시간 저장 구조 없음 (identify_mock이 대체) | HITL 아키텍처(§5) |
| G6 | 거래 수수료·비용·Net Proceeds 없음 — `contract_price`가 총액인지 순액인지 미정의 | Ground Truth(§15) |
| G7 | audit log 없음 — correction event_type만 존재, 이력 추적 불가 | 데이터 조작 리스크(§16-E) |
| G8 | 표본만 넘으면 항상 권장 LTV 출력, 금은 관행값 0.80 고정 출력 | No-Fake-Confidence(§12) |
| G9 | OBSERVED/DERIVED/ESTIMATED, evidence_grade, source_type 분류 없음 | Evidence 분류(§9) |
| G10 | 이미지·문서·상태·진위 Evidence 저장 구조 없음 | Core Layer B(§6) |

**긍정적 자산**: canonical_asset_id 중심 설계, append-only 원칙, 신뢰도 게이트(`insufficient`)와
"산출 불가" 상태, 실데이터 입력 통로(ingest.py), 분위수 기반 baseline, Gemini "가격 필드 없는
폐쇄형 식별" 프롬프트 — V1이 요구하는 방향의 씨앗이 이미 코드에 있다.

---

## 2. 유지할 모듈 (재사용 계획)

| 모듈 | 유지 방식 | V1에서의 역할 |
|---|---|---|
| `schema.sql`의 설계 원칙 | 증축 | canonical ID·append-only·meta JSON 패턴을 신규 테이블에 그대로 적용 |
| `asset_master` + `catalog_seed.csv` | 그대로 + variant 컬럼 추가 | Canonical Asset ID의 원천 (§8) |
| `ingest.py` | **주 통로로 승격** | 실데이터·백필 입력. source_type/evidence_grade/data_environment 태깅 추가 |
| `analyze.py` 엔진부 | 유지 + 리네임 | §14의 **"Dealer Median baseline"** — 이후 Rule Engine·ML의 비교 기준선. 분위수 함수(`_pct`), 윈도우 로직, find_asset 검색 재사용 |
| `analyze.py` 신뢰도 게이트 | 강화 | `insufficient` → INSUFFICIENT DATA / NOT AVAILABLE + reason 코드로 확장 |
| `app.py` | 유지 + 개편 | Evidence Report UI와 검증 콘솔(Phase 1)의 셸. 라우팅·렌더 구조 재사용 |
| `identify.py`의 `GEMINI_CLOSED_SET_PROMPT` | 유지 | AI 후보 추천(top-3, 가격 없음) 프롬프트 — ai_predictions 테이블에 기록 |
| `simulate.py`/`metrics.py`/`report.py`/`run.py`/`dashboard.py` | **격리 유지** | `sim/` 하위로 이동. 시뮬레이션 DB 전용, 그리고 **백테스트 하네스**(§14)로 전용 |
| `export_web.py` | 유지 | Evidence Report 웹 배포판 생성기로 개편 |
| `/api/asset` (app.py) | 유지 | Phase 5 기관 API의 원형 — confidence·sample·version 필드 유지 |

---

## 3. 제거·비활성화할 기능

| # | 대상 | 조치 | 근거 |
|---|---|---|---|
| R1 | 실데이터 경로의 `ai_estimate` 가격 이벤트 | **제거.** AI 산출물은 `ai_predictions`로만 (가격 필드 자체가 없음) | §4, §21 |
| R2 | 무조건 출력되는 "권장 LTV" | 게이트 뒤로. FIRM bid + settled transaction 표본 미달 시 `Financial LTV Recommendation: NOT AVAILABLE` + reason | §11, §12 |
| R3 | 금 `GOLD_LTV = 0.80` 관행값 출력 | 실측 근거 생길 때까지 "참고 관행치(비검증)" 라벨로 강등 또는 숨김 | §12 |
| R4 | 시뮬레이션 데이터의 기본 DB(`drrrk_ledger.db`) 기록 | 분리: `drrrk_sim.db`(SIMULATION 전용) / `drrrk_real.db`(REAL·BACKFILL) | §12 |
| R5 | 단일 "시세" 숫자 중심 화면 | Evidence Report(§18) 구조로 교체 — 값마다 표본수·freshness·confidence 병기 | §11 |
| R6 | `identify_mock`의 실경로 사용 | sim/ 전용으로 격리. 실경로는 AI 후보 추천 + human 확정만 | §5 |
| R7 | `dashboard.py`를 제품 산출물로 취급 | sim 도구로 강등 (README·문서에서 위상 수정) | §18 |
| R8 | `analyze.py`의 `simulate.py` import (GRADE_MULT) | 상수를 core로 이동 — 실경로가 시뮬레이터에 의존하지 않게 | 격리 원칙 |

삭제가 아니라 대부분 "격리·강등"이다. 시뮬레이터는 백테스트·회귀 테스트 자산으로 계속 쓴다.

---

## 4. DB 스키마 변경 (schema_v1.sql)

### 4.1 공통 Evidence 컬럼 — 모든 증거성 테이블에 필수

```sql
source            text not null,       -- buyer:강남A / kream / gemini-2.0 / expert:김OO
source_type       text not null check (source_type in (
  'AI_ESTIMATE','PUBLIC_LISTING','EXTERNAL_SOLD','EXPERT_ESTIMATE',
  'DEALER_INDICATIVE_BID','DEALER_FIRM_BID','DEALER_COMMITTED_BID',
  'ACTUAL_PURCHASE','ACTUAL_SALE','ACTUAL_LIQUIDATION',
  'PARTNER_HISTORICAL','PARTNER_FINANCE_OUTCOME')),
evidence_class    text not null check (evidence_class in ('OBSERVED','DERIVED','ESTIMATED')),
data_environment  text not null check (data_environment in ('SIMULATION','REAL','BACKFILL')),
confidence        real,                -- 산출물에만 (관측치는 NULL)
verified_status   text default 'UNVERIFIED'
                  check (verified_status in ('UNVERIFIED','VERIFIED','REJECTED')),
observed_at       text not null,
created_at        text default (datetime('now'))
```

### 4.2 테이블 매핑 — 기존 → V1

| 기존 | V1 | 변경 |
|---|---|---|
| `asset_master` | `asset_master` | `variant`, `status(active/merged/deprecated)`, `merged_into` 추가. **AI 오추론으로 덮어쓰기 금지** — 변경은 audit_logs 경유만 |
| `asset_instance` | `assets` | 개별 실물. `data_environment`, `identity_status(AI_CANDIDATE/HUMAN_VERIFIED/DISPUTED)`, `registered_by` 추가 |
| (없음) | `asset_images`, `asset_documents` | 원본 Evidence 보존 (파일 경로 + sha256 해시 + 촬영 메타) |
| `valuation_event`의 `ai_estimate` | `ai_predictions` | prediction_type(identity/condition/anomaly/field_extraction), payload JSON(top-3 후보+근거), confidence, `model_version_id` FK. **가격 필드 없음** |
| (없음) | `human_verifications` | asset_id, field(identity/condition/authenticity), ai_prediction_id FK(nullable), verified_value, verified_by, started_at/completed_at(검증 시간 측정), evidence_used |
| (없음) | `verification_corrections` | verification_id FK, correction_flag, correction_reason enum(reference_mismatch/serial_mismatch/material/size/year/hardware/stitching/logo/aftermarket_part/repair/condition/insufficient_image/authenticity_issue), before/after 값 |
| (없음) | `condition_assessments` | grade(S/A/B/C 유지), 부위별 점수 JSON, 근거 이미지 참조 |
| (없음) | `authentication_evidence` | evidence_type(serial/hologram/receipt/external_cert/expert_opinion), result(pass/fail/inconclusive), serial_hash(원문 대신 해시 §16-H), duplicate_check_result |
| `valuation_event`의 `external_comp` | `market_events` | listing/sold 구분(source_type로), currency, url/출처 스냅샷 |
| `valuation_event`의 `buyer_quote` | `dealer_bids` | **bid_type(INDICATIVE/FIRM/COMMITTED/SETTLED)**, buyer_id, expiry, status(active/expired/cancelled/selected/rejected), rejected_reason, payment_capacity_verified, settlement_status |
| `valuation_event`의 `contract_price` | `transactions` | asset_id, winning_bid_id FK, gross_price, transaction_type(sale/purchase/liquidation), settled_at, days_to_sale |
| (없음) | `transaction_costs` | transaction_id FK, cost_type(platform_fee/shipping/authentication/repair/other), amount → **net_proceeds = gross − Σcosts** (DERIVED) |
| `metric_snapshot` | `liquidity_snapshots` | 원시 지표 중심으로 재정의: unique_qualified_bidders, firm_bid_count, bid_dispersion, buyer_concentration(top1/top3 점유율), time_to_first_bid/first_firm_bid, bid_to_sale_conversion, days_to_sale_median, failed_listing_count |
| (없음) | `liquidation_estimates` | horizon(7d/30d/60d), range_low/mid/high, confidence(HIGH/MEDIUM/LOW/INSUFFICIENT), reason_codes JSON, input_sample JSON(표본수 명세), `rule_version` — **ESTIMATED로만 분류** |
| (없음) | `outcomes` | 예측 대비 실측 대사: estimate_id FK ↔ transaction_id FK, error_pct, downside_error — 캘리브레이션의 원천 |
| (없음) | `model_versions` | AI 모델/룰 엔진 버전 레지스트리 (이름, 버전, 파라미터 해시, 배포일) |
| (없음) | `audit_logs` | **append-only** (UPDATE/DELETE를 SQLite trigger로 RAISE). actor, action, table_name, record_id, before/after JSON, reason |
| `sim_truth` | `sim/` 전용 유지 | 실DB 스키마에서 제외 |
| `valuation_event` | **호환 뷰로 유지** | `valuation_event_v` 뷰가 신규 테이블을 union — 기존 analyze/dashboard가 마이그레이션 기간 동안 그대로 작동 |

확장 예약(스키마만 정의, V1 UX 제외 — §6): `finance_cases`, `finance_events`,
`recovery_events`, `institution_policies`.

### 4.3 신뢰도 계층의 강제

- `dealer_bids.bid_type='FIRM'` → source_type `DEALER_FIRM_BID`, evidence_class `OBSERVED`
- 딜러 중앙값·유동성 지표 → `DERIVED` (liquidity_snapshots)
- 30d LV → `ESTIMATED` (liquidation_estimates)
- 위 분류는 CHECK 제약 + 입력 코드 양쪽에서 강제. **bid count를 독립 표본수로 쓰지 않고
  unique_qualified_bidders를 별도 산출**한다.

---

## 5. 마이그레이션 플랜

원칙: **증축(additive) → 이식 → 호환 뷰 → 전환 → 구뷰 폐기**. 각 단계는 되돌릴 수 있다.

| 단계 | 작업 | 산출물 |
|---|---|---|
| M0 | `schema_v1.sql` 작성 — 기존 테이블 옆에 신규 테이블 추가 (기존 것 삭제 없음) | schema_v1.sql |
| M1 | DB 분리: 기존 `drrrk_ledger.db` → `drrrk_sim.db`로 개명(전량 SIMULATION 태깅), 실DB `drrrk_real.db` 신규 생성. `db.py`의 `connect(env)`가 환경별 파일 라우팅 | db.py |
| M2 | `migrate_v1.py` (멱등): 기존 `valuation_event` → 신규 테이블 이식. 매핑: buyer_quote→dealer_bids(bid_type=INDICATIVE — 기존 호가는 구속력 미확인이므로 보수적으로), contract_price→transactions(costs 없음→net=gross, `costs_unknown` 플래그), external_comp→market_events, ai_estimate→ai_predictions(가격은 payload로 격하), backfill_*→data_environment=BACKFILL | migrate_v1.py |
| M3 | 호환 뷰 `valuation_event_v` 생성 → 기존 analyze.py·dashboard가 무수정 작동 확인 (행 수 대사 테스트) | 뷰 + 대사 테스트 |
| M4 | analyze.py·app.py·ingest.py를 신규 테이블 직조회로 전환, export_web 갱신 | 코드 전환 |
| M5 | 검증 완료 후 실DB에서 legacy 테이블·뷰 제거. sim DB는 legacy 유지 가능 | 정리 |

주의: 기존 시뮬레이션 DB 3종(`_85/_95/_99`)은 재생성 가능하므로 이식하지 않는다 —
`run.py`가 schema_v1로 다시 생성.

---

## 6. V1 아키텍처

```
prototype/
├─ core/
│  ├─ schema_v1.sql          # §4의 전체 DDL + audit trigger
│  ├─ db.py                  # connect(env='REAL'|'SIMULATION') — 환경별 DB 라우팅
│  ├─ evidence.py            # source_type/evidence_class/correction_reason enum, 상수(GRADE_MULT 등)
│  └─ audit.py               # 모든 쓰기 경로가 경유하는 audit_logs 기록기
├─ intake/
│  ├─ ingest.py              # (기존 승격) CSV·수기 입력 — 태깅 필수화
│  ├─ ai_assist.py           # (identify.py 개편) 후보 추천·필드 추출·anomaly 후보 → ai_predictions
│  └─ verify.py              # 전문가 검증 워크플로 (확정·correction·시간 기록)
├─ market/
│  ├─ bids.py                # bid 수명주기 상태기계 (INDICATIVE→FIRM→COMMITTED→SETTLED / 만료·취소)
│  └─ transactions.py        # 거래·비용·net proceeds·outcome 대사
├─ engine/
│  ├─ baseline.py            # (analyze.py 엔진부) Dealer Median baseline
│  ├─ liquidity.py           # §13 원시 지표 산출 → liquidity_snapshots
│  └─ liquidation.py         # §14 rule-based 구간 추정 + confidence gating + reason codes
├─ report/
│  ├─ asset_report.py        # §18 Evidence Report 조립 (JSON — API·웹·CLI 공용)
│  ├─ app.py                 # (기존 개편) 검증 콘솔 + Evidence Report 웹
│  └─ export_web.py          # 공개 배포판 생성
└─ sim/                      # 격리 — simulate/metrics/report/run/dashboard + sim_truth
                             #   역할 전환: 데모 → 회귀 테스트·백테스트 하네스
```

데이터 흐름 (§4 목표 구조의 구현):

```
사진/문서/입력 ─→ ai_assist(특징·후보·가격없음) ─→ ai_predictions
                                                     │
                                    verify(전문가 확정·correction) ─→ human_verifications
                                                     │                verification_corrections
                                              canonical_asset_id 확정 (assets.identity_status)
                                                     │
        condition_assessments · authentication_evidence · asset_images/documents
                                                     │
        market_events(외부) · dealer_bids(4단계) · transactions+costs → net_proceeds
                                                     │
                liquidity.py(DERIVED) · liquidation.py(ESTIMATED, gated)
                                                     │
                      outcomes(예측 vs 실측) ─→ 캘리브레이션 → Learning Loop
                                                     │
                          asset_report.py — Evidence Report / API
   (모든 화살표의 쓰기는 audit.py 경유, 모든 행에 data_environment)
```

---

## 7–9. 개발 티켓 · 우선순위 · 구현 순서

구현 순서는 아래 번호 순서와 같다 (의존관계 반영). P0 완료 = "실물 1건 관통" 성공 기준 충족.

### P0 — Phase 0: Prototype Reset (관통 흐름의 뼈대)

| # | 티켓 | 내용 | 완료 조건 |
|---|---|---|---|
| T1 | core: schema_v1 + enum + audit | §4 DDL, audit_logs + UPDATE/DELETE 금지 trigger, evidence.py enum | 스키마 적용·제약 위반 시 실패 확인 |
| T2 | core: 환경 분리 db.py | sim/real DB 파일 분리, 전 기록 data_environment 필수화, sim/ 이동 | 실DB에 SIMULATION 행이 물리적으로 못 들어감 |
| T3 | migrate_v1.py + 호환 뷰 | §5의 M2·M3 | 행 수 대사 100% 일치, 기존 도구 무수정 작동 |
| T4 | intake: AI/Human 분리 | ai_predictions 기록(가격 없음), verify.py로 확정·correction reason·검증시간 저장. 실경로에서 ai_estimate 가격 이벤트 제거(R1) | AI 예측값과 인간 검증값이 항상 별도 행 |
| T5 | market: bid 4단계 + 거래·비용 | dealer_bids 상태기계, transactions + transaction_costs + net_proceeds | INDICATIVE→SETTLED 전이·만료·취소가 기록됨 |
| T6 | engine/report: confidence gating | INSUFFICIENT DATA / NOT AVAILABLE + reason codes(§12), LTV 게이트(R2), 금 관행값 강등(R3) | 빈 원장 입력 시 모든 산출이 "산출 불가 + 이유" |
| T7 | **관통 시나리오 검증** | 실자산 1건(수기 입력 가능)을 T1–T6 경로로 끝까지 통과시키는 스크립트 + 문서 | canonical ID 1개에 전 단계 + audit trail 조회 가능 |

### P1 — Phase 1–2: 검증 콘솔 · 시장 Evidence 원장

| # | 티켓 | 내용 |
|---|---|---|
| T8 | 전문가 검증 콘솔 (app.py 확장) | 이미지 업로드·AI top-3 표시·원클릭 확정/수정·correction reason 선택·상태 폼·진위 evidence 첨부·검증 타이머 |
| T9 | 시장 Evidence 입력 UI/CLI | 외부 comps 등록, bid 등록·만료·전환, 거래 정산·비용 입력 (ingest 확장 + 콘솔 폼) |
| T10 | Evidence Report (§18) | asset_report.py + app.py 화면 교체: IDENTITY/CONDITION/AUTHENTICITY/MARKET/DEALER/LIQUIDITY/LIQUIDATION/OUTCOME/DATA QUALITY 섹션. export_web 갱신 |
| T11 | liquidity.py 원시 지표 | §13 feature 전체 — 점수화 없이 원시값+표본수로 노출 |
| T12 | KPI 리포트 (§20) | correction rate, top-1/top-3 정확도, 검증 시간·비용, firm-to-settlement 전환율 등 — sim/report.py 구조 재사용 |

### P2 — Phase 3–4: 추정 엔진 · 파트너 데이터

| # | 티켓 | 내용 |
|---|---|---|
| T13 | liquidation.py V1 + 백테스트 | rule-based 7d/30d/60d 구간 추정, freshness·condition 조정, sim/을 백테스트 하네스로 전용. **Dealer Median baseline과 out-of-sample 비교표가 산출물** |
| T14 | outcomes 캘리브레이션 루프 | estimate↔transaction 자동 대사, downside error 추적 |
| T15 | 파트너 백필 임포터 | ingest 확장: 파트너 CSV 매핑, data-quality score, legacy 자산 매칭, BACKFILL 태깅 |
| T16 | Gemini 실연동 | ai_assist.py에 실제 API 호출 (기존 폐쇄형 프롬프트) — 후보·필드 추출만, model_versions 기록 |
| T17 | 기관용 Asset Report API | /api/asset 확장: 버전드 JSON, 기관 정책 분리 원칙 반영 — **P0·P1 KPI가 충족되기 전 착수 금지** |

---

## 10. 테스트 전략

**1) 제약·불변식 테스트 (T1과 동시 작성)**
- audit_logs UPDATE/DELETE 시도 → trigger가 거부하는지
- 실DB에 `data_environment='SIMULATION'` 삽입 거부
- evidence_class 오분류 거부 (FIRM bid를 ESTIMATED로 넣기 등)
- ai_predictions에 가격 필드가 존재할 수 없음 (스키마 수준)

**2) 마이그레이션 대사 테스트**
- 구 `valuation_event` 행 수 = 신규 테이블 합계 (event_type별 매핑 대사)
- 마이그레이션 멱등성: 2회 실행 = 1회 실행 결과

**3) 상태기계 테스트 (bids/transactions)**
- 허용 전이만 통과 (INDICATIVE→FIRM→COMMITTED→SETTLED, 만료·취소 경로)
- expiry 경과 후 FIRM bid가 유동성 지표에서 제외되는지
- net_proceeds = gross − Σcosts 검증, costs_unknown 플래그 경로

**4) No-Fake-Confidence 테스트 (핵심)**
- 빈 원장 → 모든 값 INSUFFICIENT DATA + reason
- FIRM 2건·settled 0건 → LV에 "Only 2 firm bids / no settled transaction" reason 출력
- identification UNVERIFIED 자산 → LTV NOT AVAILABLE
- **골든 파일**: Evidence Report JSON을 시나리오별 스냅샷으로 고정 (회귀 감지)

**5) 시뮬레이터 = 통합 테스트 하네스**
- run.py를 SIMULATION 환경으로 돌려 전 파이프라인 관통 (CI에서 실행 가능한 결정적 seed)
- sim_truth로 correction rate·오염률 지표가 KPI 리포트에 정확히 잡히는지 검증

**6) 백테스트 (T13 배포 게이트)**
- 시간 절단 holdout: 거래일 이전 데이터만으로 LV 추정 → actual net proceeds와 비교
- Dealer Median baseline vs Rule Engine 비교표 — **baseline을 못 이기면 배포하지 않는다**
- 이후 ML도 같은 게이트를 통과할 때만 배포 (§14)

**7) 관통 시나리오 (T7 = 인수 테스트)**
- 실물 1건: 등록→AI 후보→전문가 확정(correction 1건 포함)→INDICATIVE 3건→FIRM 1건→
  COMMITTED→SETTLED→비용 2건→net proceeds→outcome 대사→Evidence Report 출력→
  audit trail 전체 조회. 이 시나리오가 통과하면 V1 뼈대 완성.

---

## 부록 — 원칙 준수 체크리스트 (리뷰 시 사용)

- [ ] AI가 가격을 생성하는 경로가 어디에도 없는가 (R1)
- [ ] 모든 증거 행에 source_type / evidence_class / data_environment가 있는가
- [ ] AI 예측과 인간 검증이 별도 행으로 남는가 (덮어쓰기 없음)
- [ ] canonical_asset_id 변경이 audit_logs 없이 불가능한가
- [ ] 표본 부족 시 숫자 대신 "산출 불가 + 이유"가 나오는가
- [ ] bid count가 아니라 unique_qualified_bidders를 쓰는가
- [ ] 시뮬레이션 데이터가 실DB·실UI에 섞일 수 없는가
- [ ] 고도화 ML·LTV 자동추천·기관 기능을 P0 완료 전에 만들고 있지 않은가
