# Pretendard 복원용 노드 리스트

원격 편집 환경에서 Pretendard 로드가 불가해, 수정·신규 텍스트는 전부 **Noto Sans KR**로 작성됨.
웨이트는 원본 체계와 동일하게 맞춰 두었으므로(헤드라인 Regular · 섹션 라벨 Medium · 강조 Bold), **폰트 패밀리만 Noto Sans KR → Pretendard로 동일 웨이트 스왑하면 복원 완료**된다.

## 한 번에 되돌리는 법 (권장)

1. Figma 플러그인 **Font Replacer** (또는 Batch Font Replace) 실행
2. `Noto Sans KR Regular → Pretendard Regular`, `Noto Sans KR Medium → Pretendard Medium`, `Noto Sans KR Bold → Pretendard Bold` 3건 스왑
3. 아래 "스왑 후 선택 조정" 3개 노드만 SemiBold로 내리면 원본과 완전 일치

수동으로 할 경우: 각 슬라이드에서 텍스트 하나 선택 → `Edit ▸ Select all with same ▸ Font` → 패밀리 변경 (웨이트별 반복).

## 스왑 후 선택 조정 (원본이 SemiBold였던 노드)

| 노드 ID | 내용 | 현재 | 원본 스타일 |
|---|---|---|---|
| `6248:366` | 516조원 | Noto Bold 40 | Pretendard SemiBold 30 / 조원 Medium 24 |
| `6248:767` | 36조원 | Noto Bold 40 | Pretendard SemiBold 30 / Medium 24 |
| `6248:792` | 66조원 | Noto Bold 40 | Pretendard SemiBold 30 / Medium 24 |

※ 현재 40px Bold는 의도적 강조(숫자 가독성)이므로 그대로 둬도 무방. 원본 충실 복원 시에만 조정.

## 전체 노드 인벤토리 (Noto Sans KR 사용 노드 · Backup row 제외)

### 01 Thesis (slide `6248:370`) — 1개
| 노드 ID | 텍스트 | 현재 스타일 | 목표 Pretendard |
|---|---|---|---|
| `6248:374` | THESIS ㅣ The Next Financeable Asset Class | Medium 20 | Medium 20 |

### 02 Problem (slide `6234:285`) — 3개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `6248:137` | PROBLEM ㅣ Financial Blind Spot | Medium 20 | Medium 20 |
| `6248:139` | 거대한 실물자산은, / 아직 충분히… | Regular 40 | Regular 40 |
| `6248:141` | 가치는 이미 존재하고… + En 문장 | Regular 24 | Regular 24 |

### 03 Market (slide `6248:203`) — 16개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `6248:208` | MARKET ㅣ A Massive Existing… | Medium 20 | Medium 20 |
| `6248:210` | 이 자산들은 이미, / 전 세계에서… | Regular 40 | Regular 40 |
| `6248:345` | 글로벌 금 시장 | Medium 24 | Medium 24 |
| `6248:366` | 516조원 | Bold 40 | SemiBold(위 참조) |
| `6248:367` | (연간 수요 · USD 382B · 2024) | Regular 15 | Regular 15 |
| `6248:786` | (4,974t · WGC) | Regular 15 | Regular 15 |
| `6248:368` | 2024 사상 최대 수요 | Bold 20 | Bold 20 |
| `6248:767` | 36조원 | Bold 40 | SemiBold(위 참조) |
| `6248:768` | (Pre-owned · EUR 25B · 2022) | Regular 15 | Regular 15 |
| `6248:769` | 2033E 약 115조원 | Bold 18/20 | Bold 20 |
| `6248:787` | (EUR 79B · LuxeConsult) | Regular 15 | Regular 15 |
| `6248:792` | 66조원 | Bold 40 | SemiBold(위 참조) |
| `6248:793` | (EUR 45B · 2023 · Bain) | Regular 15 | Regular 15 |
| `6248:794` | 4년간 약 2배 성장 | Bold 20 | Bold 20 |
| `6248:803` | (신품 시장의 12% 규모) | Regular 15 | Regular 15 |
| `8223:133` | Source: World Gold Council… (footnote) | Regular 13 | Regular 13 |

### 05 Solution (slide `6236:290`) — 2개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `6248:146` | SOLUTION ㅣ Transactions Generate… | Medium 23 | Medium 20/23 |
| `6248:148` | 우리는 실제 거래를 통해,… | Regular 40 | Regular 40 |

### 09 Proprietary Data (slide `2023:695`) — 3개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `2023:702` | PROPRIETARY DATA ㅣ Closed-loop… | Medium 20 | Medium 20 |
| `2023:704` | 우리는 가격을 수집하는 것이 아니라… | Regular 40 | Regular 40 |
| `2023:762` | 공개 시세가 아니라, 입찰·검수·실거래… | Regular 24 | Regular 24 |

### 11 Financial Application (slide `6239:314`) — 5개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `6248:184` | FINANCIAL APPLICATION ㅣ Illustrative… | Medium 23 | Medium 20/23 |
| `6248:186` | 이번 18개월간, 거래 데이터가… | Regular 40 | Regular 40 |
| `6248:188` | Asset Intelligence가 검증되면… | Regular 24 | Regular 24 |
| `8230:135` | ILLUSTRATIVE PROTOTYPE (배지) | Bold 20 | Bold 20 |
| `8230:136` | ㅣ 수치는 예시값 (Target Output) | Medium 16 | Medium 16 |

### APPENDIX Financial Ecosystem (slide `6236:301`) — 1개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `6248:168` | 축적된 거래 결과를 금융기관이… | Regular 24 | Regular 24 |

### 17 18M Milestone 오버레이 (slide `6267:216`) — 3개
`8230:138`, `8230:140`, `8230:142` — [TARGET REQUIRED] — Bold 24 → Bold 24

### 20 Vision 오버레이 (slide `6272:221`) — 2개
| 노드 ID | 텍스트 | 현재 | 목표 |
|---|---|---|---|
| `8230:143` | Not a traditional lender — … | Bold 18 | Bold 18 |
| `8230:144` | 직접 대출하는 은행이 아니라… | Regular 15 | Regular 15 |

### 신규 슬라이드 3장 — 전 노드 Noto Sans KR (동일 웨이트로 스왑하면 끝)

**06 Why Transaction (slide `8227:133`) — 34개**
섹션/카드라벨/스텝번호·스텝명/하단 En 메시지 = Bold (`8227:134,136,139,140,153,154,156,157,160,161,164,165,168,169,173,174,189`) · 불릿 = Medium (`8227:145,148,151,179,182,185,188`) · 설명·캡션 = Regular (`8227:135,137,141,158,162,166,170,171,175,190`)

**08 Liquidity Proof (slide `8228:133`) — 41개**
KPI 숫자·퍼널 숫자·화살표·라벨·하단 메시지 = Bold (`8228:134,136,139,141,142,145,146,149,150,153,154,158,160,162,164,166,168,170,174,177,180,183,186,189,191`) · 퍼널 캡션·지표명 = Medium (`8228:159,163,167,171,178,181,184,187,190`) · 서브카피·주석 = Regular (`8228:135,137,143,147,151,155,172`)

**10 Asset Intelligence (slide `8229:134`) — 39개**
섹션/타이틀/항목명/상태칩/화살표/하단 = Bold (`8229:135,137,140,141,143,146,149,152,155,157,161,164,167,170,173,176,179,182,185,188,192,196,200,202`) · 설명 = Regular (`8229:136,138,144,147,150,153,156,162,168,174,180,186,193,197,201`)

---
합계 **150개 노드 / 11개 슬라이드**. 모두 패밀리 스왑만으로 복원되도록 웨이트를 원본 체계에 맞춰 정리해 둔 상태.
