"""Диагностика гейта «Вам подходит этот заказ?» на карточке заказа.

Read-only + один клик «Да» (тот же, что делает respond.py). Ничего не отправляем.
Дампим состояние карточки ДО гейта и ПОСЛЕ клика «Да», скриншоты в logs/m5/.

Запуск: python scripts/diag/probe_gate.py <order_id>
env: PROFI_CDP_PORT=9223 и PYTHONPATH=src
"""

from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from profi import config
from profi.integration.orders import human_pause, open_candidate
from profi.integration.respond import (
    SUIT_GATE_TEXT,
    TARIFFS_BLOCK_TESTID,
    WRITE_CLIENT_CTA,
)

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
OUT = config.LOG_DIR / "m5"
OUT.mkdir(parents=True, exist_ok=True)


def dump(page, tag: str, order_id: str) -> None:
    def q(desc, fn):
        try:
            print(f"  [{tag}] {desc}: {fn()}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{tag}] {desc}: ERR {type(exc).__name__}: {str(exc)[:120]}")

    print(f"--- dump {tag} @ {time.strftime('%H:%M:%S')} url={page.url[:90]}")
    q("tariffs testid count", lambda: page.get_by_test_id(TARIFFS_BLOCK_TESTID).count())
    q("gate text count", lambda: page.get_by_text(SUIT_GATE_TEXT, exact=False).count())
    q(
        "CTA «Написать клиенту»",
        lambda: (
            page.get_by_test_id("order_card_container")
            .get_by_text(WRITE_CLIENT_CTA, exact=False)
            .count()
        ),
    )
    q("bid_window", lambda: page.get_by_test_id("bid_window_container").count())
    q("«Продолжить» anywhere", lambda: page.get_by_text("Продолжить", exact=True).count())
    q("«Да» buttons", lambda: page.get_by_text("Да", exact=True).count())

    try:
        cont = page.get_by_test_id("order_card_container")
        txt = cont.inner_text(timeout=5000)
        tail = txt[-1500:].replace("\n", " | ")
        print(f"  [{tag}] card tail: {tail}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [{tag}] card container ERR: {exc}")

    try:
        page.screenshot(path=str(OUT / f"{order_id}_{tag}.png"), full_page=False)
        print(f"  [{tag}] screenshot -> {OUT / (order_id + '_' + tag + '.png')}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [{tag}] screenshot ERR: {exc}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: probe_gate.py <order_id>")
        return 2
    order_id = sys.argv[1]

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        feed_page = next(
            pg for pg in ctx.pages if "profi.ru/backoffice/n.php" in pg.url and "o=" not in pg.url
        )
        page, _ = open_candidate(ctx, feed_page, order_id)
        try:
            dump(page, "before", order_id)
            gate = page.get_by_text(SUIT_GATE_TEXT, exact=False)
            if gate.count() > 0:
                yes = page.get_by_text("Да", exact=True)
                print(f"gate present, «Да» count={yes.count()} → кликаю первый")
                if yes.count() > 0:
                    human_pause(0.6, 1.2)
                    yes.first.click(delay=100)
                    human_pause(1.0, 1.6)
                    dump(page, "after_yes", order_id)
                    # ждём как respond.py — 5 сек на блок тарифов
                    try:
                        page.get_by_test_id(TARIFFS_BLOCK_TESTID).first.wait_for(timeout=5_000)
                        print("tariffs block ПОЯВИЛСЯ в течение 5с")
                        dump(page, "after_wait", order_id)
                    except Exception:
                        print("tariffs block НЕ появился за 5с (как в ошибке воркера)")
            else:
                print("гейта нет — карточка сразу в другом состоянии")
            print("HOLD 60s: вкладка открыта для ручного осмотра, потом закрою")
            page.wait_for_timeout(60_000)
        finally:
            try:
                page.close(run_before_unload=False)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
