#!/bin/bash
exec /root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome --no-sandbox --disable-dev-shm-usage "$@"
