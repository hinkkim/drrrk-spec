# 드르륵 GTM 이벤트 명세 (Canonical)

> 이 문서가 **단일 기준(SSOT)** 입니다. GA4 property `drrrk.ai.kr` (`properties/499270625`) 기준.
> 성과 분석 시 매번 이 문서로 이벤트 정의를 먼저 확인한 뒤 수치를 해석합니다.
>
> 최종 확인: 2026-07-31

---

## 1. 이벤트 정의

### 감정 (AI 시세조회)

#### `ai_appraisal_start`
| 항목 | 내용 |
|---|---|
| 발화 | 홈(`/`)에서 AI 감정 제출 시 (이미지/텍스트/혼합 모두) |
| 파라미터 | `input_mode` (`image` \| `text` \| `both`), `image_count` |
| 규칙 | 연타 가드로 1회 보장 |

#### `ai_appraisal_complete`
| 항목 | 내용 |
|---|---|
| 발화 | 감정 시세 결과 화면 표시 시 |
| 파라미터 | `category_id`, `brand_name`, `model_name` |
| 규칙 | 감정 세션당 1회. 스펙 수정 후 재진입해도 재발화 없음. **공유 링크(`/ai-result/[id]`)는 미발화** |

> **"시세조회" 지표는 이 두 이벤트로 정의합니다.**
> - 시세조회 시도 = `ai_appraisal_start`
> - 시세조회 완료 = `ai_appraisal_complete` ← 광고 전환 목표(KPI)로 사용

---

### 판매

#### `listing_start`
| 항목 | 내용 |
|---|---|
| 발화 | 판매 등록 시작 시 (deal/drop 공통, 진입당 1회) |
| 파라미터 | `entry_source` = `direct`(직접) \| `ai_appraiser`(감정 결과 경유 폼 진입) \| `ai_report`(리포트 코드) \| `ai_auto`(감정 결과에서 즉시 등록) \| `asset_book`(자산수첩 판매) |
| 규칙 | 폼 스텝 이동 / 완료 화면 진입 시 재발화 없음 |

#### `listing_photo_upload`
| 항목 | 내용 |
|---|---|
| 발화 | 판매 폼에서 **사진 신규 업로드 성공 시에만** |
| 파라미터 | `photo_count` |
| 규칙 | AI 감정 사진 자동 재사용(prefill) 미발화, 업로드 실패 시 미발화 |

#### `listing_submit`
| 항목 | 내용 |
|---|---|
| 발화 | 판매 등록 제출 **성공** 시 (실패 시 미발화) |
| 파라미터 | `sales_type`(`DEAL`\|`DROP`), `ai_source`(`WRITE`\|`AI_APPRAISER`\|`AI_REPORT`\|`ASSET_BOOK`), `category_id` |
| 커버 경로 | 수동 confirm 제출 / AI 자동 제출 / AI add-photos 제출 / 감정 결과 즉시 등록 / 자산수첩 판매(`sellAsset`, 호출처 3곳) |

---

### 견적

#### `bid_view`
| 항목 | 내용 |
|---|---|
| 발화 | 판매자 상품 상세에서 견적 목록 노출 시 (`biddingList > 0`) |
| 파라미터 | `product_id`, `bid_count` |
| 규칙 | 페이지 뷰당 1회 (refetch에도 재발화 없음) |

#### `bid_accept`
| 항목 | 내용 |
|---|---|
| 발화 | 판매요청(낙찰 확정) **성공** 시 (버튼 클릭이 아닌 mutation 성공 시점, deal/drop 모두) |
| 파라미터 | `product_id`, `bid_id`, `price`, `sales_type` |
| 규칙 | **최초 낙찰만.** 조정가 수락은 미계측 (한 거래 accept 2회 방지) |

---

### 자산수첩

#### `asset_notebook_add`
| 항목 | 내용 |
|---|---|
| 발화 | 자산 등록 성공 시 (수동 폼 + 감정 결과 "자산수첩에 담기" 직접 생성 모두) |
| 파라미터 | `asset_id`, `category`, `source`(`manual`\|`ai_result`) |

#### `asset_notebook_price_check`
| 항목 | 내용 |
|---|---|
| 발화 | 자산 상세 진입 시 (개별 자산 시세 확인) |
| 파라미터 | `asset_id`, `category` |
| 규칙 | 뷰당 1회. 내 자산 탭 뷰(총 자산 노출)는 페이지뷰성이라 제외하고 **상세 진입**으로 정의 |

#### `asset_notebook_to_loan` — 크로스셀 핵심
| 항목 | 내용 |
|---|---|
| 발화 | 자산 상세의 담보대출 버튼 클릭 시 (하단 CTA + 시세 리스트 2곳) |
| 파라미터 | `asset_id`, `category` |
| 규칙 | "준비 중" alert 상태에서도 **클릭 시점 발화** (수요 측정). 목록 카드 버튼은 disabled라 대상 아님 |

---

## 2. 요약표

| 이벤트 | 그룹 | 발화 시점 | 1차 KPI |
|---|---|---|---|
| `ai_appraisal_start` | 감정 | 홈에서 AI 감정 제출 (연타 가드) | |
| `ai_appraisal_complete` | 감정 | 시세 결과 화면 표시 (세션당 1회, 공유 링크 제외) | ✅ 광고 전환 |
| `listing_start` | 판매 | 판매 등록 시작 (`entry_source` 5종) | |
| `listing_photo_upload` | 판매 | 사진 신규 업로드 성공 (재사용 미발화) | |
| `listing_submit` | 판매 | 등록 성공 5개 경로 전부 | ✅ 공급 |
| `bid_view` | 견적 | 판매자 상세에서 견적 목록 노출 (뷰당 1회) | |
| `bid_accept` | 견적 | 판매요청(낙찰) 성공 (deal/drop) | ✅ 거래 |
| `asset_notebook_add` | 자산수첩 | 자산 등록 성공 (수동 + AI 결과 담기) | |
| `asset_notebook_price_check` | 자산수첩 | 자산 상세 진입 | |
| `asset_notebook_to_loan` | 자산수첩 | 자산 상세 담보대출 버튼 클릭 (수요 측정) | ✅ 크로스셀 |

---

## 3. 분석 시 주의사항 (해석 함정)

1. **`ai_appraisal_complete`는 공유 링크에서 미발화** → 공유를 통한 바이럴 유입은 시세조회 지표에 안 잡힘. 시세조회 성과를 과소평가할 수 있음.
2. **`ai_appraisal_complete`는 감정 세션당 1회** → 스펙 수정 후 재조회는 카운트 안 됨. 사용자당 실제 조회 횟수 ≠ 이벤트 수.
3. **`listing_photo_upload`는 AI 감정 사진 재사용 시 미발화** → AI 경유 등록이 늘수록 이 이벤트는 자연 감소. 감소를 이탈로 오독하지 말 것.
4. **`bid_accept`는 최초 낙찰만** → 조정가 수락 거래는 누락. 실거래 수 > `bid_accept`.
5. **`bid_view`는 페이지 뷰당 1회** → 같은 판매자가 여러 번 봐도 세션 내 반복 발화됨(페이지 뷰 기준). 유니크 판매자 수와 다름.
6. **`listing_start` → `listing_submit`은 서로 다른 진입 단위** → `listing_start`는 진입당 1회, `listing_submit`은 성공당 1회. 재진입 이탈자는 분모에 안 잡힘.

---

## 4. 계측 갭 (2026-07-31 확인)

| 이슈 | 상태 | 영향 |
|---|---|---|
| **`utm_content` 미설정** | ❌ | GA4에서 **광고 소재별 전환 분리 불가**. 현재 캠페인 단위(`conversion_ai`, `organic_boost`, `120248862565110529`)까지만 구분됨. 소재 성과 판단은 Meta 대시보드에 의존 중 |
| **`asset_notebook_to_loan` 발화 0건** | ❌ | 45일간 0건. 크로스셀 수요 측정 불가 (태그 미배포 또는 진입 경로 자체 부재) |
| **`ai_appraisal_*` 계측 시작일 2026-07-03** | ⚠️ | 07-03 이전 데이터 없음. 6월 광고 성과와 직접 비교 불가 |
| **Meta Ads 데이터 파이프라인** | ❌ | 07-13 이후 미연결. 광고비/노출/CTR 자동 수집 불가 |
