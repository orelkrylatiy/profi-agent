#!/bin/bash
# run_lang.sh — запуск/подъём инстанса «Валерия» (английский+испанский, акк profi2)
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PROFI_PERSONA=lang
export PROFI_DB=/root/profi-agent/data/lang.db
export PROFI_CHROME_PROFILE=/root/profi-agent/data/browser-profiles/profi2
export PROFI_CDP_PORT=9224
export PROFI_SUBJECTS="английск,испанск,english,spanish,eng,исп"
export PROFI_RHYTHM_TAG=lang
curl -s -m 3 http://127.0.0.1:9224/json/version >/dev/null 2>&1 || \
  setsid /root/profi-agent/scripts/launch_browser2.sh </dev/null >>/root/profi-agent/logs/browser-lang.log 2>&1 &
# воркер поднимаем только если сессия залогинена (иначе бьётся в логин-стену)
if [ -f /root/profi-agent/data/lang.db ]; then
  pgrep -f "PROFI_RHYTHM_TAG=lang" >/dev/null 2>&1 || \
    cd /root/profi-agent && setsid env PROFI_RHYTHM_TAG=lang PROFI_PERSONA=lang PROFI_DB=/root/profi-agent/data/lang.db \
      PROFI_CHROME_PROFILE=/root/profi-agent/data/browser-profiles/profi2 PROFI_CDP_PORT=9224 \
      PROFI_SUBJECTS="английск,испанск,english,spanish,eng,исп" \
      xvfb-run -a uv run python -m profi.main >> logs/worker-lang.log 2>&1 &
fi
