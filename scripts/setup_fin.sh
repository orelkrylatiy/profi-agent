#!/bin/bash
# setup_fin.sh — финальная обвязка мультиакка (18:31 UTC 2026-09-01)
set -u
cd /root/profi-agent
chmod +x scripts/rhythm_keeper.sh scripts/run_info.sh scripts/run_lang.sh scripts/launch_browser2.sh scripts/chats_unread.py

# cron-обёртка autopilot для второго акка (Валерия)
cat > /root/profi-autopilot2-cron.sh << 'EOF'
#!/bin/bash
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PROFI_PERSONA=lang
export PROFI_DB=/root/profi-agent/data/lang.db
export PROFI_CHROME_PROFILE=/root/profi-agent/data/browser-profiles/profi2
export PROFI_CDP_PORT=9224
export PROFI_SUBJECTS="английск,испанск,english,spanish,eng,исп"
cd /root/profi-agent
[ -f data/lang_ready ] || exit 0   # воркер после логина второго акка
exec xvfb-run -a uv run python main.py autopilot
EOF
chmod +x /root/profi-autopilot2-cron.sh

# перезапуск info-воркера под тегом (rhythm-кипер сможет им управлять)
PAT='main\.py'
pkill -f "xvfb-run -a uv run python ${PAT}" 2>/dev/null
sleep 2
bash scripts/run_info.sh
sleep 3

# кроны: ритм каждые 15 мин + lang autopilot
( crontab -l 2>/dev/null | grep -v rhythm_keeper | grep -v autopilot2
  echo "*/15 * * * * /root/profi-agent/scripts/rhythm_keeper.sh >> /root/profi-agent/logs/rhythm.log 2>&1"
  echo "17,47 * * * * /root/profi-autopilot2-cron.sh >> /root/profi-agent/logs/autopilot2-cron.log 2>&1"
) | crontab -

echo "--- crontab:"; crontab -l | tail -3
echo "--- тег-воркер info:"; pgrep -fc "RHYTHM_TAG=info" || true
echo "--- браузеры:"; curl -s -m 3 http://127.0.0.1:9223/json/version >/dev/null && echo "9223 ok"; curl -s -m 3 http://127.0.0.1:9224/json/version >/dev/null && echo "9224 ok"
