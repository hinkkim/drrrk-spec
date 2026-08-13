# 드르륵 Asset Intelligence System — V1 프로토타입

비정형 실물자산(명품·시계·귀금속)을 금융기관이 사용할 수 있는 표준 데이터로
변환하는 시스템. **"정답을 잘 예측하는 시스템"이 아니라 "정답을 학습할 수 있도록
Evidence와 Ground Truth를 정확히 축적하는 시스템"**이 V1의 목표다.

설계 문서: `docs/V1_전환설계_AssetIntelligence.md` · 파이썬 표준 라이브러리만 사용 (설치 불필요).

## 핵심 원칙 (코드로 강제됨)

| 원칙 | 강제 위치 |
|---|---|
| AI는 가격을 만들지 않는다 — 식별 후보·필드 추출만 | `ai_predictions` 스키마 CHECK + `intake/ai_assist.py` |
| AI 예측과 인간 검증은 항상 별도 행 | `human_verifications` / correction 사유 13종 enum |
| 시뮬레이션과 실데이터는 물리적으로 분리 | `drrrk_sim.db` / `drrrk_real.db` + 환경 가드 trigger |
| 모든 증거에 source_type · OBSERVED/DERIVED/ESTIMATED | 전 테이블 공통 컬럼 + CHECK |
| bid는 4단계 (INDICATIVE→FIRM→COMMITTED→SETTLED) | `market/bids.py` 상태기계 — 역행·건너뛰기 거부 |
| 표본이 부족하면 "모른다"고 답한다 | confidence 게이트 — LTV `NOT AVAILABLE` + 사유 코드 |
| 모든 상태 변경은 audit trail | `audit_logs` append-only (trigger로 UPDATE/DELETE 차단) |

## 빠른 시작 (prototype/ 디렉토리에서)

```bash
# ① 관통 시나리오 — 실물 1건이 등록→AI→검증→bid→거래→Net Proceeds까지 흐르는지
python3 e2e_scenario.py

# ② 실데이터 입력 (REAL 원장 — 실제 운영은 여기부터)
python3 intake/ingest.py template          # CSV 템플릿
python3 intake/ingest.py events real_data_template.csv
python3 intake/ingest.py spot gold 152000  # 금 시세

# ③ 분석 — Evidence Report
python3 analyze.py list                    # 자산 목록 (기본: REAL)
python3 analyze.py asset "서브마리너"       # 리포트 (LTV는 게이트 통과 시에만)
python3 analyze.py gold --purity 18K --weight 18.75
python3 app.py                             # 웹 (localhost:8765) + /api/asset

# ④ 시뮬레이션 (회귀 테스트·백테스트 하네스 — 별도 DB)
python3 sim/run.py                         # → drrrk_sim.db (v1 자동 이식 포함)
python3 sim/run.py --compare               # 식별 정확도 85/95/99% 비교
python3 analyze.py --env SIM asset "클미"   # 시뮬레이션 원장 조회
python3 sim/dashboard.py                   # 시뮬레이션 대시보드 HTML

# ⑤ 테스트 (52건 + e2e)
python3 -m unittest discover -s tests
```

## 구조

```
core/       schema_v1.sql(전 테이블 DDL+무결성 trigger) · db.py(환경 분리)
            evidence.py(분류 enum·상수) · audit.py
intake/     ingest.py(실데이터 입력·자산 등록) · ai_assist.py(AI 후보 — 가격 금지)
            verify.py(전문가 확정·correction·진위)
market/     bids.py(bid 4단계 상태기계) · transactions.py(거래·비용·net proceeds·outcome)
engine/     baseline.py(Dealer Median baseline — 이후 모델의 비교 기준선)
            liquidity.py(원시 유동성 지표) · liquidation.py(rule-v1 구간 추정+게이트)
report/     asset_report.py(Evidence Report §18 — CLI·웹·API 공용 JSON)
sim/        시뮬레이터 격리 (simulate/metrics/report/run/dashboard + legacy 스키마)
tests/      제약 16 · 환경 6 · 마이그레이션 8 · intake/market 12 · 게이팅 10 · e2e
analyze.py  CLI · app.py 웹 앱 · export_web.py 공개 배포판 · migrate_v1.py
e2e_scenario.py  P0 인수 테스트 (관통 흐름)
```

## Evidence Report가 답하는 것 (§18)

하나의 "시세" 숫자가 아니라: 식별(AI 후보 vs 인간 확정·correction 이력) · 진위
(시리얼 해시·중복 탐지) · 시장(호가/sold 분리) · 딜러(단계별 호가·바이어 집중도·
취소/정산실패) · 유동성(전환율·소요일·유찰) · 청산 범위(7/30일·confidence·사유) ·
실측(gross−비용=net proceeds) · 데이터 품질(표본·evidence grade·누락 필드).

데이터가 부족하면:

```
LTV           NOT AVAILABLE — no_firm_bid, no_settled_transaction
LIQUIDATION   30d: INSUFFICIENT DATA — sample_too_small
```

## 주의

- `drrrk_sim.db`의 숫자는 **100% 시뮬레이션**이다 (기준가 수기 근사 + 가정 기반
  난수). 목적은 그릇(스키마·산식·게이트)의 작동 검증. 실측은 `intake/ingest.py`로
  들어오는 순간 같은 프로그램이 REAL 원장 위에서 동작한다.
- 다음 단계(P1~): 전문가 검증 콘솔(T8) · 시장 Evidence 입력 UI(T9) · Evidence
  Report 웹 고도화(T10) · 유동성 KPI(T11~12) · 백테스트(T13) · 파트너 백필(T15) ·
  Gemini 실연동(T16) · 기관 API(T17). 티켓 정의는 설계 문서 §7–9.
