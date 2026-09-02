#!/bin/bash
# general — рабочий профиль (ТГ, репетит.ру и прочее), CDP 9225
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec $CHROME --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-port=9225 \
  --user-data-dir=/root/browser-profiles/general \
  --no-first-run --no-default-browser-check about:blank
