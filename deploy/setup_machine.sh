#!/bin/bash
# 이 기기(집/회사 노트북)를 현재 브랜치 기준으로 정리한다.
#
#   bash deploy/setup_machine.sh          확인하며 진행
#   bash deploy/setup_machine.sh --yes    확인 없이 진행
#   bash deploy/setup_machine.sh --dry-run  무엇을 할지만 출력
#
# 하는 일
#   1. 로컬에만 있는 커밋을 백업 브랜치로 보존한 뒤 origin 상태로 맞춘다
#   2. 수집기를 실행본(~/bunjang_c2c)으로 배포한다
#   3. launchd 정리 — 수집기(11:00) 확인, 업로더(kr.drrrk.autoupload) 해제
#   4. 남은 정리거리(구 수집분, worktree)를 보고만 하고 건드리지 않는다
#
# 파일을 지우지 않는다. 되돌릴 수 없는 단계는 백업 후에만 실행한다.
set -euo pipefail

YES=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

step()  { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
info()  { printf "   %s\n" "$1"; }
warn()  { printf "   \033[33m! %s\033[0m\n" "$1"; }
todo()  { printf "   \033[36m→ %s\033[0m\n" "$1"; }

run() {
  if [ "$DRY" = 1 ]; then
    info "(dry-run) $*"
  else
    "$@"
  fi
}

confirm() {
  [ "$YES" = 1 ] && return 0
  [ "$DRY" = 1 ] && return 1
  if [ ! -t 0 ]; then
    warn "비대화형 실행 — 건너뜀. 진행하려면 --yes 를 붙이세요."
    return 1
  fi
  printf "   %s [y/N] " "$1"
  read -r reply
  case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

retry_git() {
  local i
  for i in 1 2 3 4; do
    if git "$@"; then return 0; fi
    [ "$i" = 4 ] && return 1
    sleep $((2 ** i))
  done
}

# ---------- 1. 저장소 ----------
step "저장소"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
info "경로   : $REPO"
info "브랜치 : $BRANCH"

# 추적 중인 파일의 변경만 막는다. reset --hard 는 untracked 를 건드리지 않으므로
# 프로젝트 루트에 굴러다니는 파일 때문에 작업이 막히지 않아야 한다.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  warn "커밋되지 않은 변경이 있습니다. 먼저 정리한 뒤 다시 실행하세요:"
  git status --short --untracked-files=no | sed 's/^/     /'
  exit 1
fi
UNTRACKED="$(git ls-files --others --exclude-standard)"
if [ -n "$UNTRACKED" ]; then
  info "추적되지 않는 파일 (그대로 둡니다):"
  echo "$UNTRACKED" | head -10 | sed 's/^/     /'
fi

info "origin 에서 가져오는 중..."
if ! retry_git fetch origin "$BRANCH"; then
  warn "fetch 실패 — 네트워크를 확인하세요."
  exit 1
fi

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse FETCH_HEAD)"
AHEAD="$(git rev-list --count FETCH_HEAD..HEAD)"
BEHIND="$(git rev-list --count HEAD..FETCH_HEAD)"

if [ "$LOCAL" = "$REMOTE" ]; then
  info "이미 origin 과 같습니다."
elif [ "$AHEAD" = 0 ]; then
  info "$BEHIND 개 커밋 뒤처짐 — fast-forward 합니다."
  run git merge --ff-only FETCH_HEAD
else
  # 로컬에만 있는 커밋이 있다. 이 저장소는 origin 쪽 이력이 정리된 적이 있어
  # 여기서 그냥 병합하면 이력이 갈라진다. 반드시 백업 후 맞춘다.
  warn "로컬에만 있는 커밋 $AHEAD 개 (origin 은 $BEHIND 개 앞섬) — 이력이 갈라져 있습니다."
  git log --oneline FETCH_HEAD..HEAD | sed 's/^/     /'

  BACKUP="backup/${BRANCH##*/}-$(date +%Y%m%d-%H%M)"
  info "백업 브랜치를 만듭니다: $BACKUP"
  run git branch "$BACKUP" HEAD
  if [ "$DRY" = 1 ]; then
    info "(dry-run) git push -u origin $BACKUP"
  elif retry_git push -u origin "$BACKUP"; then
    info "origin/$BACKUP 로 올렸습니다 — 이 커밋들은 안전합니다."
  else
    warn "백업 푸시 실패. 로컬 브랜치 $BACKUP 에는 남아 있습니다."
  fi

  if [ "$DRY" = 1 ]; then
    info "(dry-run) git reset --hard $(git rev-parse --short FETCH_HEAD)"
  elif confirm "$BRANCH 를 origin 상태($(git rev-parse --short FETCH_HEAD))로 맞출까요?"; then
    git reset --hard FETCH_HEAD
    info "맞췄습니다. 되돌리려면: git reset --hard $BACKUP"
  else
    warn "건너뜀 — 저장소가 origin 과 다른 상태입니다. 배포도 건너뜁니다."
    exit 1
  fi
fi
info "현재: $(git log --oneline -1 | cat)"

# ---------- 2. 실행본 배포 ----------
step "수집기 배포"
if [ "$DRY" = 1 ]; then
  info "(dry-run) bash deploy/deploy.sh"
else
  bash "$REPO/deploy/deploy.sh" | sed 's/^/   /'
fi

# ---------- 3. launchd ----------
step "launchd"
AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

# plist 가 실제로 실행하는 스크립트 경로. plutil -p 는 배열을 [ ... ] 로 찍으므로
# 범위를 ']' 까지로 끊는다 ('}' 로 끊으면 StandardErrorPath 등이 딸려 들어온다).
plist_program() {
  [ -f "$1" ] || return 0
  plutil -p "$1" 2>/dev/null \
    | awk '/ProgramArguments/,/\]/' \
    | grep -oE '"[^"]*\.(py|sh)"' | tr -d '"' | head -3
}

# 3-1. 수집기 (계속 사용)
COLLECTOR="com.drrrk.c2c-collector"
CPLIST="$AGENTS/$COLLECTOR.plist"
if launchctl list 2>/dev/null | grep -q "$COLLECTOR"; then
  info "$COLLECTOR: 등록됨 (매일 11:00)"
elif [ -f "$CPLIST" ]; then
  warn "$COLLECTOR: plist 는 있으나 미등록 — 등록합니다."
  # bootstrap 은 이미 등록돼 있으면 실패한다. 구형 load 로 한 번 더 시도하고,
  # 둘 다 실패해도 나머지 정리는 계속 진행한다.
  if ! { run launchctl bootstrap "gui/$UID_NUM" "$CPLIST" 2>/dev/null \
      || run launchctl load -w "$CPLIST" 2>/dev/null; }; then
    warn "  등록 실패 — 직접 확인하세요: launchctl load -w '$CPLIST'"
  fi
else
  warn "$COLLECTOR: plist 가 없습니다 ($CPLIST)"
  todo "이 기기에서 자동 수집을 원하면 plist 를 등록하세요."
fi
if [ -f "$CPLIST" ]; then
  for prog in $(plist_program "$CPLIST"); do
    info "  실행 대상: $prog"
    case "$prog" in
      "$HOME/bunjang_c2c/bunjang_collector.py") ;;
      *.py) warn "  실행본(~/bunjang_c2c/bunjang_collector.py)이 아닙니다 — plist 확인 필요" ;;
    esac
  done
fi

# 3-2. 업로더 (더 이상 불필요)
# 수집기가 구글드라이브에 직접 쓰므로 별도 업로드 단계가 없다.
# 이 잡의 스크립트가 git worktree 안에 있어 worktree 를 지우면 깨지기도 한다.
UPLOADER="kr.drrrk.autoupload"
UPLIST="$AGENTS/$UPLOADER.plist"
if [ -f "$UPLIST" ] || launchctl list 2>/dev/null | grep -q "$UPLOADER"; then
  info "$UPLOADER: 발견 — 수집기가 드라이브에 직접 쓰므로 더 이상 필요 없습니다."
  if confirm "$UPLOADER 를 해제할까요? (plist 는 .disabled 로 남겨 되돌릴 수 있습니다)"; then
    if ! { run launchctl bootout "gui/$UID_NUM/$UPLOADER" 2>/dev/null \
        || run launchctl unload -w "$UPLIST" 2>/dev/null; }; then
      warn "  launchctl 해제에 실패했지만, plist 를 비활성화하면 다시 뜨지 않습니다."
    fi
    if [ -f "$UPLIST" ]; then
      run mv "$UPLIST" "$UPLIST.disabled"
      info "해제했습니다. 되돌리려면:"
      info "  mv '$UPLIST.disabled' '$UPLIST' && launchctl load -w '$UPLIST'"
    fi
  else
    todo "그대로 둡니다 — 매일 10:00 에 계속 돕니다."
  fi
else
  info "$UPLOADER: 없음 (정리됨)"
fi

# ---------- 4. 남은 정리거리 (보고만) ----------
step "확인만 — 지우지 않습니다"

LEGACY="$HOME/bunjang_c2c/c2c market"
if [ -d "$LEGACY" ]; then
  SIZE="$(du -sh "$LEGACY" 2>/dev/null | cut -f1)"
  COUNT="$(find "$LEGACY" -mindepth 1 -maxdepth 2 -type d 2>/dev/null | wc -l | tr -d ' ')"
  warn "구 수집분이 로컬에 남아 있습니다: $LEGACY ($SIZE, 하위 폴더 $COUNT)"
  todo "업체 매물과 깨진 .jpg 가 섞여 있습니다. 확인 후 직접 정리하세요."
fi

WT="$(git worktree list | tail -n +2 || true)"
if [ -n "$WT" ]; then
  warn "git worktree 가 있습니다:"
  echo "$WT" | sed 's/^/     /'
  todo "업로더를 해제했다면 이제 지워도 됩니다: git worktree remove <경로>"
fi

step "정리 결과"
info "저장 위치:"
python3 - <<'PY' 2>/dev/null || info "  (수집기를 불러올 수 없어 생략)"
import os, sys
sys.path.insert(0, os.path.expanduser("~/bunjang_c2c"))
from bunjang_collector import BASE_DIR
print(f"   {BASE_DIR}")
PY
info "다음 자동 수집: 매일 11:00 ($COLLECTOR)"
info "지금 바로 받으려면: bash deploy/run_today.sh"
