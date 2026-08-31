"""Проверка чатов r.php (read-only): список диалогов и непрочитанные.

Открывает СВОЮ вкладку r.php (ленту не трогает), читает текст, закрывает.
Запуск: uv run python scripts/check_chats.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

CDP = f"http://127.0.0.1:{config.CDP_PORT}"


def main() -> int:
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto("https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(4000)
            body = page.locator("body").inner_text(timeout=8000)
            print(body[:2500])
        finally:
            time.sleep(1.5)
            page.close(run_before_unload=False)
        browser.close()
    finally:
        pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
