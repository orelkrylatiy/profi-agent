"""Полный сетевой лог reload (все URL profi.ru, все типы ресурсов) + проверка SSR.

Вопрос: откуда чаты берут список диалогов — graphql, /backoffice/api/ RPC,
SSR-JSON внутри HTML, ServiceWorker-кэш? Логируем каждый запрос, а после
стабилизации ищем имена диалогов в outerHTML и в содержимом ServiceWorker.
Имена для SSR-проверки передаются аргументами (ПДн клиентов в коде не
хранятся): uv run python scripts/diag/explore_full.py chats Имя1 Имя2
"""

from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from profi import config
from profi.browser import is_feed_url

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
WATCH_S = 40


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "chats"
    names = [a for a in sys.argv[2:] if a]
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
                url = resp.url
                if "profi.ru" not in url:
                    return
                rt = resp.request.resource_type
                status = resp.status
                if rt in ("xhr", "fetch", "document"):
                    out.append(
                        f"+{time.monotonic() - t0:6.1f}s {rt:<9} {resp.request.method} {status} "
                        f"{url[:130]}"
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

        # SSR-проверка: имена диалогов прямо в HTML документа?
        if not names:
            print(
                "\n(SSR-проверка пропущена: передайте имена аргументами, "
                "например: explore_full.py chats Имя1 Имя2)"
            )
        else:
            html = target.evaluate("() => document.documentElement.outerHTML")
            for name in names:
                print(f"HTML содержит «{name}»: {name in html}")
        # ServiceWorker?
        sw = target.evaluate(
            "() => navigator.serviceWorker ? navigator.serviceWorker.controller !== null : 'no-api'"
        )
        print("ServiceWorker контролирует страницу:", sw)


if __name__ == "__main__":
    sys.exit(main())
