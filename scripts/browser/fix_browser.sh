#!/bin/bash
# fix_browser.sh <account> — перезапуск браузера аккаунта (убить зависший, поднять заново).
# Порт берётся из accounts/<account>.env; профиль — тот же (сессия сохраняется).
set -u
ACC="${1:?usage: fix_browser.sh <account>}"
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; . "$BASE/accounts/$ACC.env"; set +a

PID=$(ss -tlnp 2>/dev/null | awk -v p=":${PROFI_CDP_PORT} " 'index($0, p) {print $NF}' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID" && sleep 3
setsid "$BASE/scripts/browser/launch_account_browser.sh" "$ACC" </dev/null >> "$BASE/logs/browser-$ACC.log" 2>&1 &
sleep 6
curl -s -m 3 "http://127.0.0.1:${PROFI_CDP_PORT}/json/version" >/dev/null && echo "${PROFI_CDP_PORT} перезапущен (pid был: ${PID:-нет})"
