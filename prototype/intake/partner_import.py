#!/usr/bin/env python3
"""파트너 백필 임포터 (T15) — 전당포·매입업체 과거 장부를 원장에 합류시킨다.

  python3 intake/partner_import.py template                    # CSV 템플릿
  python3 intake/partner_import.py import ledger.csv --partner 종로B
  python3 intake/partner_import.py import ledger.csv --partner 종로B --dry-run

CSV 컬럼 (partner_ledger_template.csv 참고):
  row_id            파트너 장부의 행 번호 (재실행 시 중복 방지 키)
  pawn_date         YYYY-MM-DD — 입질(감정·대출) 일자
  item_description  자유 텍스트 (예: "롤렉스 서브마리너 검판")
  brand / model_hint  매칭 힌트 (선택 — 있으면 정확도↑)
  serial            선택 — 해시로만 저장, 중복 시리얼 탐지
  grade             S|A|B|C (선택)
  appraisal_krw     감정가
  loan_krw          대출액
  outcome           redeemed | defaulted | open
  liquidation_krw / liquidation_date   defaulted일 때 유질 처분 실측

원칙:
  · 전 데이터 BACKFILL 환경 태깅 — REAL 실측과 절대 섞이지 않는다 (§17)
  · 카탈로그 매칭 실패 행은 추측하지 않고 미매칭 목록으로 보고한다
  · 임포트마다 data-quality score를 산출하고 audit_logs에 요약을 남긴다
"""
import argparse
import csv
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit
from engine.baseline import find_asset
from intake import ingest as intake_ingest
from intake import verify as intake_verify
from market import transactions as mtx

TEMPLATE = """row_id,pawn_date,item_description,brand,model_hint,serial,grade,appraisal_krw,loan_krw,outcome,liquidation_krw,liquidation_date
1,2025-03-02,롤렉스 서브마리너 검판 풀셋,Rolex,서브마리너,7218XXX1,A,13500000,8100000,redeemed,,
2,2025-04-11,샤넬 클미 캐비어 은장,Chanel,클미,,B,11000000,6600000,defaulted,9200000,2025-09-30
3,2025-05-20,오메가 문워치,,스피드마스터,88M2210,A,7800000,4700000,open,,
"""


def match_row(conn, row):
    """카탈로그 매칭 — model_hint → brand+hint → description 순. 실패 시 None."""
    for q in (row.get("model_hint"),
              f"{row.get('brand', '')} {row.get('model_hint', '')}".strip(),
              row.get("item_description")):
        if not q:
            continue
        cid, _ = find_asset(conn, q.strip())
        if cid:
            return cid
    return None


def import_ledger(conn, path, partner, dry_run=False):
    imported, unmatched, dup_skipped = [], [], 0
    fields = {"serial": 0, "grade": 0, "appraisal": 0, "loan": 0}
    defaulted, liq_complete = 0, 0
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        key = f"backfill:{partner}:{row['row_id']}"
        if conn.execute("select 1 from assets where listing_id=?",
                        (key,)).fetchone():
            dup_skipped += 1
            continue
        cid = match_row(conn, row)
        if cid is None:
            unmatched.append({"row_id": row["row_id"],
                              "item_description": row.get("item_description")})
            continue
        if dry_run:
            imported.append((row["row_id"], cid))
            continue

        aid = intake_ingest.register_asset(
            conn, source=f"backfill:{partner}", env="BACKFILL",
            canonical_asset_id=cid, grade=(row.get("grade") or None),
            listing_id=key, actor=f"import:{partner}")
        for k, col in (("serial", "serial"), ("grade", "grade"),
                       ("appraisal", "appraisal_krw"), ("loan", "loan_krw")):
            if row.get(col):
                fields[k] += 1
        if row.get("serial"):
            intake_verify.add_authentication_evidence(
                conn, aid, "serial", "inconclusive", f"backfill:{partner}",
                serial=row["serial"], env="BACKFILL",
                observed_at=row["pawn_date"])
        if row.get("appraisal_krw"):
            conn.execute(
                "insert into appraisals (appraisal_id, asset_id,"
                " canonical_asset_id, value_krw, appraised_by, source_type,"
                " data_environment, observed_at) values (?,?,?,?,?,"
                "'PARTNER_HISTORICAL','BACKFILL',?)",
                (str(uuid.uuid4()), aid, cid, int(row["appraisal_krw"]),
                 f"backfill:{partner}", row["pawn_date"]))
        if row.get("loan_krw"):
            case_id = f"case:{aid}"
            conn.execute(
                "insert into finance_cases (case_id, asset_id,"
                " canonical_asset_id, institution, data_environment, opened_at)"
                " values (?,?,?,?,'BACKFILL',?)",
                (case_id, aid, cid, f"backfill:{partner}", row["pawn_date"]))
            conn.execute(
                "insert into finance_events (finance_event_id, case_id,"
                " event_kind, amount_krw, source_type, data_environment,"
                " observed_at) values (?,?,'origination',?,"
                "'PARTNER_HISTORICAL','BACKFILL',?)",
                (str(uuid.uuid4()), case_id, int(row["loan_krw"]),
                 row["pawn_date"]))
            outcome = (row.get("outcome") or "open").strip()
            if outcome == "redeemed":
                conn.execute(
                    "insert into finance_events (finance_event_id, case_id,"
                    " event_kind, amount_krw, source_type, data_environment,"
                    " observed_at) values (?,?,'repayment',?,"
                    "'PARTNER_HISTORICAL','BACKFILL',?)",
                    (str(uuid.uuid4()), case_id, int(row["loan_krw"]),
                     row.get("liquidation_date") or row["pawn_date"]))
            elif outcome == "defaulted":
                defaulted += 1
                conn.execute(
                    "insert into finance_events (finance_event_id, case_id,"
                    " event_kind, amount_krw, source_type, data_environment,"
                    " observed_at) values (?,?,'default',null,"
                    "'PARTNER_HISTORICAL','BACKFILL',?)",
                    (str(uuid.uuid4()), case_id, row["pawn_date"]))
                if row.get("liquidation_krw") and row.get("liquidation_date"):
                    liq_complete += 1
                    mtx.record_transaction(
                        conn, aid, "liquidation", int(row["liquidation_krw"]),
                        row["liquidation_date"],
                        settled_at=row["liquidation_date"], costs_unknown=1,
                        source=f"backfill:{partner}", env="BACKFILL",
                        actor=f"import:{partner}",
                        meta={"loan_balance": int(row["loan_krw"])})
        imported.append((row["row_id"], cid))

    n_seen = len(rows) - dup_skipped
    report = {
        "partner": partner, "rows": len(rows), "imported": len(imported),
        "unmatched": unmatched, "duplicates_skipped": dup_skipped,
        "dry_run": dry_run,
        "quality": _quality(n_seen, len(imported), fields, defaulted,
                            liq_complete),
    }
    if not dry_run:
        audit.log(conn, f"import:{partner}", "partner_import", "assets",
                  f"backfill:{partner}",
                  after={k: v for k, v in report.items() if k != "unmatched"},
                  reason=f"{len(imported)}/{n_seen} rows imported")
        conn.commit()
    return report


def _quality(n, matched, fields, defaulted, liq_complete):
    """data-quality score — 매칭률·필드 완결성·유질 실측 완결성의 평균."""
    if not n:
        return {"score_pct": None}
    match_pct = matched / n * 100
    field_pct = (sum(fields.values()) / (4 * matched) * 100) if matched else 0
    liq_pct = (liq_complete / defaulted * 100) if defaulted else None
    parts = [match_pct, field_pct] + ([liq_pct] if liq_pct is not None else [])
    return {"score_pct": round(sum(parts) / len(parts), 1),
            "match_pct": round(match_pct, 1),
            "field_completeness_pct": round(field_pct, 1),
            "liquidation_completeness_pct": (round(liq_pct, 1)
                                             if liq_pct is not None else None)}


def render(r):
    q = r["quality"]
    L = [f"\n■ 파트너 백필 임포트 — {r['partner']}"
         + (" (dry-run)" if r["dry_run"] else "")]
    L.append(f"  {r['rows']}행 중 {r['imported']}건 입력 · 미매칭 "
             f"{len(r['unmatched'])}건 · 중복 스킵 {r['duplicates_skipped']}건")
    if q.get("score_pct") is not None:
        L.append(f"  data-quality {q['score_pct']}점 — 매칭 {q['match_pct']}% · "
                 f"필드 완결 {q['field_completeness_pct']}% · "
                 f"유질 실측 완결 {q['liquidation_completeness_pct'] or '—'}%")
    for u in r["unmatched"]:
        L.append(f"  ✘ 미매칭 row {u['row_id']}: {u['item_description']}"
                 " — catalog_seed.csv에 모델 추가 후 재실행")
    return "\n".join(L) + "\n"


def main():
    from core import db as coredb
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template")
    pi = sub.add_parser("import")
    pi.add_argument("csv_path")
    pi.add_argument("--partner", required=True)
    pi.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if args.cmd == "template":
        path = os.path.join(root, "partner_ledger_template.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE)
        print(f"템플릿 생성: {path}")
        return
    conn = coredb.connect("REAL")   # BACKFILL은 REAL DB에 산다 (환경 태깅으로 구분)
    print(render(import_ledger(conn, args.csv_path, args.partner,
                               dry_run=args.dry_run)))
    conn.close()


if __name__ == "__main__":
    main()
