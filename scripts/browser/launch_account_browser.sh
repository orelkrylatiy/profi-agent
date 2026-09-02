#!/bin/bash
# shellcheck disable=SC1090
# launch_account_browser.sh <account> — generic запуск Chrome для аккаунта
set -u
ACC="${1:?usage: launch_account_browser.sh <account>}"
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$BASE/accounts/$ACC.env"; set +a
# относительный профиль из env-файла — от корня проекта (как в config.py)
case "${PROFI_CHROME_PROFILE:-}" in
  /*) ;;
  *)  PROFI_CHROME_PROFILE="$BASE/$PROFI_CHROME_PROFILE" ;;
esac
# shellcheck disable=SC2012  # glob по фиксированному пути, ls корректен
# shellcheck disable=SC2012
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec "$CHROME" --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-port="${PROFI_CDP_PORT}" \
  --user-data-dir="${PROFI_CHROME_PROFILE}" \
  --no-first-run --no-default-browser-check about:blank
