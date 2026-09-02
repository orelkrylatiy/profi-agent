#!/bin/bash
# fix_info_worker.sh — поднять info-воркер (без самоубийства pkill'ом)
set -u
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PAT='RHYTHM_TAG=inf[o]'
pkill -f "$PAT" 2>/dev/null; sleep 1
cd /root/profi-agent
setsid env PROFI_RHYTHM_TAG=info PROFI_PERSONA=info PROFI_DB=/root/profi-agent/data/profi.db \
  PROFI_CHROME_PROFILE=/root/profi-agent/data/browser-profiles/profi PROFI_CDP_PORT=9223 PROFI_CHROME_PATH=/root/profi-agent/scripts/chrome-vps.sh \
  xvfb-run -a uv run python main.py >> logs/worker-info.log 2>&1 &
sleep 8
echo "живых info-воркеров: $(pgrep -fc "$PAT")"
tail -3 logs/worker-info.log
