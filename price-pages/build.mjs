#!/usr/bin/env node
/**
 * 품목별 시세 페이지 생성기
 *
 *   node build.mjs            → dist/ 에 정적 HTML 생성
 *   node build.mjs --out www  → 출력 폴더 지정
 *
 * 의존성 없음. Node 18 이상.
 * 데이터 소스와 분리되어 있어 DB든 시트든 items.json 형태로만 뽑아주면 그대로 붙습니다.
 */

import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

/* ── 설정 ────────────────────────────────────────────── */

const CONFIG = {
  // 'ko'    → /price/샤넬-클래식-플랩-미디움   (검색어와 일치, SERP에서 한글로 표시)
  // 'ascii' → /price/chanel-classic-flap-medium (운영상 안전, 복사·붙여넣기 깔끔)
  //           ascii 로 쓰려면 각 item 에 slugEn 필드를 추가하세요.
  slugMode: 'ko',
  base: '/price',
};

/* ── 유틸 ────────────────────────────────────────────── */

const esc = (s = '') =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
           .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const man = (won) => (won / 10000).toLocaleString('ko-KR');
const comma = (n) => Number(n).toLocaleString('ko-KR');

const slugOf = (item) =>
  CONFIG.slugMode === 'ascii' && item.slugEn ? item.slugEn : item.slug;

const urlOf = (item) => `${CONFIG.base}/${slugOf(item)}`;

const ymd = (s) => {
  const [y, m] = s.split('-');
  return `${y}년 ${Number(m)}월`;
};

/* ── 페이지 템플릿 ───────────────────────────────────── */

function page(item, all, meta) {
  const title = `${item.brand} ${item.model} 중고 시세 | 매입가 비교 - ${meta.brandName}`;
  const desc =
    `${item.brand} ${item.model}(${item.spec}) 중고 시세는 ${item.period} 실거래 기준 ` +
    `${man(item.low)}만원~${man(item.high)}만원입니다. 상태 등급별 가격과 매입 시 체크포인트를 확인하고 ` +
    `여러 바이어의 매입 견적을 비교하세요.`;

  const rel = (item.related || [])
    .map((s) => all.find((x) => x.slug === s))
    .filter(Boolean);

  const up = item.delta >= 0;
  const canonical = `${meta.site}${urlOf(item)}`;

  /* 구조화 데이터 —
     Product + offers 는 의도적으로 넣지 않았습니다. 이 페이지는 상품을 파는 페이지가
     아니라 시세를 안내하는 페이지라, 구매 가능한 offer 가 없는 상태에서 Product 마크업을
     붙이면 구조화 데이터 정책 위반으로 리치 결과에서 제외될 수 있습니다.
     실제로 리치 결과를 받을 수 있고 사실에도 부합하는 두 가지만 사용합니다. */
  const ld = [
    {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: '홈', item: meta.site },
        { '@type': 'ListItem', position: 2, name: '시세', item: `${meta.site}${CONFIG.base}` },
        { '@type': 'ListItem', position: 3, name: `${item.brand} ${item.model}`, item: canonical },
      ],
    },
    {
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: (item.faq || []).map((f) => ({
        '@type': 'Question',
        name: f.q,
        acceptedAnswer: { '@type': 'Answer', text: f.a },
      })),
    },
  ];

  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${esc(canonical)}">
<script type="application/ld+json">${JSON.stringify(ld)}</script>
${STYLE}
</head>
<body>
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="/">DRRRK</a>
    <a class="btn btn-y" href="/">내 자산 시세 조회</a>
  </div>
</header>

<main class="wrap">
  <nav class="crumb" aria-label="위치">
    <a href="/">홈</a> <span>›</span>
    <a href="${CONFIG.base}">시세</a> <span>›</span>
    <span aria-current="page">${esc(item.brand)} ${esc(item.model)}</span>
  </nav>

  <h1>${esc(item.brand)} ${esc(item.model)} 중고 시세</h1>
  <p class="stamp">${esc(item.spec)} · ${ymd(meta.updated)} 기준 · ${esc(item.period)} 실거래 ${comma(item.sampleSize)}건</p>

  <section class="hero-price">
    <div class="range">
      <span class="rl">최근 거래 범위</span>
      <strong>${man(item.low)} ~ ${man(item.high)}<em> 만원</em></strong>
    </div>
    <div class="delta ${up ? 'up' : 'down'}">
      ${up ? '▲' : '▼'} ${Math.abs(item.delta)}%
      <span>전월 대비</span>
    </div>
  </section>

  <p class="lead">
    ${esc(item.brand)} ${esc(item.model)}는 ${esc(item.period)} 실거래 기준
    <strong>${man(item.low)}만원에서 ${man(item.high)}만원</strong> 사이에서 거래되고 있습니다.
    아래 범위는 상태 등급과 구성품 유무에 따라 나뉘며, 실제 매입가는 바이어가 실물을 검수한 뒤
    제시하는 견적에서 확정됩니다. 같은 자산이라도 바이어의 재고와 판매 채널에 따라 제안 금액이
    달라지기 때문에, 한 곳의 견적만 보고 결정하기보다 여러 제안을 비교하시는 편이 유리합니다.
  </p>

  <h2>상태 등급별 시세</h2>
  <div class="tablewrap">
    <table>
      <thead><tr><th>등급</th><th>상태</th><th class="r">예상 시세</th></tr></thead>
      <tbody>
        ${item.grades.map((g) => `<tr>
          <td class="g">${esc(g.grade)}</td>
          <td>${esc(g.desc)}</td>
          <td class="r num">${man(g.low)} ~ ${man(g.high)}만원</td>
        </tr>`).join('\n        ')}
      </tbody>
    </table>
  </div>
  <p class="note">등급은 실물 검수 결과에 따라 최종 확정됩니다. 사진만으로는 범위까지만 좁힐 수 있습니다.</p>

  <h2>이 모델의 시세를 가르는 요인</h2>
  <ul class="factors">
    ${item.factors.map((f) => `<li>${esc(f)}</li>`).join('\n    ')}
  </ul>

  <h2>판매 전 확인할 것</h2>
  <ul class="checks">
    ${item.checkpoints.map((c) => `<li>${esc(c)}</li>`).join('\n    ')}
  </ul>

  <h2>즉시팔기와 맡겨팔기, 어느 쪽이 유리한가요?</h2>
  <p>
    바로 현금화가 필요하다면 <strong>즉시팔기(매입)</strong>가 맞습니다. 바이어가 직접 매입하므로
    검수 후 정산까지 걸리는 시간이 짧습니다. 반대로 시간을 두고 더 높은 금액을 노린다면
    <strong>맡겨팔기(위탁)</strong>를 검토해보세요. 판매가 성사될 때까지 기다려야 하지만
    일반적으로 더 높은 금액을 기대할 수 있습니다. 자산을 다시 찾을 계획이 있다면 매도 대신
    담보 대출을 비교해보시는 방법도 있습니다.
  </p>

  <section class="cta">
    <h2>${esc(item.model)}, 지금 얼마인지 확인하세요</h2>
    <p>사진 한 장이면 됩니다. 여러 바이어의 매입 견적을 한 번에 비교할 수 있습니다.</p>
    <a class="btn btn-y btn-lg" href="/">내 자산 시세 조회하기</a>
  </section>

  <h2>자주 묻는 질문</h2>
  <div class="faq">
    ${(item.faq || []).map((f) => `<details>
      <summary>${esc(f.q)}</summary>
      <p>${esc(f.a)}</p>
    </details>`).join('\n    ')}
  </div>

  ${rel.length ? `<h2>함께 많이 조회한 자산</h2>
  <div class="rel">
    ${rel.map((r) => `<a href="${urlOf(r)}">
      <span class="rb">${esc(r.brandEn)}</span>
      <span class="rm">${esc(r.model)}</span>
      <span class="rp num">${man(r.low)} ~ ${man(r.high)}만원</span>
    </a>`).join('\n    ')}
  </div>` : ''}
</main>

<footer class="foot">
  <div class="wrap">
    <p><a href="${CONFIG.base}">전체 시세 목록</a> · <a href="/faq">자주 묻는 질문</a> · <a href="/">홈</a></p>
    <p class="dim">시세는 ${esc(item.period)} 실거래를 기준으로 산출한 참고값이며 실제 매입가와 다를 수 있습니다.
    최종 금액은 바이어 견적 단계에서 확정됩니다.</p>
  </div>
</footer>
</body>
</html>
`;
}

/* ── 허브 페이지 ─────────────────────────────────────── */

function hub(items, meta) {
  const byCat = {};
  for (const it of items) (byCat[it.category] ||= []).push(it);

  const title = `중고 명품·전자기기 시세表 | 브랜드별 매입가 - ${meta.brandName}`.replace('表', '표');
  const desc = `샤넬·롤렉스·에르메스부터 맥북·아이폰까지, 최근 실거래 기준 중고 시세를 브랜드와 모델별로 확인하세요.`;

  const ld = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: '홈', item: meta.site },
      { '@type': 'ListItem', position: 2, name: '시세', item: `${meta.site}${CONFIG.base}` },
    ],
  };

  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${meta.site}${CONFIG.base}">
<script type="application/ld+json">${JSON.stringify(ld)}</script>
${STYLE}
</head>
<body>
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="/">DRRRK</a>
    <a class="btn btn-y" href="/">내 자산 시세 조회</a>
  </div>
</header>

<main class="wrap">
  <nav class="crumb" aria-label="위치">
    <a href="/">홈</a> <span>›</span> <span aria-current="page">시세</span>
  </nav>

  <h1>중고 명품·전자기기 시세</h1>
  <p class="lead">
    최근 실거래를 기준으로 산출한 모델별 시세입니다. 상태 등급별 범위와 판매 전 확인할 점을
    함께 정리했습니다. 실제 매입가는 바이어 견적 단계에서 확정됩니다.
  </p>

  ${Object.entries(byCat).map(([cat, list]) => `<h2>${esc(cat)}</h2>
  <div class="rel">
    ${list.map((r) => `<a href="${urlOf(r)}">
      <span class="rb">${esc(r.brandEn)}</span>
      <span class="rm">${esc(r.model)}</span>
      <span class="rp num">${man(r.low)} ~ ${man(r.high)}만원</span>
    </a>`).join('\n    ')}
  </div>`).join('\n\n  ')}
</main>

<footer class="foot">
  <div class="wrap">
    <p><a href="/faq">자주 묻는 질문</a> · <a href="/">홈</a></p>
    <p class="dim">시세는 참고값이며 실제 매입가와 다를 수 있습니다.</p>
  </div>
</footer>
</body>
</html>
`;
}

/* ── 스타일 (드르륵 브랜드 토큰) ─────────────────────── */

const STYLE = `<style>
  :root{
    --yellow:#FFC93C; --yellow-deep:#F5B800; --yellow-soft:#FFF6DC;
    --ink:#16161A; --ink-2:#3D3D46; --muted:#6E6E78;
    --line:#E9E9EE; --fill:#F4F4F6; --page:#F5F5F7;
    --up:#0E7A47; --down:#B91C1C;
    --sans:'Pretendard','Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',-apple-system,BlinkMacSystemFont,sans-serif;
  }
  *,*::before,*::after{box-sizing:border-box}
  body{margin:0;font-family:var(--sans);color:var(--ink);background:#fff;line-height:1.7;word-break:keep-all;-webkit-font-smoothing:antialiased}
  .wrap{max-width:780px;margin:0 auto;padding-inline:20px}
  a{color:var(--ink)}
  :focus-visible{outline:2px solid var(--yellow-deep);outline-offset:2px}
  .num{font-variant-numeric:tabular-nums}

  .top{border-bottom:1px solid var(--line);position:sticky;top:0;background:rgba(255,255,255,.95);backdrop-filter:blur(12px);z-index:10}
  .top-in{display:flex;align-items:center;justify-content:space-between;min-height:60px;gap:12px}
  .logo{font-weight:800;font-size:18px;letter-spacing:.04em;text-decoration:none;display:inline-flex;align-items:center;min-height:44px}

  .btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border-radius:12px;
       font-weight:800;font-size:14px;letter-spacing:-.02em;text-decoration:none;color:var(--ink);transition:background-color .2s ease-out}
  .btn-y{background:var(--yellow)}
  .btn-y:hover{background:var(--yellow-deep)}
  .btn-lg{min-height:52px;padding:0 28px;font-size:16px}

  .crumb{font-size:13px;color:var(--muted);padding:18px 0 0}
  .crumb a{color:var(--muted);text-decoration:none;min-height:44px;display:inline-flex;align-items:center;padding-inline:2px}
  .crumb a:hover{color:var(--ink);text-decoration:underline}
  .crumb span{margin-inline:2px}

  h1{font-size:clamp(24px,4.4vw,34px);font-weight:800;letter-spacing:-.035em;line-height:1.3;margin:10px 0 6px;text-wrap:balance}
  .stamp{margin:0 0 22px;color:var(--muted);font-size:13.5px}

  .hero-price{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px;
              background:var(--fill);border-radius:16px;padding:20px 22px;margin-bottom:22px}
  .hero-price .rl{display:block;font-size:12.5px;color:var(--muted)}
  .hero-price strong{font-size:clamp(26px,5vw,36px);font-weight:800;letter-spacing:-.035em;font-variant-numeric:tabular-nums}
  .hero-price strong em{font-style:normal;font-size:16px;font-weight:700}
  .delta{font-weight:800;font-size:16px;font-variant-numeric:tabular-nums}
  .delta.up{color:var(--up)} .delta.down{color:var(--down)}
  .delta span{display:block;font-size:11.5px;font-weight:500;color:var(--muted)}

  .lead{font-size:16px;color:var(--ink-2);margin:0 0 30px}
  h2{font-size:clamp(19px,2.8vw,23px);font-weight:800;letter-spacing:-.03em;margin:36px 0 12px;text-wrap:balance}
  p{margin:0 0 14px}

  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
  table{border-collapse:collapse;width:100%;min-width:460px;font-size:14.5px}
  th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line)}
  thead th{background:var(--fill);font-size:12.5px;color:var(--muted);font-weight:700}
  tbody tr:last-child td{border-bottom:0}
  td.g{font-weight:800}
  .r{text-align:right}
  .note{font-size:13px;color:var(--muted);margin-top:10px}

  .factors,.checks{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:10px}
  .factors li,.checks li{position:relative;padding-left:24px;font-size:15px;color:var(--ink-2)}
  .factors li::before{content:"";position:absolute;left:6px;top:11px;width:6px;height:6px;border-radius:50%;background:var(--yellow-deep)}
  .checks li::before{content:"";position:absolute;left:4px;top:7px;width:11px;height:6px;
    border-left:2px solid var(--up);border-bottom:2px solid var(--up);transform:rotate(-45deg)}

  .cta{background:var(--yellow-soft);border:1px solid var(--yellow);border-radius:16px;padding:26px 22px;margin:38px 0;text-align:center}
  .cta h2{margin:0 0 8px}
  .cta p{color:var(--ink-2);font-size:14.5px;margin-bottom:18px}

  .faq details{border-bottom:1px solid var(--line)}
  .faq summary{cursor:pointer;list-style:none;min-height:56px;display:flex;align-items:center;padding:12px 30px 12px 0;
               position:relative;font-size:15.5px;font-weight:700;letter-spacing:-.025em}
  .faq summary::-webkit-details-marker{display:none}
  .faq summary::after{content:"";position:absolute;right:6px;top:50%;margin-top:-6px;width:9px;height:9px;
    border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(45deg)}
  .faq details[open] summary::after{transform:rotate(-135deg);margin-top:-2px}
  .faq p{padding:0 4px 18px 0;color:var(--muted);font-size:14.5px;margin:0}

  .rel{display:grid;grid-template-columns:1fr;gap:8px}
  @media(min-width:560px){.rel{grid-template-columns:repeat(3,1fr)}}
  .rel a{border:1px solid var(--line);border-radius:14px;padding:14px;text-decoration:none;
         display:flex;flex-direction:column;gap:3px;min-height:44px;transition:border-color .2s ease-out}
  .rel a:hover{border-color:var(--yellow)}
  .rb{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--muted)}
  .rm{font-size:14.5px;font-weight:700;letter-spacing:-.025em}
  .rp{font-size:13px;color:var(--ink-2);margin-top:2px}

  .foot{border-top:1px solid var(--line);margin-top:46px;padding:24px 0 40px;font-size:13px;color:var(--muted)}
  .foot a{color:var(--muted);min-height:44px;display:inline-flex;align-items:center;padding-inline:4px}
  .foot .dim{margin:0;font-size:12.5px}
</style>`;

/* ── 실행 ────────────────────────────────────────────── */

const outFlag = process.argv.indexOf('--out');
const OUT = join(HERE, outFlag > -1 ? process.argv[outFlag + 1] : 'dist');

const raw = JSON.parse(readFileSync(join(HERE, 'data/items.json'), 'utf8'));
const { meta, items } = raw;

// 슬러그 중복 검사 — 조용히 덮어쓰이면 페이지가 사라집니다
const seen = new Set();
for (const it of items) {
  const s = slugOf(it);
  if (seen.has(s)) throw new Error(`슬러그 중복: ${s}`);
  seen.add(s);
}
// related 참조 무결성 검사 — 깨진 내부 링크는 SEO 손해입니다
for (const it of items) {
  for (const r of it.related || []) {
    if (!items.some((x) => x.slug === r)) {
      throw new Error(`${it.slug} 의 related 에 존재하지 않는 슬러그: ${r}`);
    }
  }
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, 'price'), { recursive: true });

for (const it of items) {
  writeFileSync(join(OUT, 'price', `${slugOf(it)}.html`), page(it, items, meta), 'utf8');
}
writeFileSync(join(OUT, 'price', 'index.html'), hub(items, meta), 'utf8');

const urls = [`${meta.site}${CONFIG.base}`, ...items.map((i) => `${meta.site}${urlOf(i)}`)];
writeFileSync(
  join(OUT, 'sitemap-price.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    urls.map((u) => `  <url><loc>${esc(u)}</loc><lastmod>${meta.updated}</lastmod></url>`).join('\n') +
    `\n</urlset>\n`,
  'utf8'
);

console.log(`생성 완료 — 상세 ${items.length}장 + 허브 1장 + sitemap`);
console.log(`출력: ${OUT}`);
