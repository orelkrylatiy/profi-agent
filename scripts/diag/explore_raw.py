"""Reload + сырые тела graphql-ответов (content-type, первые 400 символов).

Разбираемся, почему resp.json() падает («не-JSON») и грузится ли список
диалогов вообще без фокуса/взаимодействия.
Запуск: uv run python scripts/diag/explore_raw.py [chats|feed]
"""

from __future__ import annotations

import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from profi import config
from profi.browser import is_feed_url
from profi.integration.feed import _operation_name

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
WATCH_S = 35


def op_name(req) -> str:
    """Имя graphql-операции (контракт общий с воркером: feed._operation_name)."""
    try:
        return _operation_name(req.post_data_json) or "?"
    except Exception:
        return "?"


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "chats"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=10_000)
        ctx = browser.contexts[0]
        target = None
        for pg in ctx.pages:  # первая совпавшая (единообразно с остальными пробниками)
            try:
                url = pg.url
            except Exception:
                continue
            if which == "chats" and "/r.php" in url:
                target = pg
                break
            if which == "feed" and is_feed_url(url):
                target = pg
                break
        if target is None:
            print("нет вкладки")
            return
        t0 = time.monotonic()
        out = []

        def on_response(resp) -> None:
            try:
                u = urlparse(resp.url)
                if u.path != "/graphql":
                    return
                ct = resp.headers.get("content-type", "?")
                try:
                    txt = resp.text()
                except Exception as e:
                    txt = f"<text fail {e}>"
                out.append(
                    f"\n+{time.monotonic() - t0:5.1f}s {op_name(resp.request)} "
                    f"status={resp.status} ct={ct}\n"
                    f"  body[:400]: {txt[:400]!r}"
                )
            except Exception as e:
                out.append(f"err {e}")

        target.on("response", on_response)
        target.reload(wait_until="domcontentloaded", timeout=45_000)
        deadline = time.monotonic() + WATCH_S
        while time.monotonic() < deadline:
            time.sleep(0.3)
            while out:
                print(out.pop(0))
        while out:
            print(out.pop(0))

        # DOM-факт: отрисовался ли список диалогов без фокуса/действий
        n = target.evaluate(
            "() => document.querySelectorAll"
            "('[data-testid*=chat], [class*=dialog], [class*=thread]').length"
        )
        body_len = target.evaluate("() => document.body.innerText.length")
        print(f"\nDOM: testid*chat/class*dialog узлов={n}, body text={body_len} симв.")
        print("--- конец ---")


if __name__ == "__main__":
    sys.exit(main())
