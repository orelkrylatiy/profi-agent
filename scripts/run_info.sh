#!/bin/bash
# run_info.sh — запуск/подъём инстанса «информатика» (акк default)
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PROFI_PERSONA=info
export PROFI_DB=/root/profi-agent/data/profi.db
export PROFI_CHROME_PROFILE=/root/browser-profiles/profi
export PROFI_CDP_PORT=9223
export PROFI_RHYTHM_TAG=info
curl -s -m 3 http://127.0.0.1:9223/json/version >/dev/null 2>&1 || \
  setsid /root/profi-agent/scripts/launch_browser.sh </dev/null >>/root/profi-agent/logs/browser-info.log 2>&1 &
pgrep -f "PROFI_RHYTHM_TAG=info" >/dev/null 2>&1 || \
  cd /root/profi-agent && setsid env PROFI_RHYTHM_TAG=info PROFI_PERSONA=info PROFI_DB=/root/profi-agent/data/profi.db \
    PROFI_CHROME_PROFILE=/root/browser-profiles/profi PROFI_CDP_PORT=9223 \
    xvfb-run -a uv run python main.py >> logs/worker-info.log 2>&1 &
