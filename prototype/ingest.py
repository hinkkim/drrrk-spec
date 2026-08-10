#!/usr/bin/env python3
"""실데이터 입력 — 시뮬레이션이 아닌 진짜 데이터로 원장을 키우는 통로.

사용법:
  python3 ingest.py spot gold 152000        # 금 시세 저장 (24K 1g당 원, 한국금거래소 고시가 참고)
  python3 ingest.py events real_data.csv    # 실거래 이벤트 일괄 입력
  python3 ingest.py template                # 입력용 CSV 템플릿 생성

CSV 컬럼 (real_data.csv):
  canonical_asset_id  asset_master에 있는 표준 ID (analyze.py list 로 확인)
  event_type          buyer_quote | contract_price | external_comp |
                      backfill_appraisal | backfill_loan | backfill_liquidation
  deal_type           sale | pawn | external
  value_krw           금액(원)
  observed_at         YYYY-MM-DD
  source              출처 (예: buyer:강남A, kream, backfill:종로B)
  grade               S|A|B|C (선택 — instance 생성용)
  meta_json           선택 — 예: {"days_to_sale": 12} {"loan_balance": 5000000,
                      "days_to_liquidate": 30}
"""
import csv
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "drrrk_ledger.db")

TEMPLATE = """canonical_asset_id,event_type,deal_type,value_krw,observed_at,source,grade,meta_json
WATCH-ROLEX-SUBMARINER-126610LN,buyer_quote,sale,11800000,2026-08-01,buyer:강남A,A,
WATCH-ROLEX-SUBMARINER-126610LN,buyer_quote,sale,12100000,2026-08-01,buyer:종로B,A,
WATCH-ROLEX-SUBMARINER-126610LN,contract_price,sale,12100000,2026-08-04,drrrk,A,"{""days_to_sale"": 3}"
WATCH-ROLEX-SUBMARINER-126610LN,external_comp,external,14900000,2026-08-01,kream,,
BAG-CHANEL-CLASSIC-MEDIUM,backfill_appraisal,pawn,13000000,2025-11-10,backfill:종로B,A,
BAG-CHANEL-CLASSIC-MEDIUM,backfill_loan,pawn,7800000,2025-11-10,backfill:종로B,A,"{""ltv"": 0.6}"
BAG-CHANEL-CLASSIC-MEDIUM,backfill_liquidation,pawn,10400000,2026-03-02,backfill:종로B,A,"{""loan_balance"": 8100000, ""days_to_liquidate"": 28, ""cost_pct"": 0.05}"
"""


def connect():
    if not os.path.exists(DB):
        conn = sqlite3.connect(DB)
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        _seed_catalog(conn)
        print("원장 DB 신규 생성 (카탈로그 시드 포함)")
    else:
        conn = sqlite3.connect(DB)
    conn.execute("create table if not exists spot_price ("
                 "metal text primary key, krw_per_g real not null, updated_at text)")
    return conn


def _seed_catalog(conn):
    with open(os.path.join(HERE, "catalog_seed.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("insert or ignore into asset_master (canonical_asset_id,"
                         " category, brand, model, reference_no, aliases) values (?,?,?,?,?,?)",
                         (row["canonical_asset_id"], row["category"], row["brand"],
                          row["model"], row["reference_no"], row["aliases"]))
    conn.commit()


def ingest_events(conn, path):
    cur = conn.cursor()
    n, instances = 0, {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["canonical_asset_id"].strip()
            if not cur.execute("select 1 from asset_master where canonical_asset_id=?",
                               (cid,)).fetchone():
                sys.exit(f"미등록 자산 ID: {cid} — catalog_seed.csv 에 먼저 추가하세요.")
            key = (cid, row.get("grade") or "A", row["source"])
            if row["event_type"] != "external_comp":
                if key not in instances:
                    iid = str(uuid.uuid4())
                    cur.execute("insert into asset_instance (instance_id,"
                                " canonical_asset_id, grade, source) values (?,?,?,?)",
                                (iid, cid, row.get("grade") or "A", "real"))
                    instances[key] = iid
                iid = instances[key]
            else:
                iid = None
            meta = row.get("meta_json") or "{}"
            json.loads(meta)  # 유효성 검사
            cur.execute("insert into valuation_event (event_id, instance_id,"
                        " canonical_asset_id, deal_type, event_type, value_krw,"
                        " observed_at, source, meta) values (?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), iid, cid, row["deal_type"],
                         row["event_type"], int(row["value_krw"]),
                         row["observed_at"], row["source"], meta))
            n += 1
    conn.commit()
    print(f"실데이터 {n}건 입력 완료 (instance {len(instances)}개 생성)")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "template":
        path = os.path.join(HERE, "real_data_template.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE)
        print(f"템플릿 생성: {path}")
        return
    conn = connect()
    if cmd == "spot":
        metal, price = sys.argv[2], float(sys.argv[3])
        conn.execute("insert or replace into spot_price values (?,?,?)",
                     (metal, price, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        print(f"{metal} 시세 저장: {price:,.0f}원/g (24K 기준)")
    elif cmd == "events":
        ingest_events(conn, sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
