#!/bin/bash
# Headless chromium, второй акк (lang) + CDP 9224
# профиль — внутри проекта (data/browser-profiles/profi2)
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec $CHROME --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-port=9224 \
  --user-data-dir="$BASE/data/browser-profiles/profi2" \
  --no-first-run --no-default-browser-check about:blank
