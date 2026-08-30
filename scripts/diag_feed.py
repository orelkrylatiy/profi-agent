"""Диагностика: что реально шлёт страница ленты после reload.

Read-only: слушаем network, ничего не кликаем. Печатаем все /graphql и
/backoffice/api запросы с operationName/method/status и таймингами,
чтобы понять, когда приходит BoSearchBoardItems и приходит ли вообще.

Запуск: uv run python scripts/diag_feed.py [сек_наблюдения]
"""
from __future__ import annotations

import json
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9333"


def main() -> None:
    watch_s = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    events: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = next(pg for pg in ctx.pages if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url)
        print(f"вкладка: {page.url}")

        def on_response(resp) -> None:
            try:
                url = urlparse(resp.url)
                if url.path == "/graphql":
                    try:
                        op = (resp.request.post_data_json or {}).get("operationName")
                    except Exception:
                        op = "?"
                    events.append(f"+{time.monotonic()-t0:6.1f}s graphql op={op} -> {resp.status}")
                elif "/backoffice/api/" in url.path:
                    events.append(f"+{time.monotonic()-t0:6.1f}s rpc {url.path} -> {resp.status}")
            except Exception as e:
                events.append(f"err {e}")

        page.on("response", on_response)
        t0 = time.monotonic()
        print("reload...")
        page.reload(wait_until="domcontentloaded", timeout=45_000)
        events.append(f"+{time.monotonic()-t0:6.1f}s domcontentloaded")
        page.wait_for_timeout(watch_s * 1000)
        page.remove_listener("response", on_response)

    for line in events:
        print(line)
    graphql_ops = [l for l in events if "graphql op=" in l]
    print(f"\nитог: graphql-запросов={len(graphql_ops)}, BoSearchBoardItems={sum('BoSearchBoardItems' in l and 'Count' not in l for l in graphql_ops)}")


if __name__ == "__main__":
    main()
