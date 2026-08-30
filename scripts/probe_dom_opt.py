"""Пробник DOM-оптимизаций Playwright (read-only, без reload/кликов).

Проверяем на живой ленте:
1. pw.selectors.set_test_id_attribute("data-testid") + get_by_test_id
2. aria_snapshot() карточки заказа — структурированный YAML вместо inner_text
3. сравнение движков: css :has-text vs get_by_text (время резолва)
4. tracing start/stop -> zip для playwright show-trace

Запуск: uv run python scripts/probe_dom_opt.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
OUT = config.LOG_DIR / "dom_opt"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    pw = sync_playwright().start()
    try:
        pw.selectors.set_test_id_attribute("data-testid")
        browser = pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = next(
            pg for pg in ctx.pages
            if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url
        )
        print(f"вкладка: {page.url[:60]}")

        ctx.tracing.start(screenshots=True, snapshots=True, sources=False)

        # 1) все карточки заказов (css-suffix — реестр testid)
        cards_all = page.locator('a[data-testid$="_order-snippet"]')
        n = cards_all.count()
        print(f"css-suffix карточек: {n}")

        first_id = cards_all.first.get_attribute("data-testid")
        print(f"первый testid: {first_id}")
        t0 = time.perf_counter()
        card = page.get_by_test_id(first_id)
        card.hover(timeout=5000)
        print(f"get_by_testid + hover: {(time.perf_counter()-t0)*1000:.0f} мс")

        # 2) aria_snapshot карточки — YAML для LLM
        snap = card.aria_snapshot()
        (OUT / "card_aria_snapshot.yaml").write_text(snap, encoding="utf-8")
        print(f"aria_snapshot карточки ({len(snap)} симв.) -> logs/dom_opt/card_aria_snapshot.yaml")
        print("--- первые строки ---")
        print("\n".join(snap.splitlines()[:18]))

        # 3) движки текста (read-only резолв)
        t0 = time.perf_counter()
        c1 = page.locator("button:has-text('Какой заказ ищете?')").count()
        t_css = time.perf_counter() - t0
        t0 = time.perf_counter()
        c2 = page.get_by_text("Какой заказ ищете?").count()
        t_text = time.perf_counter() - t0
        print(f"css :has-text: {t_css*1000:.1f} мс (count={c1}) | get_by_text: {t_text*1000:.1f} мс (count={c2})")

        # 4) роль-ориентированный подсчёт
        t0 = time.perf_counter()
        links = page.get_by_role("link").count()
        print(f"get_by_role('link'): {links} ссылок за {(time.perf_counter()-t0)*1000:.0f} мс")

        ctx.tracing.stop(path=str(OUT / "trace.zip"))
        print("трейс: logs/dom_opt/trace.zip — смотреть: uv run playwright show-trace logs/dom_opt/trace.zip")
        browser.close()
    finally:
        pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
