#!/usr/bin/env python3
"""P0 인수 테스트 — 관통 시나리오 (설계 T7).

실물 자산 1건이 아래 전 단계를 하나의 canonical_asset_id + audit trail로
통과하는지 검증한다. 이 흐름이 완성되기 전에는 ML·LTV 자동추천·기관 기능을
만들지 않는다 (V1 최우선 목표).

  등록 → 사진 → AI 후보(가격 없음) → 전문가 검증(correction 포함) → 상태 확정
  → 진위 근거(시리얼 해시) → INDICATIVE bid ×3 → FIRM 승격 → COMMITTED → 낙찰
  → 사전 청산 추정(정직한 confidence) → SETTLED 정산 → 거래 → 비용 → Net Proceeds
  → 추정 vs 실측 대사(outcome) → Evidence Report → audit trail 조회

  python3 e2e_scenario.py             # 스크래치 DB로 실행 (기본)
  python3 e2e_scenario.py --keep-db   # drrrk_e2e.db 남기기
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import audit, db as coredb
from intake import ai_assist, ingest, verify
from market import bids, transactions as tx
from engine import liquidation
from report import asset_report

CID = "WATCH-ROLEX-SUBMARINER-126610LN"
WRONG = "WATCH-ROLEX-GMT-126710BLNR"


def run(conn, quiet=False):
    say = (lambda *a: None) if quiet else print

    # 1. 등록 + 사진
    say("① 등록: 실물 접수 (canonical 미확정 — UNIDENTIFIED)")
    aid = ingest.register_asset(conn, source="drrrk", env="REAL",
                                registered_by="staff:lee")
    ingest.attach_image(conn, aid, "uploads/sub_dial.jpg", sha256="ab12")

    # 2. AI 후보 (가격 없음)
    say("② AI 후보: gemini-mock top-2 (오답이 top-1인 상황)")
    pid = ai_assist.record_prediction(
        conn, aid, "identity",
        {"brand": "Rolex",
         "candidates": [
             {"canonical_asset_id": WRONG, "confidence": 0.62,
              "evidence": "베젤 형상"},
             {"canonical_asset_id": CID, "confidence": 0.35,
              "evidence": "다이얼 각인"}],
         "grade_estimate": "A", "authenticity_flags": []},
        0.62, "gemini-mock", "0.1")

    # 3. 전문가 검증 — AI 오류를 correction으로 교정
    say("③ 전문가 검증: AI top-1 기각 → Submariner 확정 (reference_mismatch)")
    t0 = verify.start_verification()
    verify.complete_verification(
        conn, aid, "identity", CID, "expert:kim", started_at=t0,
        ai_prediction_id=pid, evidence_used="러그 각인·보증서 대조",
        correction={"reason": "reference_mismatch", "before": WRONG,
                    "note": "GMT 베젤로 오인 — 서브마리너 세라믹 베젤"})
    verify.complete_verification(conn, aid, "condition", "A", "expert:kim")
    verify.add_authentication_evidence(conn, aid, "serial", "pass",
                                       "expert:kim", serial="72K91344")

    # 4. 딜러 bid — 단계 승격
    say("④ 딜러 견적: INDICATIVE ×3 → 최고가 FIRM → COMMITTED → 낙찰")
    b1 = bids.place_bid(conn, aid, "buyer:강남A", 11600000, "INDICATIVE",
                        bid_time="2026-08-10")
    b2 = bids.place_bid(conn, aid, "buyer:종로B", 11900000, "INDICATIVE",
                        bid_time="2026-08-10")
    bids.place_bid(conn, aid, "buyer:압구정C", 11300000, "INDICATIVE",
                   bid_time="2026-08-11")
    f = bids.promote_bid(conn, b2, "FIRM", price_krw=12100000,
                         expiry="2026-08-20", actor="buyer:종로B",
                         bid_time="2026-08-12")
    c = bids.promote_bid(conn, f, "COMMITTED", payment_capacity_verified=1,
                         actor="buyer:종로B", bid_time="2026-08-13")
    bids.select_bid(conn, c, actor="drrrk")

    # 5. 사전 청산 추정 — 표본이 얇으니 정직하게 낮은 confidence가 나와야 한다
    est = liquidation.estimate(conn, CID, 30, grade="A", persist=True,
                               env="REAL", asset_id=aid)
    say(f"⑤ 사전 30일 청산 추정: confidence={est['confidence']}"
        f" reasons={est['reason_codes']} (FIRM 표본 부족 — 정직한 출력)")

    # 6. 정산 → 거래 → 비용 → Net Proceeds
    say("⑥ 정산·거래·비용: SETTLED → gross 12,100,000 − 비용 393,000")
    settled = bids.settle_bid(conn, c, actor="drrrk")
    tid = tx.record_transaction(conn, aid, "sale", 12100000, "2026-08-13",
                                winning_bid_id=settled,
                                settled_at="2026-08-14", days_to_sale=4)
    tx.add_cost(conn, tid, "platform_fee", 363000)
    tx.add_cost(conn, tid, "shipping", 30000)
    np_ = tx.net_proceeds(conn, tid)

    # 7. 추정 vs 실측 대사
    tx.record_outcome(conn, est["estimate_id"], tid)

    # 8. Evidence Report + audit trail
    r = asset_report.build(conn, CID, grade="A", asset_id=aid)
    trail = audit.trail(conn, record_id=aid)
    return {"asset_id": aid, "canonical": CID, "net": np_, "report": r,
            "trail": trail, "estimate": est, "transaction_id": tid}


def verify_result(conn, out):
    """인수 조건: 전 단계가 같은 canonical/asset ID에 연결 + audit trail 존재."""
    aid, cid = out["asset_id"], out["canonical"]
    checks = {}
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    checks["사진"] = q("select count(*) from asset_images where asset_id=?", aid)
    checks["AI 예측"] = q("select count(*) from ai_predictions where asset_id=?", aid)
    checks["전문가 검증"] = q("select count(*) from human_verifications"
                          " where asset_id=?", aid)
    checks["correction"] = q(
        "select count(*) from verification_corrections c join human_verifications v"
        " using (verification_id) where v.asset_id=?", aid)
    checks["상태 평가"] = q("select count(*) from condition_assessments"
                        " where asset_id=?", aid)
    checks["진위 근거"] = q("select count(*) from authentication_evidence"
                        " where asset_id=?", aid)
    checks["bid (전 단계)"] = q("select count(*) from dealer_bids where asset_id=?", aid)
    checks["거래"] = q("select count(*) from transactions where asset_id=?", aid)
    checks["비용"] = q("select count(*) from transaction_costs c join transactions t"
                     " using (transaction_id) where t.asset_id=?", aid)
    checks["청산 추정"] = q("select count(*) from liquidation_estimates"
                        " where canonical_asset_id=?", cid)
    checks["outcome 대사"] = q(
        "select count(*) from outcomes o join transactions t using (transaction_id)"
        " where t.asset_id=?", aid)
    checks["audit trail"] = len(out["trail"])
    failed = [k for k, v in checks.items() if not v]
    r = out["report"]
    assert not failed, f"누락 단계: {failed}"
    assert r["identity"]["human_verified"], "식별이 HUMAN_VERIFIED가 아님"
    assert r["identity"]["correction_count"] == 1
    assert out["net"]["net_proceeds_krw"] == 12100000 - 393000
    assert not out["net"]["costs_unknown"]
    bid_types = {r[0] for r in conn.execute(
        "select bid_type from dealer_bids where asset_id=?", (aid,))}
    assert bid_types == {"INDICATIVE", "FIRM", "COMMITTED", "SETTLED"}
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-db", action="store_true")
    args = ap.parse_args()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drrrk_e2e.db")
    if os.path.exists(path):
        os.remove(path)
    conn = coredb.connect("REAL", path=path)
    out = run(conn)
    checks = verify_result(conn, out)

    print("\n── 인수 조건 검증 (canonical 1개에 전 단계 연결) ──")
    for k, v in checks.items():
        print(f"  {k:12s} {v}건")
    print("\n── Evidence Report ──")
    print(asset_report.render_text(out["report"]))
    print("── Audit Trail (해당 자산) ──")
    for t in out["trail"]:
        print(f"  {t['at'][:19]}  {t['actor']:14s} {t['action']:18s}"
              + (f" {t['reason']}" if t["reason"] else ""))
    print("\n✔ 관통 시나리오 통과 — 등록→AI→검증→bid 4단계→거래→비용→Net Proceeds"
          "→대사→리포트→감사가 하나의 자산으로 연결됨")
    conn.close()
    if not args.keep_db:
        os.remove(path)
    else:
        print(f"(DB 유지: {path})")


if __name__ == "__main__":
    main()
