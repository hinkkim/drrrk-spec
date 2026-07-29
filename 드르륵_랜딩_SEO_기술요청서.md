# 드르륵 랜딩 업데이트 — 기술 SEO 요청서

| 항목 | 내용 |
|---|---|
| 요청일 | 2026-07-29 |
| 대상 | 프론트엔드 개발 |
| 관련 자료 | 랜딩화면 콘텐츠 품질 업데이트 디자인 덱(7/29), 랜딩 시안 HTML(`드르륵_랜딩_시안_v3.html`) |
| 대상 페이지 | `/`(랜딩), FAQ, 향후 `/price/*`(시세 페이지) |

## 배경과 목표

이번 랜딩 업데이트로 콘텐츠(FAQ 9문항, 정책 수치, 카테고리·브랜드 키워드)가 크게 보강됐습니다. 다만 현재 사이트는 React SPA(클라이언트 렌더링)라서 **서버 응답 HTML에 본문이 없으면 이 콘텐츠가 검색엔진에 노출되지 않습니다.** 이번 배포에 아래 기술 항목을 함께 반영해 주세요.

우선순위는 P0 → P4 순서입니다. **P0과 P1만 이번 스프린트에 확보돼도 효과의 대부분을 잡습니다.** P2~P4는 후속 티켓으로 나눠도 됩니다.

---

## P0. 프리렌더(SSG) 또는 SSR — 이번 배포의 핵심

**요청:** 랜딩(`/`), FAQ, 향후 시세 페이지(`/price/*`)는 서버가 **완성된 HTML**로 응답하게 해주세요. JS 실행 전에도 본문 텍스트가 존재해야 합니다.

**이유:** 네이버 크롤러(Yeti)는 JS 렌더링 능력이 구글보다 훨씬 약해서, CSR 상태로는 네이버 검색 노출이 사실상 불가능합니다. 구글도 렌더링 큐 지연으로 색인이 늦어집니다.

**구현 방식은 재량에 맡깁니다.** (랜딩은 내용 변경이 잦지 않으므로 풀 SSR 없이 빌드 타임 프리렌더로 충분합니다.)
- Next.js 등 프레임워크 전환(SSG)
- 현재 빌드에 프리렌더 단계 추가(vite-plugin-prerender, react-snap 등)
- 정적 HTML을 별도 생성해 SPA rewrite보다 먼저 서빙(Vercel은 파일시스템 매칭이 rewrite에 우선)

**검수 기준:**
```bash
curl -s https://drrrk.ai.kr | grep "지금 팔면 얼마일까요"
curl -s https://drrrk.ai.kr | grep "중고 명품 시세는 어떻게 정해지나요"
```
- [ ] 위 두 명령이 모두 결과를 반환한다 (h1과 FAQ 본문이 서버 응답에 포함)
- [ ] 브라우저 "페이지 소스 보기"에서 FAQ 9문항 텍스트가 보인다

---

## P1. 문서 메타 태그

**요청:** 아래 태그를 서버 응답 HTML의 `<head>`에 포함해 주세요. (JS로 늦게 주입하면 카카오톡/크롤러가 못 읽습니다.)

```html
<html lang="ko">

<title>사진 한 장으로 명품·중고 시세조회, 바이어 비교견적 | 드르륵</title>
<meta name="description" content="가입 없이 사진 한 장으로 가방·시계·주얼리·전자기기 시세를 바로 확인하세요. 원할 때 여러 바이어의 견적을 한 번에 비교해 좋은 조건으로 판매할 수 있어요.">
<link rel="canonical" href="https://drrrk.ai.kr/">

<!-- 공유 미리보기 (카카오톡·슬랙 등) -->
<meta property="og:type" content="website">
<meta property="og:title" content="내 자산, 지금 팔면 얼마일까요? | 드르륵">
<meta property="og:description" content="가입 없이 사진 한 장으로 시세 확인, 여러 바이어 견적 비교까지.">
<meta property="og:url" content="https://drrrk.ai.kr/">
<meta property="og:image" content="https://drrrk.ai.kr/og-image.png">
<meta property="og:site_name" content="드르륵">
<meta name="twitter:card" content="summary_large_image">
```

**참고:**
- `og-image.png`는 **1200×630 이미지 별도 제작 필요** (디자인 측에서 전달 예정 — 준비 전까지는 로고+옐로 배경 임시본으로 배포 가능)
- 페이지가 늘어나면(FAQ 분리, `/price/*`) **페이지마다 title / description / canonical / og:url이 달라야 합니다.** 전 페이지 동일 title은 색인 품질을 떨어뜨립니다.

**검수 기준:**
- [ ] `curl -s https://drrrk.ai.kr | grep og:image` 결과가 존재
- [ ] 카카오톡 나에게 보내기로 URL 공유 시 제목·설명·이미지가 표시됨 (캐시 갱신: https://developers.kakao.com/tool/debugger/sharing)

---

## P2. 구조화 데이터 (JSON-LD)

**요청:** 아래 두 블록을 랜딩 `<head>` 또는 `<body>` 말미에 `<script type="application/ld+json">`으로 포함해 주세요.

### 2-1. FAQPage — 랜딩 FAQ 9문항 전체

대상 문항(질문·답변 텍스트는 시안 HTML의 FAQ 섹션과 **완전히 동일해야** 합니다 — 화면에 없는 내용을 마크업에 넣으면 정책 위반):

1. 중고 명품 시세는 어떻게 정해지나요?
2. 사진 한 장만으로 정확한 시세를 알 수 있나요?
3. 가입하지 않아도 이용할 수 있나요?
4. 바이어마다 견적이 다른 이유는 무엇인가요?
5. 견적은 얼마나 기다려야 하나요?
6. 견적 기간을 놓치면 어떻게 되나요?
7. 견적을 받으면 반드시 판매해야 하나요?
8. 보증서나 구성품이 없어도 판매할 수 있나요?
9. 매입과 담보 대출 중 어떤 게 유리한가요?

형식 예시(1번 문항 — 나머지 8개도 같은 구조로):

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "중고 명품 시세는 어떻게 정해지나요?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "(시안 FAQ의 답변 텍스트 그대로)"
      }
    }
  ]
}
```

### 2-2. Organization + WebSite

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "name": "드르륵",
      "url": "https://drrrk.ai.kr",
      "logo": "https://drrrk.ai.kr/logo.png"
    },
    {
      "@type": "WebSite",
      "name": "드르륵",
      "url": "https://drrrk.ai.kr"
    }
  ]
}
```

### ⚠️ 넣지 말아야 할 것 (중요)

- **`Product` + `offers`, `AggregateRating`, `Review` 마크업은 실거래 데이터가 확보되기 전까지 절대 넣지 마세요.** 현재 화면의 시세·평점·후기는 예시값입니다. 예시값을 구조화 데이터로 선언하면 구글 스팸 정책 위반으로 사이트 전체 리치결과가 제외될 수 있습니다.
- `/price/*` 오픈 시 `BreadcrumbList`는 추가 (이건 안전).

**검수 기준:**
- [ ] https://search.google.com/test/rich-results 에서 FAQPage 오류 0건
- [ ] 화면 FAQ 텍스트와 JSON-LD 텍스트 일치

---

## P3. 마크업·크롤링 위생

**마크업:**
- [ ] `<h1>`은 페이지당 1개 — "내 자산, 지금 팔면 얼마일까요?" / 섹션 제목은 `<h2>`, FAQ 질문은 `<h3>` 또는 `<summary>` 계층 유지
- [ ] FAQ·리뷰·정책 수치(0원/48시간/+3일/5회)는 **이미지가 아닌 실제 텍스트 DOM**으로 구현 (디자인 덱 화면을 이미지로 잘라 넣지 말 것)
- [ ] 모든 `<img>`에 `alt`(키워드 포함 서술형), `width`/`height` 속성(CLS 방지), 가급적 webp + `loading="lazy"` (단, 히어로 첫 화면 이미지는 lazy 제외)
- [ ] 페이지 이동은 `<button>`+JS 라우팅이 아닌 **실제 `<a href>`** (카테고리 → `/price` 등 내부 링크가 크롤러에 보여야 함)

**크롤링 인프라:**
- [ ] `robots.txt` 제공 (전체 허용 + `Sitemap:` 라인)
- [ ] `sitemap.xml` 자동 생성 — 신규 페이지(`/price/*` 등)가 배포 시 자동 포함되는 구조
- [ ] 존재하지 않는 경로는 **실제 HTTP 404** 반환 (SPA 기본 설정은 모든 경로가 200 — soft 404는 색인 품질 저하)
- [ ] `http→https`, `www` 유무 한쪽으로 301 통일

---

## P4. 성능 (Core Web Vitals)

모바일 기준 목표치 — PageSpeed Insights(https://pagespeed.web.dev)로 검수:

| 지표 | 목표 |
|---|---|
| LCP | < 2.5s |
| CLS | < 0.1 |
| INP | < 200ms |

- [ ] 히어로 LCP 요소(이미지/폰트) `<link rel="preload">`
- [ ] 웹폰트는 서브셋 woff2 + `font-display: swap` (Pretendard 사용 시 subset 배포본)
- [ ] JS 번들 코드 스플리팅 — 랜딩 첫 로드에 불필요한 라우트 청크 제외

---

## 배포 직후 할 일 (등록·측정)

1. **Google Search Console** + **네이버 서치어드바이저**(https://searchadvisor.naver.com) 소유 확인 — 확인용 meta 태그 삽입 요청드릴 예정, 이후 두 곳 모두 sitemap 제출. *네이버 쪽을 빼먹기 쉬운데 국내 트래픽에는 필수입니다.*
2. **GA4 + Microsoft Clarity** 스니펫 삽입 — 이탈 분석용 이벤트(스크롤 50%, CTA 탭, 사진 업로드 시작/완료, 견적 등록)는 별도 티켓으로 전달 예정. 이번 배포에 스니펫만 먼저 실려도 됩니다.

---

## 최종 검수 체크리스트 (요약)

```bash
# 1. 프리렌더 확인 — 본문이 서버 응답에 있어야 함
curl -s https://drrrk.ai.kr | grep "지금 팔면 얼마일까요"

# 2. 메타 태그 확인
curl -s https://drrrk.ai.kr | grep -E 'og:image|canonical|description'

# 3. 404 확인 — 200이 아닌 404가 나와야 함
curl -s -o /dev/null -w "%{http_code}" https://drrrk.ai.kr/no-such-page

# 4. 리다이렉트 확인 — 301이 나와야 함
curl -s -o /dev/null -w "%{http_code}" http://drrrk.ai.kr
```

- [ ] P0: view-source에 h1·FAQ 본문 존재
- [ ] P1: title/description/canonical/OG 세트, 카카오톡 미리보기 정상
- [ ] P2: FAQPage + Organization JSON-LD, 리치결과 테스트 통과, **Product/평점 마크업 없음**
- [ ] P3: h1 1개, 텍스트 DOM, img alt/치수, robots.txt, sitemap.xml, 404/301
- [ ] P4: PageSpeed 모바일 LCP<2.5s / CLS<0.1 / INP<200ms
- [ ] 배포 후: GSC·네이버 서치어드바이저 등록 + sitemap 제출

---

## 함께 전달하는 주의사항

- 화면의 시세·거래 건수·평점·후기 텍스트는 **전부 예시값**입니다. 실데이터 연동 전까지 "예시 화면" 라벨을 유지해 주세요.
- 카테고리 섹션의 상품 이미지는 **데모용 임시 이미지**입니다. 실서비스 배포 전 자체 촬영 실물 사진으로 교체 예정이며, 교체 시 alt 텍스트도 실제 브랜드·품목 기준으로 갱신합니다.
