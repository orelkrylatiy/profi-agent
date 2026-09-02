#!/bin/bash
# Headless chromium with persistent profile + CDP for profi-agent
CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
exec $CHROME --headless=new --no-sandbox --disable-dev-shm-usage   --remote-debugging-port=9223   --user-data-dir=/root/browser-profiles/profi   --no-first-run --no-default-browser-check about:blank
