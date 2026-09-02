#!/bin/zsh
# Бесплатный диспетчер автопилота (launchd, без LLM на холостом ходу)
# PATH обязателен: launchd не видит ~/.local/bin (инцидент 127, аудит 2026-08-31)
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
cd "${0:A:h}/.." || exit 1
echo "[$(date '+%F %T')] диспетчер: запуск" >> logs/launchd.log
[ -f data/autopilot.lock ] && exit 0
exec uv run python -m profi.main autopilot >> logs/autopilot.log 2>&1
