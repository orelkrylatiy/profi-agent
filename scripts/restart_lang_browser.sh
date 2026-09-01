#!/bin/bash
# restart_lang_browser.sh — перезапуск браузера lang после заливки кук
set -u
# PID по прослушиваемому порту
PID=$(ss -tlnp 2>/dev/null | awk '/:9224 /{print $NF}' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID" && sleep 3
setsid /root/profi-agent/scripts/launch_account_browser.sh lang </dev/null >>/root/profi-agent/logs/browser-lang.log 2>&1 &
sleep 6
curl -s -m 3 http://127.0.0.1:9224/json/version >/dev/null && echo "9224 перезапущен (pid был: ${PID:-нет})"
