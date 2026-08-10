# 드르륵 자산 분석 프로그램 — 로컬 프로토타입

중고 실물자산·귀금속 정보를 분석하는 프로그램. 자산을 입력하면
**식별 → 시장가치(MV) → 청산가치(LV) → 유동성 → 권장 LTV**를 원장 데이터에서 산출한다.
내 컴퓨터에서 돌려 검증한 뒤 정식 개발로 넘어가기 위한 프로토타입.

## 분석 프로그램 사용법

```bash
python3 app.py                                        # 웹 앱 → http://localhost:8765
python3 analyze.py asset "서브마리너" --grade A        # CLI (별칭·모델명 검색 지원)
python3 analyze.py gold --purity 18K --weight 18.75   # 귀금속 — 시세×순도×중량
python3 analyze.py list                               # 분석 가능 자산 목록
```

실데이터로 원장을 키우는 통로 (시뮬레이션 없이도 사용 가능):

```bash
python3 ingest.py template                 # 입력용 CSV 템플릿 생성
python3 ingest.py events real_data.csv     # 실제 견적·성사가·백필 일괄 입력
python3 ingest.py spot gold 152000         # 금 시세 저장 (24K 1g당 원)
```

금융기관 PoC용 JSON API도 웹 앱에 내장: `GET /api/asset?q=서브마리너&grade=A`

귀금속과 브랜드 자산의 차이가 곧 이 프로그램의 논리다 —
**금은 표준화 자산이라 시세×순도×중량으로 즉시 계산된다 (은행이 이미 담보로 받는 이유).
명품은 비표준 자산이라 모델·상태별 실거래 원장이 있어야 같은 답을 낼 수 있다 (드르륵의 존재 이유).**

- 배경 전략: [`../docs/실물자산_금융데이터_시스템_전략.md`](../docs/실물자산_금융데이터_시스템_전략.md)
- 원장 설계: [`../docs/자산_언더라이팅_원장_구현스펙.md`](../docs/자산_언더라이팅_원장_구현스펙.md)

## 시뮬레이션 (원장 검증용 — 설치 불필요, 파이썬 3.9+ 표준 라이브러리만)

```bash
python3 run.py                        # 기본: 365일, 하루 2건 등록, 전당포 백필 300건
python3 run.py --days 730 --listings-per-day 3
python3 run.py --compare              # ★ 1차 단계(식별) 정확도 85/95/99% 시나리오 비교
python3 dashboard.py                  # 웹 대시보드 생성 → reports/dashboard.html (브라우저로 열기)
```

출력:
- `drrrk_ledger.db` — SQLite 원장 (스키마 = 구현 스펙과 동일 구조)
- `reports/summary.md` — Asset Score 리포트 (자산별 MV/LV/도매할인/회수율/권장 LTV)
- `reports/asset_scores.json` — 금융기관 PoC API 응답과 같은 형태의 구조화 데이터

## 4개 가격 레이어가 전부 하나의 원장에 쌓인다

| 레이어 | 원장 이벤트 | 시뮬레이션 소스 |
|---|---|---|
| ① 중고 거래 시세 (retail) | `external_comp` | 주간 시세 시계열 (KREAM/Chrono24 모사, 랜덤워크+추세) |
| ② 매입/위탁 호가 (wholesale) | `buyer_quote` (sale) | 바이어 매입 견적 — **Liquidation Value 직접 관측치** |
| ③ 담보 거래 가치 | `backfill_appraisal` / `backfill_loan` | 파트너 전당포 과거 장부 (감정가·대출액·LTV) |
| ④ 회수율 | `backfill_liquidation` | 유질 처분가·소요일·비용 → 회수율 실측 |

주간 배치(`metrics.py`)가 원장에서 분위수 통계로 Asset Score를 산출한다:
MV(P50) · LV(P50/P25) · Bid Depth · Bid Spread · 변동성 · MAPE · 도매할인율 · 회수율 · 처분소요일 · **권장 LTV** (= P10 호가 × (1−처분비용) ÷ MV — "최악 분위 호가로 처분해도 원금이 회수되는 비율").

## 1차 단계(자산 식별·상태판별·정가품 판별)가 왜 결정적인가 — 정량 확인

모든 가격 이벤트는 1차 단계가 결정한 canonical_asset_id에 귀속된다.
여기서 틀리면 이후 모든 데이터가 잘못된 서랍에 들어간다.
`--compare`는 동일 거래량·동일 seed(5개 평균)에서 식별 정확도만 바꿔 그 영향을 측정한다:

```
식별정확도 | 오염 이벤트 | MAPE  | Spread | 평균 권장LTV
    85%   |    5.0%    | 18.0% | 43.7%  |   55.0%
    95%   |    1.6%    | 16.0% | 34.4%  |   57.4%
    99%   |    0.3%    |  9.0% | 31.2%  |   59.0%
```

식별 정확도가 오를수록: 오염 이벤트(잘못된 자산에 귀속된 견적/성사가)가 1/17로 줄고,
추정오차(MAPE)가 절반이 되며, 스프레드가 좁아지고, **같은 데이터로 더 높은 LTV를
안전하게 제시할 수 있다.** 즉 식별 정확도는 곧 금융 한도의 상한이다.

`identify.py`에 실서비스용 Gemini 폐쇄형 분류(카탈로그 매칭) 프롬프트 구조가 정의되어 있다 —
가격 필드가 아예 없는 JSON 스키마로, 식별·상태·정가품 플래그만 출력한다.

## 파일 구성

```
schema.sql        원장 DDL (asset_master / asset_instance / valuation_event / metric_snapshot)
catalog_seed.csv  카노니컬 자산 사전 샘플 22개 모델 (실서비스: 상위 200개로 확장)
identify.py       1차 단계 — 식별·상태·정가품 (mock + Gemini 폐쇄형 분류 구조)
simulate.py       거래 시뮬레이터 (4개 가격 레이어 이벤트 생성, sim_truth 정답지 기록)
metrics.py        주간 배치 — Asset Score 분위수 산출
report.py         리포트 생성 + 1차 단계 오염도 분석
run.py            시뮬레이션 진입점
analyze.py        ★ 분석 엔진 + CLI (자산 입력 → Asset Score 산출)
app.py            ★ 분석 프로그램 웹 앱 (+ PoC JSON API)
ingest.py         ★ 실데이터 입력 (견적·성사가·백필 CSV, 금 시세)
dashboard.py      웹 대시보드 생성 (dashboard_template.html 사용)
```

## 시뮬레이션 → 정식 개발 전환 시 매핑

| 프로토타입 | 정식 개발 |
|---|---|
| SQLite | Supabase (Postgres) — DDL 거의 동일 |
| `identify_mock` | Gemini 폐쇄형 분류 (`GEMINI_CLOSED_SET_PROMPT`) + 유저 확인 폴백 UI |
| `simulate.py`의 이벤트 생성 | 비교견적·자산수첩 API의 기록 훅 (구현 스펙 §3.1) |
| 백필 생성기 | 파트너 전당포 엑셀 템플릿 import |
| `sim_truth` 정답지 | 삭제 (시뮬레이션 전용) — 대신 유저 확인·바이어 검수 결과가 라벨이 됨 |
| `reports/asset_scores.json` | 금융기관 PoC API 응답 |

## 시뮬레이션 가정값 (검증 대상 — 실데이터로 교체할 것)

도매할인율(시계 15%/가방 25%/주얼리 22%), 등급 계수(S 1.08/A 1.00/B 0.88/C 0.72),
디폴트율 15%, 가품 출현율 2%, 판매 전환율 60% 등은 전부 가정이다.
**프로토타입의 목적은 이 값들이 맞다는 게 아니라, 이 값들을 실측으로 채워 넣을
그릇(스키마·산식·플로우)이 작동함을 확인하는 것이다.**
