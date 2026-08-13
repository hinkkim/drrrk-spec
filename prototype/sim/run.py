#!/usr/bin/env python3
"""드르륵 자산 언더라이팅 원장 프로토타입 — 실행 진입점.

사용법 (prototype/ 디렉토리에서):
  python3 sim/run.py                  # 기본 시뮬레이션 (365일, 하루 2건)
  python3 sim/run.py --days 730 --listings-per-day 3
  python3 sim/run.py --compare        # 1차 단계 정확도 시나리오 비교 (85/95/99%)

의존성: 파이썬 3.9+ 표준 라이브러리만 사용 (설치 불필요).
출력: drrrk_sim.db (SQLite, SIMULATION 환경 전용),
      reports/asset_scores.json, reports/summary.md

시뮬레이션 데이터는 실DB(drrrk_real.db)와 물리적으로 분리된다 (§12).
이 모듈은 데모가 아니라 회귀 테스트·백테스트 하네스다.
"""
import argparse
import csv
import os
import sqlite3
import sys
from datetime import timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ROOT는 뒤에 — sim 내부 모듈(report.py 등)이 우선

from simulate import run_simulation, START
from metrics import compute_metrics
from report import write_reports, pollution_stats, overall_mape
from migrate_v1 import migrate

HERE = os.path.dirname(os.path.abspath(__file__))   # sim/
ROOT = os.path.dirname(HERE)                        # prototype/


def init_db(path):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("create table _seed_meta (canonical_asset_id text primary key,"
                 " base_retail_krw integer, popularity integer)")
    with open(os.path.join(ROOT, "catalog_seed.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("insert into asset_master (canonical_asset_id, category, brand,"
                         " model, reference_no, aliases) values (?,?,?,?,?,?)",
                         (row["canonical_asset_id"], row["category"], row["brand"],
                          row["model"], row["reference_no"], row["aliases"]))
            conn.execute("insert into _seed_meta values (?,?,?)",
                         (row["canonical_asset_id"], int(row["base_retail_krw"]),
                          int(row["popularity"])))
    conn.commit()
    return conn


def run_once(args, id_accuracy, db_suffix=""):
    db = os.path.join(ROOT, f"drrrk_sim{db_suffix}.db")
    conn = init_db(db)
    params = dict(days=args.days, listings_per_day=args.listings_per_day,
                  seed=args.seed, id_accuracy=id_accuracy,
                  grade_accuracy=args.grade_accuracy, fake_detection=args.fake_detection)
    stats = run_simulation(conn, **params,
                           counterfeit_rate=0.02, sale_conversion=0.60,
                           backfill_pawn_deals=args.backfill)
    compute_metrics(conn, as_of=START + timedelta(days=args.days))
    migrate(conn, "SIMULATION")  # v1 테이블에도 이식 — 마이그레이션 코드의 상시 검증
    return conn, stats, params


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--listings-per-day", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--id-accuracy", type=float, default=0.95)
    ap.add_argument("--grade-accuracy", type=float, default=0.80)
    ap.add_argument("--fake-detection", type=float, default=0.90)
    ap.add_argument("--backfill", type=int, default=300)
    ap.add_argument("--compare", action="store_true",
                    help="1차 단계(식별) 정확도 85/95/99%% 시나리오 비교")
    args = ap.parse_args()

    if args.compare:
        n_seeds = 5
        print(f"1차 단계(자산 식별) 정확도 시나리오 비교 — seed {n_seeds}개 평균, 동일 거래량\n")
        print(f"{'식별정확도':>8} | {'오염 이벤트':>8} | {'MAPE':>6} | {'Spread':>7} | {'평균 권장LTV':>9}")
        print("-" * 55)
        base_seed = args.seed
        for acc in (0.85, 0.95, 0.99):
            agg = {"poll": [], "mape": [], "spread": [], "ltv": []}
            for s in range(n_seeds):
                args.seed = base_seed + s
                conn, stats, params = run_once(args, acc, db_suffix=f"_{int(acc*100)}")
                poll = pollution_stats(conn)
                m = overall_mape(conn)
                agg["poll"].append(poll["polluted_price_events_pct"])
                agg["mape"].append(m["mape_pct"])
                agg["spread"].append(m["spread_pct"])
                agg["ltv"].append(m["avg_ltv_pct"])
                conn.close()
            avg = {k: round(sum(v) / len(v), 1) for k, v in agg.items()}
            print(f"{acc*100:>7.0f}% | {avg['poll']:>7}% | {avg['mape']:>5}% | "
                  f"{avg['spread']:>6}% | {avg['ltv']:>8}%")
        print("\n→ 식별 정확도가 원장 오염도·추정오차·스프레드를 직접 결정한다.")
        print("  (오염 이벤트 = 잘못된 자산 ID에 귀속된 견적/성사가 비율)")
        return

    conn, stats, params = run_once(args, args.id_accuracy)
    path = write_reports(conn, os.path.join(ROOT, "reports"), stats, params)
    poll = pollution_stats(conn)
    print(f"시뮬레이션 완료: 등록 {stats['listings']} / 견적 {stats['quotes']} / "
          f"성사 {stats['sales']} / 가품차단 {stats['fake_rejected']}")
    print(f"1차 단계 오염도: 오식별 {poll['misid_rate_pct']}%, "
          f"오염 가격 이벤트 {poll['polluted_price_events_pct']}%")
    print(f"리포트: {path}")
    conn.close()


if __name__ == "__main__":
    main()
