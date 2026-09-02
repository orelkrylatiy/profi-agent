"""Разведка DOM чатов r.php (read-only): структура списка диалогов и окна чата.

Дампим aria_snapshot списка диалогов и одного диалога + инвентарь инпутов.
Запуск: uv run python scripts/probe_chat.py [order_id]
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from profi import config

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
OUT = config.LOG_DIR / "chats"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else None
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto(
                "https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000
            )
            page.wait_for_timeout(3500)
            # список диалогов: ссылки на r.php?id=
            links = page.locator('a[href*="r.php?id="]')
            n = links.count()
            print(f"диалогов-ссылок: {n}")
            for i in range(min(n, 8)):
                el = links.nth(i)
                print(f"[{i}] href={el.get_attribute('href')!r}")
                print(f"    text={el.inner_text(timeout=3000)[:180]!r}")
            (OUT / "list_aria.yaml").write_text(
                page.locator("body").aria_snapshot(), encoding="utf-8"
            )
            print("снапшот списка -> logs/chats/list_aria.yaml")

            if order_id:
                page.goto(
                    f"https://profi.ru/backoffice/r.php?id={order_id}&filter=open",
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                page.wait_for_timeout(3500)
                print("\n=== диалог ===")
                print(page.locator("body").inner_text(timeout=5000)[-1500:])
                print("\n--- инпуты ---")
                for inp in page.locator("input, textarea").all():
                    try:
                        print(
                            f"<{inp.evaluate('e => e.tagName')}> ph={inp.evaluate('e => e.placeholder')!r} "
                            f"visible={inp.is_visible()}"
                        )
                    except Exception:
                        pass
                print("--- кнопки ---")
                for b in page.locator("button").all()[:15]:
                    try:
                        if b.is_visible():
                            print("btn:", repr(b.inner_text(timeout=800)[:40]))
                    except Exception:
                        pass
                (OUT / f"dialog_{order_id}.yaml").write_text(
                    page.locator("body").aria_snapshot(), encoding="utf-8"
                )
                print(f"снапшот диалога -> logs/chats/dialog_{order_id}.yaml")
        finally:
            page.wait_for_timeout(1200)
            page.close(run_before_unload=False)
        browser.close()
    finally:
        pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
