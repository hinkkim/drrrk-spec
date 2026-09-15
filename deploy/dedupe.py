#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수집 폴더의 중복 매물을 찾아 하나만 남긴다.

판매자가 안 팔린 물건을 새 pid 로 다시 올리면 pid 검사를 통과해 버려서,
같은 물건이 날짜 폴더마다 쌓인다. 사진 지문(dHash)으로 같은 물건을 묶어
가장 먼저 수집한 것만 남기고 나머지는 치운다.

  python3 deploy/dedupe.py                 무엇이 중복인지 보기만 한다 (기본)
  python3 deploy/dedupe.py --apply         중복을 '_중복' 폴더로 옮긴다
  python3 deploy/dedupe.py --apply --delete  옮기지 않고 바로 지운다
  python3 deploy/dedupe.py --reindex       정리 없이 사진 지문만 다시 만든다

--apply 는 다음도 함께 한다
  - 남은 매물의 사진 지문을 수집기 상태(image_hashes.json)에 기록해,
    앞으로 같은 물건이 다시 들어오지 않게 한다
  - catalog.csv 에서 사라진 폴더의 줄을 지운다

기본값은 옮기기다. 지우는 건 --delete 를 명시할 때만 한다.
"""

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path.home() / "bunjang_c2c"))
import bunjang_collector as b  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
QUARANTINE = "_중복"
BANDS = 8          # 64비트를 8비트씩 나눠 후보를 좁힌다 (거리 5 이하면 반드시 한 밴드는 일치)


def listing_folders(base):
    """매물 폴더 = metadata.json 이 있는 폴더."""
    for meta in sorted(base.rglob("metadata.json")):
        folder = meta.parent
        if QUARANTINE in folder.parts:
            continue
        yield folder


def folder_hashes(folder):
    """폴더 안 이미지들의 지문. 읽을 수 없는 건 건너뛴다."""
    out = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            h = b.dhash_from_pixels(b.pixels_for_analysis(f))
        except Exception:
            h = None
        if b.usable_hash(h):       # 밋밋한 사진의 지문은 못 믿으니 판정에서 뺀다
            out.append(h)
    return out


def collected_at(folder, base):
    """수집 시각. metadata.json → 날짜 폴더명 → 파일 시각 순으로 찾는다."""
    meta = folder / "metadata.json"
    try:
        d = json.loads(meta.read_text(encoding="utf-8"))
        if d.get("collected_at"):
            return str(d["collected_at"])
    except Exception:
        pass
    for part in folder.relative_to(base).parts:
        try:
            datetime.strptime(part, "%Y-%m-%d")
            return part
        except ValueError:
            continue
    return datetime.fromtimestamp(folder.stat().st_mtime).isoformat()


class Grouper:
    """지문이 가까운 폴더끼리 묶는다 (union-find + 밴드 색인).

    사진 한 장이 겹쳤다고 묶으면 서로 다른 물건이 뭉친다. 수집기와 같은 기준으로
    서로 다른 사진이 min_matches 장 이상 겹칠 때만 같은 물건으로 본다.
    """

    def __init__(self, dist, min_matches):
        self.dist = dist
        self.min_matches = min_matches
        self.parent = {}
        self.buckets = {}      # (밴드번호, 값) → [(해시, 폴더키)]

    def find(self, x):
        while self.parent.setdefault(x, x) != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, c):
        ra, rc = self.find(a), self.find(c)
        if ra != rc:
            self.parent[ra] = rc

    def add(self, key, hashes):
        self.find(key)
        pair_hits = {}
        for h in hashes:
            matched = set()        # 이 사진 한 장이 같은 폴더를 여러 밴드로 잡아도 한 번만 센다
            for band in range(BANDS):
                slot = (band, (h >> (band * 8)) & 0xFF)
                for other_h, other_key in self.buckets.get(slot, ()):
                    if other_key != key and other_key not in matched \
                            and b.hamming(h, other_h) <= self.dist:
                        matched.add(other_key)
                self.buckets.setdefault(slot, []).append((h, key))
            for other_key in matched:
                pair_hits[other_key] = pair_hits.get(other_key, 0) + 1
        for other_key, n in pair_hits.items():
            if n >= self.min_matches:
                self.union(key, other_key)

    def groups(self):
        out = {}
        for key in self.parent:
            out.setdefault(self.find(key), []).append(key)
        return [g for g in out.values() if len(g) > 1]


def prune_catalog(base):
    """catalog.csv 에서 이제 없는 폴더의 줄을 지운다. (지운 줄 수 반환)"""
    path = base / "catalog.csv"
    if not path.exists():
        return 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    header, body = rows[0], rows[1:]
    try:
        col = header.index("폴더")
    except ValueError:
        return 0
    kept = [r for r in body if len(r) > col and (base / r[col]).is_dir()]
    removed = len(body) - len(kept)
    if removed:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(kept)
    return removed


def main():
    ap = argparse.ArgumentParser(description="수집 폴더의 중복 매물 정리")
    ap.add_argument("--base", default=None, help="수집 루트 (기본: 수집기와 동일)")
    ap.add_argument("--apply", action="store_true", help="실제로 정리한다")
    ap.add_argument("--delete", action="store_true", help="옮기지 않고 지운다")
    ap.add_argument("--reindex", action="store_true", help="정리 없이 지문만 다시 만든다")
    ap.add_argument("--dist", type=int, default=b.DUP_DIST, help=f"해밍 거리 (기본 {b.DUP_DIST})")
    ap.add_argument("--matches", type=int, default=b.DUP_MIN_MATCHES,
                    help=f"같은 물건으로 볼 최소 겹친 사진 수 (기본 {b.DUP_MIN_MATCHES})")
    args = ap.parse_args()

    base = Path(args.base).expanduser() if args.base else b.BASE_DIR
    if not base.is_dir():
        print(f"수집 폴더가 없습니다: {base}", file=sys.stderr)
        return 1

    print(f"수집 폴더: {base}")
    folders = list(listing_folders(base))
    if not folders:
        print("매물 폴더가 없습니다.")
        return 0
    print(f"매물 {len(folders)}건 검사 중...")

    hashes_by_folder = {}
    grouper = Grouper(args.dist, args.matches)
    for i, folder in enumerate(folders, 1):
        key = str(folder.relative_to(base))
        hs = folder_hashes(folder)
        hashes_by_folder[key] = hs
        grouper.add(key, hs)
        if i % 100 == 0:
            print(f"  {i}/{len(folders)}")

    no_image = [k for k, v in hashes_by_folder.items() if not v]
    if no_image:
        print(f"주의: 쓸 만한 사진 지문이 없는 폴더 {len(no_image)}건 — 중복 판정에서 제외")
        for k in no_image[:5]:
            print(f"     {k}")

    groups = grouper.groups()
    dup_count = sum(len(g) - 1 for g in groups)
    print(f"\n중복 묶음 {len(groups)}개, 치울 매물 {dup_count}건\n")

    survivors, losers = [], []
    for g in sorted(groups, key=lambda x: min(x)):
        ranked = sorted(g, key=lambda k: (collected_at(base / k, base),
                                          -len(hashes_by_folder[k]), k))
        keep, drop = ranked[0], ranked[1:]
        survivors.append(keep)
        losers.extend(drop)
        print(f"■ 남김: {keep}")
        for d in drop:
            print(f"   치움: {d}")

    survivors += [k for k in hashes_by_folder if k not in set(survivors) | set(losers)]

    if args.reindex:
        table = build_index(base, hashes_by_folder, survivors)
        print(f"\n사진 지문 {len(table)}개 기록: {b.HASH_STATE}")
        return 0

    if not args.apply:
        if dup_count:
            print("\n(보기만 했습니다. 실제로 정리하려면 --apply 를 붙이세요)")
        return 0

    moved = 0
    for k in losers:
        src = base / k
        if not src.is_dir():
            continue
        if args.delete:
            shutil.rmtree(src, ignore_errors=True)
        else:
            dst = base / QUARANTINE / k
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst = dst.with_name(f"{dst.name}_{moved}")
            shutil.move(str(src), str(dst))
        moved += 1
    verb = "삭제" if args.delete else f"'{QUARANTINE}' 로 이동"
    print(f"\n{moved}건 {verb} 완료")

    prune_empty(base)
    table = build_index(base, hashes_by_folder, survivors)
    print(f"사진 지문 {len(table)}개 기록: {b.HASH_STATE}")
    removed = prune_catalog(base)
    if removed:
        print(f"catalog.csv 에서 {removed}줄 정리")
    if not args.delete:
        print(f"\n확인 후 지우려면: rm -rf '{base / QUARANTINE}'")
    return 0


def build_index(base, hashes_by_folder, survivors):
    """남은 매물의 지문을 수집기 상태에 기록. 앞으로 같은 물건을 다시 받지 않게 한다."""
    table = b.load_hashes()
    for k in survivors:
        pid = pid_of(base / k)
        if not pid:
            continue
        for h in hashes_by_folder.get(k, ()):
            table.setdefault(f"{h:016x}", pid)
    b.save_hashes(table)
    return table


def pid_of(folder):
    try:
        return str(json.loads((folder / "metadata.json").read_text(encoding="utf-8"))["pid"])
    except Exception:
        return None


def prune_empty(base):
    """매물이 다 빠져 비어버린 날짜 폴더를 정리한다."""
    for d in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not d.is_dir() or QUARANTINE in d.parts:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
