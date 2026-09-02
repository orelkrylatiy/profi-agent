#!/bin/bash
# Бесплатный диспетчер автопилота (launchd, без LLM на холостом ходу)
# PATH обязателен: launchd не видит ~/.local/bin (инцидент exit 127, аудит 2026-08-31)
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
echo "[$(date '+%F %T')] диспетчер: запуск" >> logs/launchd.log
[ -f data/autopilot.lock ] && exit 0
exec uv run python -m profi.main autopilot >> logs/autopilot.log 2>&1
