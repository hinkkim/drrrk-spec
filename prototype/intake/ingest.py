#!/usr/bin/env python3
"""실데이터 입력 — REAL/BACKFILL 환경 원장의 주 입력 통로. (prototype/ 에서 실행)

  python3 intake/ingest.py template               # 입력용 CSV 템플릿 생성
  python3 intake/ingest.py events real_data.csv   # 실거래 이벤트 일괄 입력
  python3 intake/ingest.py spot gold 152000       # 금 시세 저장 (24K 1g당 원)

CSV 컬럼 (real_data_template.csv 참고):
  kind          bid | transaction | external | appraisal
  canonical_asset_id  asset_master의 표준 ID
  bid_type      bid일 때: INDICATIVE | FIRM | COMMITTED   (모르면 INDICATIVE)
  value_krw     금액(원)
  observed_at   YYYY-MM-DD
  source        출처 (bid는 buyer_id 겸용: buyer:강남A / kream / backfill:종로B)
  grade         S|A|B|C (선택 — 자산 생성용)
  environment   REAL | BACKFILL   (과거 장부 백필이면 BACKFILL)
  group_id      같은 실물의 행들을 묶는 임의 라벨 (선택 — 같은 값이면 같은 asset)
  meta_json     선택 — 예: {"days_to_sale": 12} {"loan_balance": 5000000}

주의: AI 추정가는 입력받지 않는다 — AI 가격 이벤트는 V1에서 금지 (§4).
"""
import csv
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit
from core import db as coredb
from core.evidence import BID_SOURCE_TYPE

TEMPLATE = """kind,canonical_asset_id,bid_type,value_krw,observed_at,source,grade,environment,group_id,meta_json
bid,WATCH-ROLEX-SUBMARINER-126610LN,INDICATIVE,11800000,2026-08-01,buyer:강남A,A,REAL,sub1,
bid,WATCH-ROLEX-SUBMARINER-126610LN,FIRM,12100000,2026-08-02,buyer:종로B,A,REAL,sub1,"{""expiry"": ""2026-08-09""}"
transaction,WATCH-ROLEX-SUBMARINER-126610LN,,12100000,2026-08-04,drrrk,A,REAL,sub1,"{""days_to_sale"": 3}"
external,WATCH-ROLEX-SUBMARINER-126610LN,,14900000,2026-08-01,kream,,REAL,,"{""sold"": true}"
appraisal,BAG-CHANEL-CLASSIC-MEDIUM,,13000000,2025-11-10,backfill:종로B,A,BACKFILL,ch1,
"""


def register_asset(conn, source, env="REAL", canonical_asset_id=None, grade=None,
                   registered_by=None, listing_id=None, actor=None):
    """실물 자산 1건 등록 → asset_id. canonical ID는 검증 전이면 비워둔다."""
    asset_id = str(uuid.uuid4())
    status = "AI_CANDIDATE" if canonical_asset_id else "UNIDENTIFIED"
    conn.execute(
        "insert into assets (asset_id, canonical_asset_id, data_environment,"
        " identity_status, grade, registered_by, source, listing_id)"
        " values (?,?,?,?,?,?,?,?)",
        (asset_id, canonical_asset_id, env, status, grade, registered_by,
         source, listing_id))
    audit.log(conn, actor or source, "register", "assets", asset_id,
              after={"canonical_asset_id": canonical_asset_id,
                     "identity_status": status, "environment": env})
    conn.commit()
    return asset_id


def attach_image(conn, asset_id, file_path, sha256=None, actor="drrrk"):
    image_id = str(uuid.uuid4())
    conn.execute("insert into asset_images (image_id, asset_id, file_path, sha256)"
                 " values (?,?,?,?)", (image_id, asset_id, file_path, sha256))
    audit.log(conn, actor, "insert", "asset_images", image_id,
              after={"file_path": file_path})
    conn.commit()
    return image_id


def ingest_events(conn, path):
    """CSV 일괄 입력. market/bids·transactions 모듈을 경유해 상태기계·audit을 지킨다."""
    from market import bids as mbids
    from market import transactions as mtx
    n, assets_by_group = 0, {}
    with open(path, encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            kind = row["kind"].strip()
            cid = row["canonical_asset_id"].strip()
            env = (row.get("environment") or "REAL").strip()
            meta = json.loads(row.get("meta_json") or "{}")
            src = row["source"].strip()
            if not conn.execute("select 1 from asset_master where"
                                " canonical_asset_id=?", (cid,)).fetchone():
                sys.exit(f"{path}:{i} 미등록 canonical ID: {cid} — "
                         "catalog_seed.csv에 먼저 추가하세요.")
            if kind == "external":
                stype = "EXTERNAL_SOLD" if meta.get("sold") else "PUBLIC_LISTING"
                mid = str(uuid.uuid4())
                conn.execute(
                    "insert into market_events (market_event_id, canonical_asset_id,"
                    " source_type, price_krw, source, data_environment, observed_at,"
                    " meta) values (?,?,?,?,?,?,?,?)",
                    (mid, cid, stype, int(row["value_krw"]), src, env,
                     row["observed_at"], json.dumps(meta, ensure_ascii=False)))
                audit.log(conn, src, "insert", "market_events", mid)
                n += 1
                continue

            aid = _asset_for(conn, assets_by_group, row, cid, env)
            if kind == "bid":
                mbids.place_bid(conn, aid, buyer_id=src,
                                price_krw=int(row["value_krw"]),
                                bid_type=(row.get("bid_type") or "INDICATIVE").strip(),
                                bid_time=row["observed_at"],
                                expiry=meta.get("expiry"), env=env, actor=src)
            elif kind == "transaction":
                mtx.record_transaction(
                    conn, aid, transaction_type=meta.get("type", "sale"),
                    gross_price_krw=int(row["value_krw"]),
                    contracted_at=row["observed_at"],
                    settled_at=meta.get("settled_at", row["observed_at"]),
                    days_to_sale=meta.get("days_to_sale"),
                    costs_unknown=1, source=src, env=env, actor=src, meta=meta)
            elif kind == "appraisal":
                apid = str(uuid.uuid4())
                stype = ("PARTNER_HISTORICAL" if env == "BACKFILL"
                         else "EXPERT_ESTIMATE")
                conn.execute(
                    "insert into appraisals (appraisal_id, asset_id,"
                    " canonical_asset_id, value_krw, appraised_by, source_type,"
                    " data_environment, meta, observed_at) values (?,?,?,?,?,?,?,?,?)",
                    (apid, aid, cid, int(row["value_krw"]), src, stype, env,
                     json.dumps(meta, ensure_ascii=False), row["observed_at"]))
                audit.log(conn, src, "insert", "appraisals", apid)
            else:
                sys.exit(f"{path}:{i} 알 수 없는 kind: {kind}")
            n += 1
    conn.commit()
    print(f"실데이터 {n}건 입력 완료 (자산 {len(assets_by_group)}개 생성)")
    return n


def _asset_for(conn, cache, row, cid, env):
    """group_id가 같으면 같은 실물로 취급. 없으면 (cid, grade, source) 단위."""
    key = row.get("group_id") or f"{cid}|{row.get('grade')}|{row['source']}"
    if key not in cache:
        cache[key] = register_asset(
            conn, source=row["source"], env=env, canonical_asset_id=cid,
            grade=(row.get("grade") or None), actor="ingest")
    return cache[key]


def save_spot(conn, metal, price):
    conn.execute("insert or replace into spot_price values (?,?,?)",
                 (metal, price, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    print(f"{metal} 시세 저장: {price:,.0f}원/g (24K 기준)")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if cmd == "template":
        path = os.path.join(root, "real_data_template.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE)
        print(f"템플릿 생성: {path}")
        return
    conn = coredb.connect("REAL")
    if cmd == "spot":
        save_spot(conn, sys.argv[2], float(sys.argv[3]))
    elif cmd == "events":
        ingest_events(conn, sys.argv[2])
    else:
        sys.exit(__doc__)
    conn.close()


if __name__ == "__main__":
    main()
