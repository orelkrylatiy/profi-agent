#!/bin/bash
# fix_info_browser.sh — разблокировать профиль profi и поднять связку заново
set -u
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PAT='RHYTHM_TAG=inf[o]'
pkill -f "$PAT" 2>/dev/null
CHROME_PAT='browser-profiles/prof[i] '
pkill -f "$CHROME_PAT" 2>/dev/null; sleep 2
rm -f /root/browser-profiles/profi/SingletonLock /root/browser-profiles/profi/SingletonSocket /root/browser-profiles/profi/SingletonCookie 2>/dev/null
# поднимаем Chrome заново (launch_account_browser сам ставит CDP 9223)
setsid /root/profi-agent/scripts/launch_account_browser.sh info </dev/null >>/root/profi-agent/logs/browser-info.log 2>&1 &
sleep 6
curl -s -m 3 http://127.0.0.1:9223/json/version >/dev/null && echo "9223 поднялся"
bash /root/profi-agent/scripts/fix_info_worker.sh 2>&1 | tail -3
