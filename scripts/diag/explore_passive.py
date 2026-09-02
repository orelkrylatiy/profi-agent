"""Пассивный сетевой сканер Профи.ру (read-only, БЕЗ действий и reload).

Вешает слушателей на уже открытые вкладки (лента n.php, чаты r.php,
order-вкладки ?o=) и 45 секунд пишет ВСЁ, что уходит в сеть:
/graphql операции, /backoffice/api/ RPC, websocket, eventsource, polling.
Цель: понять, как сайт сам обновляет данные — есть ли push/poll,
и на что реально может опираться воркер вместо reload ленты.

Содержимое WS-кадров НЕ печатаем (там переписка клиентов — ПДн),
только факт и размер кадра.
"""

from __future__ import annotations

import sys
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from profi import config
from profi.browser import is_feed_url
from profi.integration.feed import _operation_name

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
WATCH_S = 45


def op_name(req) -> str:
    """Имя graphql-операции (контракт общий с воркером: feed._operation_name)."""
    try:
        return _operation_name(req.post_data_json) or "?"
    except Exception:
        return "?"


def main() -> None:
    events: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=10_000)
        ctx = browser.contexts[0]
        targets = {}
        for pg in ctx.pages:
            try:
                url = pg.url
            except Exception:
                continue
            if "profi.ru/backoffice" not in url:
                continue
            if "/r.php" in url:
                targets["chats"] = pg
            elif is_feed_url(url):
                targets["feed"] = pg
            elif parse_qs(urlparse(url).query).get("o"):
                targets.setdefault("order", pg)  # первая order-вкладка
        print("наблюдаемые вкладки:", {k: v.url[:80] for k, v in targets.items()})

        t0 = time.monotonic()

        def mk_handlers(tag: str, page):
            def on_request(req) -> None:
                try:
                    rt = req.resource_type
                    u = urlparse(req.url)
                    if rt == "websocket":
                        events.append(
                            f"+{time.monotonic() - t0:6.1f}s [{tag}] WS OPEN {req.url[:110]}"
                        )
                        return
                    if rt == "eventsource":
                        events.append(
                            f"+{time.monotonic() - t0:6.1f}s [{tag}] SSE OPEN {req.url[:110]}"
                        )
                        return
                    if u.path == "/graphql":
                        events.append(
                            f"+{time.monotonic() - t0:6.1f}s [{tag}] GQL {req.method} "
                            f"op={op_name(req)} qs={u.query[:60]}"
                        )
                    elif "/backoffice/" in u.path and rt in ("xhr", "fetch"):
                        events.append(
                            f"+{time.monotonic() - t0:6.1f}s [{tag}] RPC {req.method} {u.path[:90]}"
                        )
                except Exception as e:
                    events.append(f"[{tag}] req-err {e}")

            def on_ws(ws) -> None:
                events.append(f"+{time.monotonic() - t0:6.1f}s [{tag}] WEBSOCKET {ws.url[:110]}")

                def on_frame(payload) -> None:
                    # содержимое не печатаем — там может быть переписка (ПДн)
                    events.append(
                        f"+{time.monotonic() - t0:6.1f}s [{tag}] WS<< frame len={len(str(payload))}"
                    )

                ws.on("framereceived", on_frame)

            page.on("request", on_request)
            page.on("websocket", on_ws)

        for tag, pg in targets.items():
            mk_handlers(tag, pg)

        deadline = time.monotonic() + WATCH_S
        while time.monotonic() < deadline:
            time.sleep(1)
            while events:
                print(events.pop(0))
        while events:
            print(events.pop(0))
        print("--- конец окна наблюдения ---")


if __name__ == "__main__":
    sys.exit(main())
