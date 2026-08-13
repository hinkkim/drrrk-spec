-- 드르륵 Asset Intelligence System — V1 스키마 (SQLite)
-- 설계: docs/V1_전환설계_AssetIntelligence.md §4
--
-- 원칙:
--   · 모든 증거 행에 source_type / evidence_class / data_environment 필수
--   · AI 예측(ai_predictions)에는 가격이 존재할 수 없다 (스키마 CHECK)
--   · audit_logs는 append-only (trigger로 UPDATE/DELETE 차단)
--   · 관측치 테이블의 값 컬럼은 불변 (trigger로 보호) — 정정은 새 행 + audit

-- ── A. Asset Identity ────────────────────────────────────────────────────

create table if not exists asset_master (
  canonical_asset_id text primary key,
  category           text not null,          -- WATCH / BAG / JWL
  brand              text not null,
  model              text not null,
  reference_no       text,
  variant            text,
  aliases            text default '',        -- 세미콜론 구분
  status             text not null default 'active'
                     check (status in ('active','merged','deprecated')),
  merged_into        text,                   -- status='merged'일 때 대상 ID
  created_at         text default (datetime('now'))
);

-- 개별 실물 (구 asset_instance). canonical_asset_id는 검증 전 NULL 가능.
create table if not exists assets (
  asset_id           text primary key,
  canonical_asset_id text references asset_master(canonical_asset_id),
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  identity_status    text not null default 'UNIDENTIFIED'
                     check (identity_status in
                       ('UNIDENTIFIED','AI_CANDIDATE','HUMAN_VERIFIED','DISPUTED')),
  grade              text check (grade in ('S','A','B','C')),
  purchase_year      integer,
  registered_by      text,
  source             text not null,          -- drrrk / backfill:종로B / sim ...
  listing_id         text,
  created_at         text default (datetime('now'))
);

create table if not exists asset_images (
  image_id    text primary key,
  asset_id    text not null references assets(asset_id),
  file_path   text not null,
  sha256      text,
  captured_at text,
  meta        text default '{}',
  created_at  text default (datetime('now'))
);

create table if not exists asset_documents (
  document_id text primary key,
  asset_id    text not null references assets(asset_id),
  doc_type    text not null check (doc_type in
                ('receipt','warranty','certificate','appraisal_doc','other')),
  file_path   text not null,
  sha256      text,
  meta        text default '{}',
  created_at  text default (datetime('now'))
);

-- ── AI / Human 분리 ──────────────────────────────────────────────────────

create table if not exists model_versions (
  model_version_id text primary key,
  name             text not null,            -- gemini-2.x / rule-liquidation / baseline
  kind             text not null check (kind in ('AI_MODEL','RULE_ENGINE','BASELINE')),
  version          text not null,
  params_hash      text,
  deployed_at      text default (datetime('now')),
  unique (name, version)
);

-- AI 산출물. 가격 필드가 스키마 수준에서 존재할 수 없다:
--   payload JSON에 _krw / "price 문자열이 들어가면 INSERT 거부.
create table if not exists ai_predictions (
  prediction_id    text primary key,
  asset_id         text not null references assets(asset_id),
  prediction_type  text not null check (prediction_type in
                     ('identity','condition','authenticity_anomaly','field_extraction')),
  payload          text not null default '{}'
                   check (instr(payload, '_krw') = 0
                          and instr(payload, '"price') = 0),
  confidence       real,
  model_version_id text references model_versions(model_version_id),
  source_type      text not null default 'AI_ESTIMATE'
                   check (source_type = 'AI_ESTIMATE'),
  evidence_class   text not null default 'ESTIMATED'
                   check (evidence_class = 'ESTIMATED'),
  data_environment text not null
                   check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  observed_at      text not null,
  created_at       text default (datetime('now'))
);
create index if not exists idx_aip_asset on ai_predictions (asset_id, prediction_type);

create table if not exists human_verifications (
  verification_id  text primary key,
  asset_id         text not null references assets(asset_id),
  field            text not null check (field in ('identity','condition','authenticity')),
  ai_prediction_id text references ai_predictions(prediction_id),
  verified_value   text not null,
  verified_by      text not null,
  started_at       text,                     -- 검증 소요시간 측정 (KPI)
  completed_at     text not null,
  evidence_used    text default '',
  source_type      text not null default 'EXPERT_ESTIMATE'
                   check (source_type = 'EXPERT_ESTIMATE'),
  evidence_class   text not null default 'OBSERVED'
                   check (evidence_class = 'OBSERVED'),
  data_environment text not null
                   check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  created_at       text default (datetime('now'))
);
create index if not exists idx_hv_asset on human_verifications (asset_id, field);

create table if not exists verification_corrections (
  correction_id     text primary key,
  verification_id   text not null references human_verifications(verification_id),
  correction_reason text not null check (correction_reason in (
    'reference_mismatch','serial_mismatch','material','size','year','hardware',
    'stitching','logo','aftermarket_part','repair','condition',
    'insufficient_image','authenticity_issue')),
  before_value      text,
  after_value       text not null,
  note              text,
  created_at        text default (datetime('now'))
);

-- ── B. Condition / Authenticity Evidence ─────────────────────────────────

create table if not exists condition_assessments (
  assessment_id    text primary key,
  asset_id         text not null references assets(asset_id),
  grade            text not null check (grade in ('S','A','B','C')),
  detail           text default '{}',        -- 부위별 점수 JSON
  assessed_by      text not null,
  source_type      text not null check (source_type in ('AI_ESTIMATE','EXPERT_ESTIMATE')),
  evidence_class   text not null default 'OBSERVED'
                   check (evidence_class in ('OBSERVED','ESTIMATED')),
  data_environment text not null
                   check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  observed_at      text not null,
  created_at       text default (datetime('now'))
);

create table if not exists authentication_evidence (
  evidence_id      text primary key,
  asset_id         text not null references assets(asset_id),
  evidence_type    text not null check (evidence_type in
                     ('serial','hologram','receipt','external_cert',
                      'expert_opinion','duplicate_check')),
  result           text not null check (result in ('pass','fail','inconclusive')),
  serial_hash      text,                     -- 시리얼 원문 대신 해시 (§16-H)
  detail           text default '{}',
  source           text not null,
  evidence_class   text not null default 'OBSERVED'
                   check (evidence_class = 'OBSERVED'),
  data_environment text not null
                   check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  observed_at      text not null,
  created_at       text default (datetime('now'))
);
create index if not exists idx_ae_serial on authentication_evidence (serial_hash);

-- ── C. Market Evidence ───────────────────────────────────────────────────

create table if not exists market_events (
  market_event_id    text primary key,
  canonical_asset_id text not null references asset_master(canonical_asset_id),
  source_type        text not null check (source_type in
                       ('PUBLIC_LISTING','EXTERNAL_SOLD')),
  price_krw          integer not null,
  currency           text not null default 'KRW',
  source             text not null,
  url                text,
  meta               text default '{}',
  evidence_class     text not null default 'OBSERVED'
                     check (evidence_class = 'OBSERVED'),
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  observed_at        text not null,
  created_at         text default (datetime('now'))
);
create index if not exists idx_me_asset on market_events (canonical_asset_id, observed_at);

-- 전문가/파트너 감정가 (백필 장부의 감정가, 재평가 등). 관측된 '추정값'.
create table if not exists appraisals (
  appraisal_id       text primary key,
  asset_id           text references assets(asset_id),
  canonical_asset_id text not null references asset_master(canonical_asset_id),
  value_krw          integer not null,
  appraised_by       text not null,
  source_type        text not null check (source_type in
                       ('EXPERT_ESTIMATE','PARTNER_HISTORICAL')),
  evidence_class     text not null default 'ESTIMATED'
                     check (evidence_class = 'ESTIMATED'),
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  meta               text default '{}',
  observed_at        text not null,
  created_at         text default (datetime('now'))
);

-- ── D. Dealer Liquidity ──────────────────────────────────────────────────

-- bid는 불변 사실. 단계 승격(INDICATIVE→FIRM→COMMITTED→SETTLED)은
-- 새 행 + supersedes_bid_id 연결로 표현한다 (append-only).
-- status만 수명주기에 따라 갱신 가능 (audit 필수, market/bids.py 경유).
create table if not exists dealer_bids (
  bid_id                    text primary key,
  asset_id                  text not null references assets(asset_id),
  canonical_asset_id        text references asset_master(canonical_asset_id),
  buyer_id                  text not null,
  bid_type                  text not null check (bid_type in
                              ('INDICATIVE','FIRM','COMMITTED','SETTLED')),
  bid_price_krw             integer not null,
  bid_time                  text not null,
  expiry                    text,
  status                    text not null default 'active' check (status in
                              ('active','expired','cancelled','superseded',
                               'selected','rejected','settled')),
  rejected_reason           text,
  payment_capacity_verified integer not null default 0,
  settlement_status         text check (settlement_status in
                              ('pending','settled','failed') or settlement_status is null),
  supersedes_bid_id         text references dealer_bids(bid_id),
  source                    text not null,
  source_type               text not null check (source_type in
                              ('DEALER_INDICATIVE_BID','DEALER_FIRM_BID',
                               'DEALER_COMMITTED_BID','ACTUAL_PURCHASE',
                               'PARTNER_HISTORICAL')),
  evidence_class            text not null default 'OBSERVED'
                            check (evidence_class = 'OBSERVED'),
  data_environment          text not null
                            check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  meta                      text default '{}',
  created_at                text default (datetime('now'))
);
create index if not exists idx_db_asset on dealer_bids (asset_id, bid_type);
create index if not exists idx_db_canonical on dealer_bids (canonical_asset_id, bid_time);

-- ── E. Transaction / Outcome ─────────────────────────────────────────────

create table if not exists transactions (
  transaction_id     text primary key,
  asset_id           text not null references assets(asset_id),
  canonical_asset_id text references asset_master(canonical_asset_id),
  winning_bid_id     text references dealer_bids(bid_id),
  transaction_type   text not null check (transaction_type in
                       ('sale','purchase','liquidation')),
  gross_price_krw    integer not null,
  contracted_at      text not null,
  settled_at         text,
  days_to_sale       real,
  costs_unknown      integer not null default 0,  -- 백필 등 비용 미상 플래그
  source             text not null,
  source_type        text not null check (source_type in
                       ('ACTUAL_SALE','ACTUAL_PURCHASE','ACTUAL_LIQUIDATION',
                        'PARTNER_HISTORICAL')),
  evidence_class     text not null default 'OBSERVED'
                     check (evidence_class = 'OBSERVED'),
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  meta               text default '{}',
  created_at         text default (datetime('now'))
);
create index if not exists idx_tx_canonical on transactions (canonical_asset_id, contracted_at);

create table if not exists transaction_costs (
  cost_id        text primary key,
  transaction_id text not null references transactions(transaction_id),
  cost_type      text not null check (cost_type in
                   ('platform_fee','shipping','authentication','repair','other')),
  amount_krw     integer not null,
  note           text,
  created_at     text default (datetime('now'))
);

-- Net Proceeds = gross − Σcosts (DERIVED — 저장하지 않고 뷰로 산출)
create view if not exists v_net_proceeds as
  select t.transaction_id, t.asset_id, t.canonical_asset_id,
         t.transaction_type, t.gross_price_krw,
         coalesce(sum(c.amount_krw), 0)                as total_costs_krw,
         t.gross_price_krw - coalesce(sum(c.amount_krw), 0) as net_proceeds_krw,
         t.costs_unknown, t.settled_at, t.days_to_sale, t.data_environment
  from transactions t
  left join transaction_costs c using (transaction_id)
  group by t.transaction_id;

-- ── 산출물 (DERIVED / ESTIMATED) ─────────────────────────────────────────

create table if not exists liquidity_snapshots (
  snapshot_id                 text primary key,
  snapshot_date               text not null,
  canonical_asset_id          text not null,
  window_days                 integer not null,
  unique_qualified_bidders    integer,
  bid_count                   integer,
  firm_bid_count              integer,
  bid_dispersion_pct          real,
  top1_buyer_share_pct        real,
  top3_buyer_share_pct        real,
  time_to_first_bid_days      real,
  time_to_first_firm_bid_days real,
  bid_to_sale_conversion_pct  real,
  days_to_sale_median         real,
  failed_listing_count        integer,
  sample                      text default '{}',
  evidence_class              text not null default 'DERIVED'
                              check (evidence_class = 'DERIVED'),
  data_environment            text not null
                              check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  created_at                  text default (datetime('now'))
);

create table if not exists liquidation_estimates (
  estimate_id        text primary key,
  canonical_asset_id text not null,
  asset_id           text,
  horizon_days       integer not null check (horizon_days in (7, 30, 60)),
  range_low_krw      integer,               -- INSUFFICIENT이면 NULL (숫자를 만들지 않는다)
  range_mid_krw      integer,
  range_high_krw     integer,
  confidence         text not null check (confidence in
                       ('HIGH','MEDIUM','LOW','INSUFFICIENT')),
  reason_codes       text default '[]',     -- JSON 배열
  input_sample       text default '{}',     -- 표본 명세 JSON
  rule_version       text not null,
  evidence_class     text not null default 'ESTIMATED'
                     check (evidence_class = 'ESTIMATED'),
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  estimated_at       text not null,
  created_at         text default (datetime('now'))
);

-- 예측 vs 실측 대사 — 캘리브레이션의 원천
create table if not exists outcomes (
  outcome_id         text primary key,
  estimate_id        text not null references liquidation_estimates(estimate_id),
  transaction_id     text not null references transactions(transaction_id),
  net_proceeds_krw   integer,
  error_pct          real,                  -- (mid − 실측) / 실측
  downside_error_pct real,                  -- (low − 실측) / 실측 (하방 오차)
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  created_at         text default (datetime('now'))
);

-- ── 공통 ─────────────────────────────────────────────────────────────────

create table if not exists spot_price (
  metal      text primary key,
  krw_per_g  real not null,
  updated_at text
);

create table if not exists db_meta (
  key   text primary key,
  value text not null
);

create table if not exists audit_logs (
  audit_id    text primary key,
  actor       text not null,
  action      text not null,               -- insert / update / merge / status_change ...
  table_name  text not null,
  record_id   text not null,
  before_json text,
  after_json  text,
  reason      text,
  created_at  text default (datetime('now'))
);

-- ── 확장 예약 (V1 UX 제외 — 스키마만 정의, §6) ───────────────────────────

create table if not exists finance_cases (
  case_id            text primary key,
  asset_id           text references assets(asset_id),
  canonical_asset_id text,
  institution        text not null,
  data_environment   text not null
                     check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  opened_at          text not null,
  meta               text default '{}',
  created_at         text default (datetime('now'))
);

create table if not exists finance_events (
  finance_event_id text primary key,
  case_id          text not null references finance_cases(case_id),
  event_kind       text not null check (event_kind in
                     ('origination','repayment','extension','delinquency',
                      'default','liquidation','recovery')),
  amount_krw       integer,
  source_type      text not null check (source_type in
                     ('PARTNER_HISTORICAL','PARTNER_FINANCE_OUTCOME')),
  evidence_class   text not null default 'OBSERVED'
                   check (evidence_class = 'OBSERVED'),
  data_environment text not null
                   check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  meta             text default '{}',
  observed_at      text not null,
  created_at       text default (datetime('now'))
);

create table if not exists recovery_events (
  recovery_event_id text primary key,
  case_id           text not null references finance_cases(case_id),
  transaction_id    text references transactions(transaction_id),
  net_recovery_krw  integer,
  days_to_liquidate real,
  data_environment  text not null
                    check (data_environment in ('SIMULATION','REAL','BACKFILL')),
  meta              text default '{}',
  observed_at       text not null,
  created_at        text default (datetime('now'))
);

create table if not exists institution_policies (
  policy_id   text primary key,
  institution text not null,
  policy_json text not null default '{}',  -- 기관 정책은 DRRRK 데이터와 분리 (§19 Phase 5)
  created_at  text default (datetime('now'))
);

-- ── 무결성 트리거 ────────────────────────────────────────────────────────

-- audit_logs: append-only
create trigger if not exists trg_audit_no_update before update on audit_logs
begin select raise(ABORT, 'audit_logs is append-only'); end;
create trigger if not exists trg_audit_no_delete before delete on audit_logs
begin select raise(ABORT, 'audit_logs is append-only'); end;

-- 증거 테이블: DELETE 전면 금지 (정정은 새 행 + audit)
create trigger if not exists trg_aip_no_delete before delete on ai_predictions
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_hv_no_delete before delete on human_verifications
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_vc_no_delete before delete on verification_corrections
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_ca_no_delete before delete on condition_assessments
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_ae_no_delete before delete on authentication_evidence
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_me_no_delete before delete on market_events
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_ap_no_delete before delete on appraisals
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_db_no_delete before delete on dealer_bids
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_tx_no_delete before delete on transactions
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_tc_no_delete before delete on transaction_costs
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_le_no_delete before delete on liquidation_estimates
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;
create trigger if not exists trg_oc_no_delete before delete on outcomes
begin select raise(ABORT, 'evidence rows cannot be deleted'); end;

-- 관측치의 값 컬럼은 불변 — 수명주기 컬럼(status 등)만 갱신 가능
create trigger if not exists trg_db_immutable
before update of bid_id, asset_id, buyer_id, bid_type, bid_price_krw, bid_time,
                 source, source_type, data_environment on dealer_bids
begin select raise(ABORT, 'bid facts are immutable — supersede with a new row'); end;

create trigger if not exists trg_tx_immutable
before update of transaction_id, asset_id, gross_price_krw, transaction_type,
                 contracted_at, source, source_type, data_environment on transactions
begin select raise(ABORT, 'transaction facts are immutable'); end;

create trigger if not exists trg_aip_no_update before update on ai_predictions
begin select raise(ABORT, 'ai_predictions are immutable'); end;
create trigger if not exists trg_hv_no_update before update on human_verifications
begin select raise(ABORT, 'human_verifications are immutable — add a correction row'); end;
create trigger if not exists trg_me_no_update before update on market_events
begin select raise(ABORT, 'market_events are immutable'); end;
