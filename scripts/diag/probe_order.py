"""Пробник M2: открыть заказ-кандидата и собрать максимум фактуры.

Read-only по смыслу: одно штатное открытие карточки (клик по интерфейсу),
дамп BoOrderScreen JSON, текст карточки из DOM, скриншот, вкладка закрывается.
Результаты — в logs/m2/ для разбора агентом-аналитиком.

Запуск: uv run python scripts/probe_order.py <order_id>
"""

from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

from profi import config
from profi.integration.orders import (
    OrderOpenError,
    extract_dom_texts,
    open_candidate,
    parse_competition_position,
)

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
OUT = config.LOG_DIR / "m2"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: probe_order.py <order_id>")
        return 2
    order_id = sys.argv[1]

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        feed_page = next(
            pg for pg in ctx.pages if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url
        )
        try:
            order_page, captured = open_candidate(ctx, feed_page, order_id)
        except OrderOpenError as e:
            print(f"ОШИБКА: {e}")
            return 1

        print(f"вкладка открыта: {order_page.url[:110]}")
        print(f"поймано BoOrderScreen ответов: {len(captured)}")

        # 1) дампы всех BoOrderScreen
        for i, resp in enumerate(captured):
            try:
                payload = resp.json()
                path = OUT / f"bo_order_screen_{order_id}_{i}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"дамп: {path.name}")
                data = payload.get("data") or {}
                print(f"  top keys: {list(data.keys())}")
                bo = data.get("boOrderScreen")
                if isinstance(bo, dict):
                    print(f"  boOrderScreen keys: {list(bo.keys())[:20]}")
            except Exception as e:
                print(f"  ответ {i}: не JSON — {e}")

        # 2) DOM-текст карточки
        dom = extract_dom_texts(order_page)
        text_path = OUT / f"order_text_{order_id}.txt"
        text_path.write_text(
            dom.get("container_text") or dom.get("container_error", ""), encoding="utf-8"
        )
        pos = parse_competition_position(dom.get("container_text"))
        print(f"текст карточки: {text_path.name} ({len(dom.get('container_text') or '')} символов)")
        print(f"позиция отклика по рейтингу: {pos}")

        # 3) скриншот для архива
        shot = OUT / f"order_{order_id}.png"
        try:
            order_page.screenshot(path=str(shot), full_page=True)
            print(f"скриншот: {shot.name}")
        except Exception as e:
            print(f"скриншот не удался: {e}")

        # 4) баланс из шапки бэкофиса (read-only)
        try:
            header = order_page.locator("header").first
            print(f"шапка: {header.inner_text(timeout=3000)[:200]!r}")
        except Exception:
            pass

        human_pause_and_close(order_page)
    return 0


def human_pause_and_close(order_page) -> None:
    time.sleep(2)
    order_page.close(run_before_unload=False)
    print("вкладка закрыта")


if __name__ == "__main__":
    sys.exit(main())
