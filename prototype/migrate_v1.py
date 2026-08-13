#!/usr/bin/env python3
"""구 스키마(valuation_event) → V1 스키마 이식. 멱등 (여러 번 실행해도 안전).

  python3 migrate_v1.py drrrk_sim.db --env SIMULATION
  python3 migrate_v1.py legacy_backup.db --env REAL

매핑 (설계 §5-M2):
  asset_instance        → assets              (asset_id = instance_id)
  buyer_quote           → dealer_bids         (bid_type=INDICATIVE — 구속력 미확인이므로 보수적)
  contract_price        → transactions(sale)  (비용 미상 → costs_unknown=1)
  liquidation_price     → transactions(liquidation, ACTUAL_LIQUIDATION)
  backfill_liquidation  → transactions(liquidation, PARTNER_HISTORICAL)
  external_comp         → market_events
  backfill_appraisal /
  extension_reappraisal → appraisals
  backfill_loan         → finance_cases + finance_events(origination)
  ai_estimate           → legacy_ai_estimates (SIMULATION·BACKFILL 전용 —
                          REAL 환경에서는 거부: AI 가격 이벤트는 V1에서 금지)
  correction            → audit_logs

이식된 행의 ID는 'mig:' + 원본 event_id — 재실행 시 insert or ignore로 중복 방지.
원본 event_type은 meta.legacy_event_type으로 보존한다.
마지막에 호환 뷰 valuation_event_v를 생성해 기존 도구가 계속 작동한다.
"""
import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import db as coredb

LEGACY_TYPES = ("ai_estimate", "buyer_quote", "contract_price",
                "extension_reappraisal", "liquidation_price", "external_comp",
                "backfill_appraisal", "backfill_loan", "backfill_liquidation",
                "correction")


def migrate(conn, default_env):
    """legacy 테이블이 있는 DB에 v1 스키마를 증축하고 데이터를 이식한다."""
    _ensure_v1_schema(conn, default_env)
    counts = {"legacy": _legacy_counts(conn), "migrated": {}}
    if not counts["legacy"]:
        _create_compat_view(conn)
        conn.commit()
        return counts

    if default_env == "REAL" and counts["legacy"].get("ai_estimate"):
        raise SystemExit(
            f"ai_estimate {counts['legacy']['ai_estimate']}건은 REAL 환경으로 이식할 수 "
            "없습니다 — AI 가격 이벤트는 V1에서 금지. 해당 행을 제외하고 다시 시도하세요.")

    _migrate_instances(conn, default_env)
    m = counts["migrated"]
    m["buyer_quote"] = _migrate_quotes(conn, default_env)
    m["contract_price"] = _migrate_sales(conn, default_env)
    m["liquidation_price"] = _migrate_liquidations(conn, default_env, "liquidation_price")
    m["backfill_liquidation"] = _migrate_liquidations(conn, default_env,
                                                     "backfill_liquidation")
    m["external_comp"] = _migrate_external(conn, default_env)
    m["backfill_appraisal"] = _migrate_appraisals(conn, default_env,
                                                  "backfill_appraisal")
    m["extension_reappraisal"] = _migrate_appraisals(conn, default_env,
                                                     "extension_reappraisal")
    m["backfill_loan"] = _migrate_loans(conn, default_env)
    m["ai_estimate"] = _migrate_ai_estimates(conn, default_env)
    m["correction"] = _migrate_corrections(conn)
    _create_compat_view(conn)
    conn.commit()
    return counts


# ── 스키마 준비 ───────────────────────────────────────────────────────────
def _ensure_v1_schema(conn, env):
    with open(coredb.SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    # legacy asset_master에 v1 컬럼 증축
    cols = [r[1] for r in conn.execute("pragma table_info(asset_master)")]
    for col, ddl in (("variant", "text"), ("status", "text default 'active'"),
                     ("merged_into", "text")):
        if col not in cols:
            conn.execute(f"alter table asset_master add column {col} {ddl}")
    conn.execute("insert or ignore into db_meta values ('environment', ?)", (env,))
    coredb.install_env_guards(conn, coredb.environment(conn))
    conn.execute("""create table if not exists legacy_ai_estimates (
        id text primary key, asset_id text, canonical_asset_id text,
        value_krw integer, observed_at text, source text, meta text,
        data_environment text check (data_environment in ('SIMULATION','BACKFILL')))""")


def _legacy_counts(conn):
    if not conn.execute("select 1 from sqlite_master where type='table'"
                        " and name='valuation_event'").fetchone():
        return {}
    return dict(conn.execute(
        "select event_type, count(*) from valuation_event group by event_type"))


def _env(default_env, source):
    if default_env == "SIMULATION":
        return "SIMULATION"
    return "BACKFILL" if (source or "").startswith("backfill") else default_env


def _meta(meta_json, legacy_type):
    m = json.loads(meta_json or "{}")
    m["legacy_event_type"] = legacy_type
    return json.dumps(m, ensure_ascii=False)


def _rows(conn, etype):
    return conn.execute(
        "select event_id, instance_id, canonical_asset_id, deal_type, value_krw,"
        " observed_at, source, meta from valuation_event where event_type=?",
        (etype,)).fetchall()


# ── 이식 단계 ────────────────────────────────────────────────────────────
def _migrate_instances(conn, default_env):
    for iid, cid, grade, source, listing in conn.execute(
            "select instance_id, canonical_asset_id, grade, source,"
            " listing_id from asset_instance"):
        conn.execute(
            "insert or ignore into assets (asset_id, canonical_asset_id,"
            " data_environment, identity_status, grade, source, listing_id)"
            " values (?,?,?,?,?,?,?)",
            (iid, cid, _env(default_env, source), "AI_CANDIDATE", grade,
             source, listing))


def _migrate_quotes(conn, default_env):
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, "buyer_quote"):
        n += conn.execute(
            "insert or ignore into dealer_bids (bid_id, asset_id,"
            " canonical_asset_id, buyer_id, bid_type, bid_price_krw, bid_time,"
            " status, source, source_type, data_environment, meta)"
            " values (?,?,?,?,'INDICATIVE',?,?,'expired',?,"
            "'DEALER_INDICATIVE_BID',?,?)",
            (f"mig:{eid}", iid, cid, src, v, at, src,
             _env(default_env, src), _meta(meta, "buyer_quote"))).rowcount
    return n


def _migrate_sales(conn, default_env):
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, "contract_price"):
        d2s = json.loads(meta or "{}").get("days_to_sale")
        n += conn.execute(
            "insert or ignore into transactions (transaction_id, asset_id,"
            " canonical_asset_id, transaction_type, gross_price_krw,"
            " contracted_at, settled_at, days_to_sale, costs_unknown, source,"
            " source_type, data_environment, meta)"
            " values (?,?,?,'sale',?,?,?,?,1,?,'ACTUAL_SALE',?,?)",
            (f"mig:{eid}", iid, cid, v, at, at, d2s, src,
             _env(default_env, src), _meta(meta, "contract_price"))).rowcount
    return n


def _migrate_liquidations(conn, default_env, etype):
    stype = "PARTNER_HISTORICAL" if etype.startswith("backfill") else "ACTUAL_LIQUIDATION"
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, etype):
        n += conn.execute(
            "insert or ignore into transactions (transaction_id, asset_id,"
            " canonical_asset_id, transaction_type, gross_price_krw,"
            " contracted_at, settled_at, costs_unknown, source, source_type,"
            " data_environment, meta)"
            " values (?,?,?,'liquidation',?,?,?,1,?,?,?,?)",
            (f"mig:{eid}", iid, cid, v, at, at, src, stype,
             _env(default_env, src), _meta(meta, etype))).rowcount
    return n


def _migrate_external(conn, default_env):
    n = 0
    for eid, _, cid, _, v, at, src, meta in _rows(conn, "external_comp"):
        stype = "EXTERNAL_SOLD" if (json.loads(meta or "{}").get("sold")
                                    or "kream" in (src or "")) else "PUBLIC_LISTING"
        n += conn.execute(
            "insert or ignore into market_events (market_event_id,"
            " canonical_asset_id, source_type, price_krw, source,"
            " data_environment, observed_at, meta) values (?,?,?,?,?,?,?,?)",
            (f"mig:{eid}", cid, stype, v, src, _env(default_env, src), at,
             _meta(meta, "external_comp"))).rowcount
    return n


def _migrate_appraisals(conn, default_env, etype):
    stype = "PARTNER_HISTORICAL" if etype.startswith("backfill") else "EXPERT_ESTIMATE"
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, etype):
        n += conn.execute(
            "insert or ignore into appraisals (appraisal_id, asset_id,"
            " canonical_asset_id, value_krw, appraised_by, source_type,"
            " data_environment, meta, observed_at) values (?,?,?,?,?,?,?,?,?)",
            (f"mig:{eid}", iid, cid, v, src, stype, _env(default_env, src),
             _meta(meta, etype), at)).rowcount
    return n


def _migrate_loans(conn, default_env):
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, "backfill_loan"):
        env = _env(default_env, src)
        conn.execute(
            "insert or ignore into finance_cases (case_id, asset_id,"
            " canonical_asset_id, institution, data_environment, opened_at)"
            " values (?,?,?,?,?,?)",
            (f"case:{iid}", iid, cid, src, env, at))
        n += conn.execute(
            "insert or ignore into finance_events (finance_event_id, case_id,"
            " event_kind, amount_krw, source_type, data_environment, meta,"
            " observed_at) values (?,?,'origination',?,'PARTNER_HISTORICAL',?,?,?)",
            (f"mig:{eid}", f"case:{iid}", v, env,
             _meta(meta, "backfill_loan"), at)).rowcount
    return n


def _migrate_ai_estimates(conn, default_env):
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, "ai_estimate"):
        env = _env(default_env, src)
        n += conn.execute(
            "insert or ignore into legacy_ai_estimates values (?,?,?,?,?,?,?,?)",
            (f"mig:{eid}", iid, cid, v, at, src, _meta(meta, "ai_estimate"),
             env if env != "REAL" else "BACKFILL")).rowcount
    return n


def _migrate_corrections(conn):
    n = 0
    for eid, iid, cid, _, v, at, src, meta in _rows(conn, "correction"):
        n += conn.execute(
            "insert or ignore into audit_logs (audit_id, actor, action,"
            " table_name, record_id, after_json, reason)"
            " values (?,?,?,?,?,?,?)",
            (f"mig:{eid}", src, "legacy_correction", "valuation_event", iid or cid,
             _meta(meta, "correction"), "migrated from legacy correction event")).rowcount
    return n


# ── 호환 뷰 — 기존 도구(analyze/dashboard)가 무수정으로 읽는다 ─────────────
def _create_compat_view(conn):
    conn.execute("drop view if exists valuation_event_v")
    conn.execute("""
create view valuation_event_v as
  select bid_id as event_id, asset_id as instance_id, canonical_asset_id,
         'sale' as deal_type,
         coalesce(json_extract(meta,'$.legacy_event_type'),'buyer_quote') as event_type,
         bid_price_krw as value_krw, bid_time as observed_at, source, meta
    from dealer_bids
  union all
  select transaction_id, asset_id, canonical_asset_id,
         case transaction_type when 'sale' then 'sale' else 'pawn' end,
         coalesce(json_extract(meta,'$.legacy_event_type'),
                  case transaction_type when 'sale' then 'contract_price'
                       else 'liquidation_price' end),
         gross_price_krw, contracted_at, source, meta
    from transactions
  union all
  select market_event_id, null, canonical_asset_id, 'external',
         'external_comp', price_krw, observed_at, source, meta
    from market_events
  union all
  select appraisal_id, asset_id, canonical_asset_id, 'pawn',
         coalesce(json_extract(meta,'$.legacy_event_type'),'backfill_appraisal'),
         value_krw, observed_at, appraised_by, meta
    from appraisals
  union all
  select finance_event_id, f.asset_id, f.canonical_asset_id, 'pawn',
         'backfill_loan', amount_krw, observed_at, institution, e.meta
    from finance_events e join finance_cases f using (case_id)
    where event_kind='origination'
  union all
  select id, asset_id, canonical_asset_id, 'sale', 'ai_estimate',
         value_krw, observed_at, source, meta
    from legacy_ai_estimates""")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db_path")
    ap.add_argument("--env", required=True, choices=["SIMULATION", "REAL"],
                    help="이식 대상 환경 (backfill 출처 행은 REAL에서 자동 BACKFILL 태깅)")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db_path)
    counts = migrate(conn, args.env)
    legacy_total = sum(counts["legacy"].values())
    migrated_total = sum(counts["migrated"].values())
    print(f"legacy 이벤트 {legacy_total}건 → v1 이식 {migrated_total}건 (재실행 시 0건이 정상)")
    for k in sorted(counts["legacy"]):
        print(f"  {k:22s} {counts['legacy'][k]:>6} → {counts['migrated'].get(k, 0)}")
    conn.close()


if __name__ == "__main__":
    main()
