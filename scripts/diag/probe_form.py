"""Пробник M5-разведка: открыть форму отклика БЕЗ отправки.

Шаги: открыть заказ → клик «Продолжить» (человеческая пауза) → задокументировать,
что появилось (форма отклика / модалка пополнения) → скриншот → закрыть вкладку.
Ничего не отправляем, ничего не оплачиваем.

Запуск: uv run python scripts/probe_form.py <order_id>
"""

from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from profi import config
from profi.integration.orders import human_pause, open_candidate

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
OUT = config.LOG_DIR / "m5"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: probe_form.py <order_id>")
        return 2
    order_id = sys.argv[1]

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        feed_page = next(
            pg for pg in ctx.pages if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url
        )

        # баланс из шапки бэкофиса (read-only)
        try:
            bal = feed_page.locator("a[href*='bill.php']").first
            print(f"баланс (шапка ленты): {bal.inner_text(timeout=3000)!r}")
        except Exception as e:
            print(f"баланс прочитать не удалось: {e}")

        order_page, captured = open_candidate(ctx, feed_page, order_id)
        print(f"вкладка: {order_page.url[:100]}")

        # ищем CTA: плавающий «Написать клиенту» или «Продолжить» в карточке тарифа.
        # Это не <button>-теги, поэтому текстовые/контейнерные селекторы.
        candidates_selectors = [
            "#MOBILE_TARIFF_BUTTON_CONTAINER_ID",
            '[data-testid="orderCard/tariffs"] >> text=Продолжить',
            "text=Написать клиенту",
        ]
        btn = None
        for sel in candidates_selectors:
            loc = order_page.locator(sel)
            if loc.count() > 0:
                btn = loc.first
                print(f"CTA найден: {sel!r} ({loc.count()} шт.)")
                break
        if btn is None:
            print("CTA не найден — дампим кандидатов:")
            for sel in ("text=Продолжить", "text=Написать клиенту", "a", "[role=button]"):
                loc = order_page.locator(sel)
                n = min(loc.count(), 15)
                for i in range(n):
                    try:
                        el = loc.nth(i)
                        print(
                            f"  {sel}[{i}] tag={el.evaluate('e => e.tagName')!r} "
                            f"text={el.inner_text(timeout=500)[:40]!r}"
                        )
                    except Exception:
                        pass
            time.sleep(1.5)
            order_page.close(run_before_unload=False)
            return 1

        human_pause(1.0, 2.5)
        btn.click(delay=120)
        order_page.wait_for_timeout(3000)

        # что открылось?
        bid_window = order_page.locator('[data-testid="bid_window_container"]')
        dialog = order_page.locator('[role="dialog"]')
        print(f"bid_window_container: {bid_window.count()}")
        print(f"role=dialog: {dialog.count()}")
        if bid_window.count():
            print("--- текст формы отклика ---")
            print(bid_window.first.inner_text(timeout=5000)[:2000])
            print("--- инпуты формы ---")
            for inp in bid_window.locator("input, textarea").all():
                try:
                    print(
                        f"  <{inp.evaluate('e => e.tagName')}> name={inp.evaluate('e => e.name')!r} "
                        f"placeholder={inp.evaluate('e => e.placeholder')!r}"
                    )
                except Exception:
                    pass
        elif dialog.count():
            print("--- текст диалога ---")
            print(dialog.first.inner_text(timeout=5000)[:1500])

        shot = OUT / f"form_{order_id}.png"
        order_page.screenshot(path=str(shot), full_page=True)
        print(f"скриншот: {shot.name}")

        time.sleep(2)
        order_page.close(run_before_unload=False)
        print("вкладка закрыта (ничего не отправлено)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
