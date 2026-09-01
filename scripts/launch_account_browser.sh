#!/bin/bash
# launch_account_browser.sh <account> — generic запуск Chrome для аккаунта
set -u
ACC="${1:?usage: launch_account_browser.sh <account>}"
BASE=/root/profi-agent
set -a; . "$BASE/accounts/$ACC.env"; set +a
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec "$CHROME" --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-port="${PROFI_CDP_PORT}" \
  --user-data-dir="${PROFI_CHROME_PROFILE}" \
  --no-first-run --no-default-browser-check about:blank
