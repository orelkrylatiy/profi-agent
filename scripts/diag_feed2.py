"""Диагностика-2: как именно уходят /graphql запросы (метод, query, тело).

Read-only. Печатаем для каждого /graphql: method, query-параметры,
первые 200 символов тела запроса и первые 120 символов ответа.
"""
from __future__ import annotations

import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9333"


def main() -> None:
    watch_s = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = next(pg for pg in ctx.pages if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url)
        print(f"вкладка: {page.url}")
        t0 = time.monotonic()

        def on_response(resp) -> None:
            try:
                url = urlparse(resp.url)
                if url.path != "/graphql":
                    return
                req = resp.request
                body = req.post_data or ""
                print(f"\n+{time.monotonic()-t0:5.1f}s {req.method} {resp.status} qs={url.query[:80]!r}")
                print(f"   body[:200]: {body[:200]!r}")
                try:
                    j = resp.json()
                    data = j.get("data") or {}
                    keys = list(data.keys())
                    print(f"   resp keys: {keys[:6]}")
                except Exception:
                    print("   resp: не JSON")
            except Exception as e:
                print(f"err {e}")

        page.on("response", on_response)
        page.reload(wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(watch_s * 1000)
        page.remove_listener("response", on_response)


if __name__ == "__main__":
    main()
