-- 드르륵 자산 언더라이팅 원장 — 프로토타입 스키마 (SQLite)
-- 구현 스펙: docs/자산_언더라이팅_원장_구현스펙.md

create table if not exists asset_master (
  canonical_asset_id text primary key,
  category           text not null,          -- WATCH / BAG / JWL
  brand              text not null,
  model              text not null,
  reference_no       text,
  aliases            text default '',        -- 세미콜론 구분
  created_at         text default (datetime('now'))
);

create table if not exists asset_instance (
  instance_id        text primary key,
  canonical_asset_id text references asset_master(canonical_asset_id),
  grade              text check (grade in ('S','A','B','C')),
  purchase_year      integer,
  source             text not null,          -- drrrk / backfill / asset_only
  listing_id         text,
  created_at         text default (datetime('now'))
);

-- 가격 이벤트 원장 (append-only). 4개 가격 레이어가 전부 이 테이블에 쌓인다:
--   중고 거래 시세  = external_comp                (retail)
--   매입/위탁 호가  = buyer_quote  (deal_type=sale) (wholesale = liquidation value 관측치)
--   담보 거래 가치  = buyer_quote/contract_price (deal_type=pawn), backfill_appraisal/loan
--   회수율         = liquidation_price / backfill_liquidation (meta: loan_balance, days, cost)
create table if not exists valuation_event (
  event_id           text primary key,
  instance_id        text references asset_instance(instance_id),
  canonical_asset_id text not null references asset_master(canonical_asset_id),
  deal_type          text not null default 'sale'
                     check (deal_type in ('sale','pawn','external')),
  event_type         text not null check (event_type in (
    'ai_estimate','buyer_quote','contract_price','extension_reappraisal',
    'liquidation_price','external_comp',
    'backfill_appraisal','backfill_loan','backfill_liquidation','correction'
  )),
  value_krw          integer not null,
  observed_at        text not null,
  source             text not null,
  meta               text default '{}',      -- JSON
  created_at         text default (datetime('now'))
);
create index if not exists idx_ve_asset on valuation_event (canonical_asset_id, event_type, observed_at);
create index if not exists idx_ve_instance on valuation_event (instance_id);

create table if not exists metric_snapshot (
  snapshot_week      text not null,
  canonical_asset_id text not null default '',   -- ''이면 category 레벨
  category           text not null,
  market_value_p50   integer,
  liq_value_p50      integer,
  liq_value_p25      integer,
  bid_depth_avg      real,
  bid_spread_pct     real,
  volatility_90d_pct real,
  mape_estimate_pct  real,
  wholesale_discount_pct real,
  recovery_rate_pct  real,
  days_to_liquidate  real,
  recommended_ltv_pct real,
  sample_size        integer not null,
  primary key (snapshot_week, category, canonical_asset_id)
);

-- ── 시뮬레이션 전용 (실서비스에는 없음) ──
-- 1차 단계(식별·상태·정가품) 오류가 원장을 얼마나 오염시키는지 측정하기 위한 정답지
create table if not exists sim_truth (
  instance_id        text primary key,
  true_canonical     text not null,
  observed_canonical text not null,
  true_grade         text not null,
  observed_grade     text not null,
  is_fake            integer not null default 0,
  fake_detected      integer not null default 0,
  id_confidence      real
);
