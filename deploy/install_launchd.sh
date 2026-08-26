#!/bin/bash
# 수집기 자동 실행(매일 11:00)을 launchd 에 등록한다. 여러 번 돌려도 안전하다.
#
#   bash deploy/install_launchd.sh            등록/갱신
#   bash deploy/install_launchd.sh --dry-run  만들 plist 내용만 출력
#
# 실행 대상은 저장소가 아니라 실행본(~/bunjang_c2c/bunjang_collector.py)이다.
# 코드를 고친 뒤에는 deploy/deploy.sh 로 실행본을 갱신해야 반영된다.
set -euo pipefail

DRY=0
case "${1:-}" in
  --dry-run|-n) DRY=1 ;;
  "") ;;
  *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
esac

LABEL="com.drrrk.c2c-collector"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"
TARGET="$HOME/bunjang_c2c/bunjang_collector.py"
LOGS="$HOME/bunjang_c2c/.state/logs"
HOUR=11
MINUTE=0

# launchd 는 PATH 를 거의 물려주지 않으므로 python3 의 절대경로를 박아 둔다.
PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY=/usr/bin/python3
if [ ! -x "$PY" ]; then
  echo "python3 를 찾지 못했습니다. Xcode Command Line Tools 를 설치하세요:" >&2
  echo "  xcode-select --install" >&2
  exit 1
fi

if [ ! -f "$TARGET" ]; then
  echo "실행본이 없습니다: $TARGET" >&2
  echo "먼저 배포하세요: bash deploy/deploy.sh" >&2
  exit 1
fi

read -r -d '' BODY <<XML || true
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$PY</string>
		<string>$TARGET</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>$HOUR</integer>
		<key>Minute</key>
		<integer>$MINUTE</integer>
	</dict>
	<key>RunAtLoad</key>
	<false/>
	<key>StandardOutPath</key>
	<string>$LOGS/launchd.out.log</string>
	<key>StandardErrorPath</key>
	<string>$LOGS/launchd.err.log</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/usr/bin:/bin:/usr/sbin:/sbin</string>
	</dict>
	<key>ProcessType</key>
	<string>Background</string>
</dict>
</plist>
XML

if [ "$DRY" = 1 ]; then
  echo "만들 파일: $PLIST"
  echo "---"
  printf '%s\n' "$BODY"
  exit 0
fi

mkdir -p "$AGENTS" "$LOGS"
printf '%s\n' "$BODY" > "$PLIST"
plutil -lint "$PLIST" >/dev/null

# 이미 등록돼 있으면 내려야 새 내용이 반영된다. 없으면 실패해도 무시한다.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null \
   || launchctl load -w "$PLIST" 2>/dev/null; then
  echo "등록 완료: $LABEL — 매일 $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
  echo "  실행: $PY $TARGET"
  echo "  로그: $LOGS/"
else
  echo "등록 실패. 직접 시도해 보세요:" >&2
  echo "  launchctl bootstrap gui/$(id -u) '$PLIST'" >&2
  exit 1
fi

echo
echo "확인:  launchctl list | grep $LABEL"
echo "해제:  launchctl bootout gui/$(id -u)/$LABEL"
