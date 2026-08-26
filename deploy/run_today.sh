#!/bin/bash
# 오늘치 수집을 한 번에 실행한다. (최신 코드 받기 → 실행본 반영 → 수집)
# 사용:  bash deploy/run_today.sh
# launchd 정기 실행(매일 11:00)과 별개로, 지금 당장 돌리고 싶을 때 쓴다.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "== 최신 코드 받기 ($BRANCH) =="
for attempt in 1 2 3 4; do
  if git pull --ff-only origin "$BRANCH"; then
    break
  fi
  if [ "$attempt" = 4 ]; then
    echo "git pull 실패." >&2
    echo "이력이 갈라져 fast-forward 가 안 되는 경우라면 먼저 정리하세요:" >&2
    echo "  bash deploy/setup_machine.sh" >&2
    exit 1
  fi
  sleep $((2 ** attempt))
done

echo
echo "== 실행본 반영 =="
bash "$REPO/deploy/deploy.sh"

echo
echo "== 수집 시작 =="
python3 "$HOME/bunjang_c2c/bunjang_collector.py"

echo
echo "== 저장 위치 =="
python3 - <<'PY'
import sys
sys.path.insert(0, __import__("os").path.expanduser("~/bunjang_c2c"))
from bunjang_collector import BASE_DIR
print(BASE_DIR)
PY
