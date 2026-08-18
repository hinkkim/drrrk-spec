# DRRRK × Shorooq IR Deck — Final Restructure Report

- **작업일:** 2026-08-18
- **대상 파일:** Figma Slides `0jV9ejKiqJNpR6mpKhtUeO` (DRRRK Shorooq IR Deck)
- **원본 기준:** `[Shorooq] DRRRK_IR_26.08.13(1).pdf` (22p) + Figma 최신 장표 (Addressable Market, 신규 Proof)

## A. Final Main Deck (Cover + 01–20)

Figma 슬라이드 그리드를 6개 Row로 재구성했다. 발표 순서 = Row 순서.

| Row | 구성 |
|---|---|
| Main ㅣ Cover & Market (01–04) | Cover · 01 Thesis · 02 Problem · 03 Market · 04 Addressable Market |
| Main ㅣ Engine & Proof (05–11) | 05 Solution · 06 Why Transaction(신규) · 07 Transaction Proof · 08 Liquidity Proof(신규) · 09 Proprietary Data · 10 Asset Intelligence(신규) · 11 Financial Application |
| Main ㅣ Business & Global (12–16) | 12 Business Model · 13 Why Korea · 14 Why UAE · 15 Korea→UAE · 16 UAE Entry |
| Main ㅣ Plan & Vision (17–20) | 17 18M Milestone · 18 Team · 19 Funding · 20 Vision · Thank You(비번호) |
| Appendix | TOC(삭제 처리) · Financial Ecosystem · Liquidity Network/Dealer OS · Collective Asset Data Network · Revenue KPI 2026 — 전부 발표 흐름에서 skip 처리 |
| Original Backup | 수정 전 원본 10장 복제본 (skip 처리) |

## C. Change Log

| Final Slide | Original Source | Action |
|---|---|---|
| Cover | 기존 p1 | Keep |
| 01 Thesis | 기존 p3 | Move / 섹션명 "THESIS ㅣ The Next Financeable Asset Class"로 변경 |
| 02 Problem | 기존 p5 (Financial Blind Spot) | Move(Market 앞으로) / 헤드라인·서브카피 교체. "Market liquidity exists. Finance-grade, asset-level liquidity intelligence does not." 추가 |
| 03 Market | 기존 p4 | Modify — 시장 숫자 전면 재검산(아래 Numeric QA) + 출처 footnote 추가, 헤드라인 "이 자산들은 이미, 전 세계에서 거대하게 거래되고 있습니다."로 교체 |
| 04 Addressable Market | Figma 최신 SOM 1.4조+→SAM 19조→TAM 55조+ 장표 | Keep (재사용, 무수정) |
| 05 Solution | 기존 p6 (What We Build ①) | Modify — 헤드라인 "우리는 실제 거래를 통해, 금융이 보지 못했던 자산 데이터를 만듭니다." |
| 06 Why Transaction | 신규 제작 | New — Asset Owner ㅣ DRRRK Liquidity Network ㅣ Professional Dealer 3단 구조, "Transactions are economically valuable before they are informationally valuable." |
| 07 Transaction Proof | Figma 최신 Proof 장표 (GMV 128억+, 매출 12.6억+, 312 active dealers, 실거래 퍼널) | Keep (재사용, 무수정) |
| 08 Liquidity Proof | 신규 제작 | New — 실제 수치(312 / 28% / 500+ / 481 + 퍼널)만 사용, 미확보 지표는 [DATA REQUIRED] |
| 09 Proprietary Data | 기존 p14 (Why We Win ① Data Advantage) | Modify — "우리는 가격을 수집하는 것이 아니라, 실제 거래 결과를 연결합니다." + Closed-loop 프레이밍 |
| 10 Asset Intelligence | 신규 제작 | New — Transaction Outcomes → 예측 출력, OBSERVED TODAY / IN DEVELOPMENT / TARGET OUTPUT 상태 구분 |
| 11 Financial Application | 기존 p8 (Asset Report) | Modify — 헤드라인 "이번 18개월간 … 검증합니다", ILLUSTRATIVE PROTOTYPE 배지 오버레이, 예시값 명시 |
| 12 Business Model | 기존 p16/17 (NOW·NEXT·SCALE) | Move (기존 NOW PROVEN/NEXT/SCALE 라벨 유지) |
| 13 Why Korea | 기존 p13 | Move |
| 14 Why UAE | 기존 p14 | Move |
| 15 Korea→UAE | 기존 p12 (Global Data Advantage, Rolex) | Move — "자산의 데이터는 국경을 넘습니다" 프레임 그대로 사용 |
| 16 UAE Entry | 기존 p15 (Localization) | Move (DMCC/Tradeflow는 이미 Potential 표기됨) |
| 17 18M Milestone | 기존 p18 | Modify — XX,XXX+/XXM+/₩XXX억+ 미완성 placeholder 위에 [TARGET REQUIRED] 패치 오버레이 |
| 18 Team | 기존 p19-20 | Move |
| 19 Funding | 기존 p19 (Funding Plan 20억, 40/35/25) | Move — 이미 Proof-gate 구조(Transaction/Intelligence/Financial Proof)로 구성돼 있어 유지 |
| 20 Vision | 기존 p21 | Modify — "Not a traditional lender — the intelligence & infrastructure layer…" 정의 문구 추가 |
| Thank You | 기존 p22 | Keep — 비번호 클로징 프레임 |

**Appendix로 이동:** TOC(발표 skip), What We Build ③ Financial Ecosystem(중복 — 서브카피를 검증 시제로 수정 완료), Liquidity Network/Dealer OS 제품 장표, Collective Asset Data Network(실증 부족), Revenue KPI 2026(미래 목표 수치).

## Numeric QA (03 Market)

기존 수치가 덱 자체 환율 기준(1 USD = ₩1,350)과 인용 소스 양쪽 모두와 불일치하여, 소스 기반 수치로 교체:

| 카드 | 기존 (오류) | 수정 후 | 근거 |
|---|---|---|---|
| 금 | 720조원 (USD 4,800B) — $4.8T×1,350은 6,480조로 계산 불일치 | **516조원** (USD 382B · 2024 연간 수요) | World Gold Council, Gold Demand Trends FY2024 |
| 럭셔리 시계 | 144조원 / "Pre-owned 49조 (USD 338/2023)" — 단위 누락 | **36조원** (Pre-owned · EUR 25B · 2022), 2033E 약 115조원(EUR 79B) | Morgan Stanley × LuxeConsult |
| 중고 럭셔리 | 701조원 (USD 467B) — 신품 럭셔리 전체 시장 수치로 추정됨 | **66조원** (EUR 45B · 2023), 신품의 12% 규모 | Bain & Company, Second-hand Luxury |

환산 기준: 1 USD = ₩1,350 · 1 EUR = ₩1,460 (2025.05) — 04 Addressable Market 장표와 동일 기준. 슬라이드 하단에 출처 footnote 추가.

## D. Missing Data List ([DATA REQUIRED] / [TARGET REQUIRED])

**08 Liquidity Proof — [DATA REQUIRED] 5건:**
- Bids / Asset
- % Assets with 3+ Bids
- Median Time to First Bid
- Median Time to Transaction
- Seller Acceptance Rate

**17 18M Milestone — [TARGET REQUIRED] 3건:**
- Asset Applications 목표 (기존 XX,XXX+)
- Asset Data Points 목표 (기존 XXM+)
- Financial Volume 목표 (기존 ₩XXX억+)

**재검증 권장:**
- 03 Market의 CAGR 표기 중 기존 유지분(중고 럭셔리 관련) 원출처 확인
- 07 Transaction Proof의 9,810→481 수치는 최신 Figma 장표의 퍼널(9,810→3,256→1,024→481)을 그대로 재사용 — 기간/코호트 정의 내부 확인 권장

## 편집 가능 재구축 (2차 작업)

플래튼 이미지였던 Main Deck 10장을 **네이티브 편집 가능 슬라이드로 재구축**해 각 원본 바로 뒤에 배치했다.
원본 이미지 장표는 보존하되 발표 흐름에서 skip 처리 — 현재 발표 플로우는 전부 편집 가능한 장표로만 구성된다.

| 슬라이드 | 원본 (skip) | 편집본 노드 ID | 비고 |
|---|---|---|---|
| 04 Addressable Market | 6293:246 | `8239:133` | SOM/SAM/TAM 카드 + 출처·정의 각주 전부 라이브 텍스트 |
| 07 Transaction Proof | 6293:251 | `8241:140` | KPI 2행 + 실거래 퍼널 + 이탈 사유 + 하단 메시지 |
| 12 Business Model | 6265:210 | `8243:133` | 상태 칩을 PROVEN / VALIDATING·THIS ROUND / VISION으로 정비 |
| 13 Why Korea | 6261:187 | `8244:133` | 3 스탯 카드 + 출처 각주 |
| 14 Why UAE | 6262:192 | `8244:181` | 기존 '약 66조원($10.0B)' 환율 불일치 → **13.5조원($10.0B)** 정정 |
| 15 Korea→UAE | 6260:182 | `8248:133` | 헤드라인 "Asset Identity Travels. Risk Is Local." + Rolex 사진 크롭 재사용 |
| 16 UAE Entry | 6263:197 | `8250:133` | DMCC/Tradeflow POTENTIAL 명시 + FROM KOREA 사진 크롭 |
| 17 18M Milestone | 6267:216 | `8245:133` | Three Proof Gates 구조(질문 중심) + [TARGET REQUIRED] 네이티브 |
| 19 Funding | 6274:227 | `8246:133` | '각 자금이 제거하는 리스크' 전면 배치 |
| 20 Vision | 6272:221 | `8250:192` | 금고 이미지 크롭 + not-a-lender 정의 네이티브 포함 |

사진 자산(롤렉스·자산 사진·금고)은 원본 플래튼 이미지를 클리핑 프레임으로 크롭해 재사용 — 재촬영/재생성 없음.

## 기술적 제약 (알아둘 것)

1. **Pretendard 폰트가 원격 편집 환경에서 로드 불가** (로컬 설치 폰트). 수정·신규 텍스트는 Pretendard의 모체인 **Noto Sans KR**로 작성됨. 디자이너가 Figma에서 해당 텍스트를 일괄 선택해 Pretendard로 되돌리면 완전히 일치함 (수정 노드는 Original Backup row와 비교 가능).
2. 이미지로 플래튼된 장표(12–17, 19–20번 등)는 내부 카피 수정이 불가 — 오버레이(배지·패치·문구)로 처리. 이미지 내부의 구 페이지 번호(우하단)는 남아 있음.
3. 원본은 전부 "Original Backup" row에 보존 (skip 처리). 파괴적 삭제 없음.
