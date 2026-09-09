#!/bin/bash
# fix_lang_browser.sh — полный цикл восстановления акка lang после OOM
set -u
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /root/profi-agent

# 1) всё, что связано с profi2 — под нож (воркер + хромы)
WPAT='RHYTHM_TAG=lan[g]'
pkill -f "$WPAT" 2>/dev/null
CPAT='browser-profiles/profi[2]'
pkill -f "$CPAT" 2>/dev/null
sleep 2

# 2) general-браузер (9225) пока глушим: не залогинен, жрёт память
GPAT='browser-profiles/genera[l]'
pkill -f "$GPAT" 2>/dev/null

# 3) снимаем singleton-локи и поднимаем хром заново
rm -f /root/browser-profiles/profi2/Singleton* 2>/dev/null
setsid scripts/launch_account_browser.sh lang </dev/null >> logs/browser-lang.log 2>&1 &
sleep 6
curl -s -m 3 http://127.0.0.1:9224/json/version >/dev/null && echo "9224 поднялся"

# 4) воркер заново
set -a; . accounts/lang.env; set +a
export PROFI_DB=data/lang.db PROFI_CHROME_PATH=/root/profi-agent/scripts/chrome-vps.sh
setsid env PROFI_RHYTHM_TAG=lang PROFI_PERSONA=lang PROFI_DB="$PWD/data/lang.db" \
  PROFI_CHROME_PROFILE=/root/browser-profiles/profi2 PROFI_CDP_PORT=9224 \
  PROFI_SUBJECTS="$PROFI_SUBJECTS" PROFI_CHROME_PATH=/root/profi-agent/scripts/chrome-vps.sh \
  xvfb-run -a uv run python main.py >> logs/worker-lang.log 2>&1 &
sleep 8
free -m | head -2
tail -2 logs/worker-lang.log
