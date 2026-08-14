"""기관용 Asset Report API v1 (T17) — Phase 3/5의 데이터 공급 인터페이스.

원칙 (§3-B·§19 Phase 5):
  · DRRRK는 자산 데이터(식별·진위·시장·유동성·청산·실측)만 공급한다
  · 승인·한도·금리 등 여신 정책은 기관 소관 — institution_policies는
    DRRRK 데이터와 분리되어 있고 이 응답에 섞이지 않는다
  · 모든 응답은 버전드 envelope — 산식(rule_version)과 API 버전을 함께 명시
  · 표본이 부족하면 숫자 대신 NOT_AVAILABLE + 사유가 그대로 나간다

서빙은 app.py(/api/v1/*)가 담당. DRRRK_API_KEY 환경변수를 설정하면
Bearer 토큰이 강제된다 (미설정 시 로컬 프로토타입 모드 = 개방).
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import baseline
from report import asset_report

API_VERSION = "v1"
NOTICE = ("이 응답은 자산 Evidence 데이터만 담습니다. 승인·한도·금리 등 여신 "
          "정책은 수신 기관의 소관이며(institution_policies 분리 원칙), "
          "recommended LTV는 게이트를 통과한 경우에만 참고값으로 제공됩니다.")


def envelope(env, body, **extra):
    return {"api_version": API_VERSION,
            "generated_at": datetime.now(timezone.utc)
                            .isoformat(timespec="seconds"),
            "environment": env,
            "data_provider": "DRRRK Asset Intelligence",
            "notice": NOTICE, **extra, **body}


def asset_response(conn, env, query, grade="A", asset_id=None):
    """/api/v1/asset — Evidence Report 전문 + 버전드 envelope."""
    cid, cands = baseline.find_asset(conn, query)
    if not cid:
        if cands:
            return envelope(env, {"error": "ambiguous", "candidates": cands})
        return envelope(env, {"error": "not_found", "query": query})
    report = asset_report.build(conn, cid, grade=grade, asset_id=asset_id)
    return envelope(env, {"report": report})


def assets_response(conn, env):
    """/api/v1/assets — 커버리지 목록 (자산별 표본 요약)."""
    items = []
    for cid, brand, model, ref in conn.execute(
            "select canonical_asset_id, brand, model, reference_no"
            " from asset_master where status='active' order by category, brand"):
        n_bid, n_firm = conn.execute(
            "select count(*),"
            " sum(bid_type in ('FIRM','COMMITTED','SETTLED'))"
            " from dealer_bids where canonical_asset_id=?"
            " and status != 'superseded'", (cid,)).fetchone()
        n_settled = conn.execute(
            "select count(*) from transactions where canonical_asset_id=?"
            " and transaction_type='sale' and settled_at is not null",
            (cid,)).fetchone()[0]
        items.append({"canonical_asset_id": cid, "brand": brand,
                      "model": model, "reference_no": ref,
                      "sample": {"bids": n_bid or 0, "firm_bids": n_firm or 0,
                                 "settled_sales": n_settled}})
    return envelope(env, {"assets": items, "count": len(items)})


def authorized(headers):
    """DRRRK_API_KEY가 설정된 서버에서는 Bearer 토큰 필수."""
    key = os.environ.get("DRRRK_API_KEY")
    if not key:
        return True
    return headers.get("Authorization", "") == f"Bearer {key}"
