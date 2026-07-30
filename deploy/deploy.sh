#!/bin/bash
# 저장소의 수집기를 실행본(~/bunjang_c2c/)으로 동기화한다.
# launchd(com.drrrk.c2c-collector, 매일 11:00)는 실행본을 돌리므로
# 코드를 수정하면 반드시 이 스크립트로 반영해야 한다.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/bunjang_collector.py"
DEST="$HOME/bunjang_c2c/bunjang_collector.py"

python3 -m py_compile "$SRC"            # 문법 오류 상태로 배포되는 것 방지
mkdir -p "$HOME/bunjang_c2c"
cp "$SRC" "$DEST"
diff -q "$SRC" "$DEST" >/dev/null && echo "배포 완료: $DEST (저장소와 동일 확인)"

# 스케줄러 등록 상태 안내 (없으면 경고만)
if launchctl list 2>/dev/null | grep -q "com.drrrk.c2c-collector"; then
  echo "launchd: com.drrrk.c2c-collector 등록됨 — 다음 11:00 실행부터 새 코드 적용"
else
  echo "경고: launchd 에 com.drrrk.c2c-collector 가 없습니다. plist 등록을 확인하세요."
fi
