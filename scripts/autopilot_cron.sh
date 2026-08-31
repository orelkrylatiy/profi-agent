#!/bin/zsh
# Бесплатный диспетчер автопилота (системный cron, без LLM на холостом ходу)
cd /Users/m.s.agafonov/profi || exit 1
[ -f data/autopilot.lock ] && exit 0
uv run python main.py autopilot >> logs/autopilot.log 2>&1
