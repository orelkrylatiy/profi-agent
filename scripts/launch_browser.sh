#!/bin/bash
# Headless chromium with persistent profile + CDP for profi-agent
# профиль — внутри проекта (data/browser-profiles/profi)
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec $CHROME --headless=new --no-sandbox --disable-dev-shm-usage   --remote-debugging-port=9223   --user-data-dir="$BASE/data/browser-profiles/profi"   --no-first-run --no-default-browser-check about:blank
