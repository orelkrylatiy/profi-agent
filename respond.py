"""Заполнение формы отклика человеческими инпут-событиями (RULES.md).

Механика: locator.click() и keyboard.type() — настоящие trusted-события CDP;
ввод посимвольный, чанками со случайными паузами (человеческий рандом);
никаких page.evaluate-действий.

Финальная кнопка «Откликнуться» нажимается ТОЛЬКО через click_send(),
вызываемый с явного разрешения (main.py respond --send); первый запуск —
после подтверждения владельцем (RULES.md §2).
"""
from __future__ import annotations

import logging
import random
import re
import time

from playwright.sync_api import BrowserContext, Page, Response

from orders import OrderOpenError, human_pause, open_candidate

log = logging.getLogger("profi.respond")

TARIFFS_CTA = '[data-testid="orderCard/tariffs"] >> text=Продолжить'
BID_WINDOW = '[data-testid="bid_window_container"]'
PAY_BUTTON_TESTID = '[data-testid="payment_methods_form_pay_button"]'


class RespondError(Exception):
    pass


def open_respond_form(ctx: BrowserContext, feed_page: Page, order_id: str) -> Page:
    """Открыть заказ и форму отклика (без заполнения)."""
    order_page, _captured = open_candidate(ctx, feed_page, order_id)
    cta = order_page.locator(TARIFFS_CTA)
    if cta.count() == 0:
        raise RespondError("CTA «Продолжить» не найден в блоке тарифов")
    human_pause(0.8, 2.0)
    cta.first.click(delay=random.randint(70, 150))
    order_page.locator(BID_WINDOW).wait_for(timeout=15_000)
    human_pause(0.5, 1.2)
    return order_page


def _type_human(page: Page, locator, text: str) -> None:
    """Посимвольный ввод чанками по 3–9 символов, паузы 0.15–0.6 с (RULES §1)."""
    locator.click(delay=random.randint(50, 110))
    i = 0
    while i < len(text):
        chunk = text[i : i + random.randint(3, 9)]
        page.keyboard.type(chunk, delay=random.randint(45, 110))
        i += len(chunk)
        if i < len(text):
            time.sleep(random.uniform(0.15, 0.6))


def fill_form(order_page: Page, rate: int, text: str) -> dict:
    """Заполнить stavka + comments4client. Единица «час» — дефолт, не трогаем."""
    win = order_page.locator(BID_WINDOW).first
    inputs = win.locator("input")
    textarea = win.locator("textarea").first
    if textarea.count() == 0:
        raise RespondError("textarea сообщения не найдена в форме")

    human_pause(0.6, 1.5)
    # stavka — числовой INPUT (первый input в окне)
    stavka = inputs.first
    _type_human(order_page, stavka, str(rate))
    human_pause(0.7, 1.6)
    _type_human(order_page, textarea, text)

    # даём UI пересчитать цену
    order_page.wait_for_timeout(1500)
    return read_footer(order_page)


def read_footer(order_page: Page) -> dict:
    """К оплате / баланс / текст кнопки из окна формы."""
    win = order_page.locator(BID_WINDOW).first
    txt = win.inner_text(timeout=5_000)
    out = {"footer_text": txt[-400:]}
    m = re.search(r"К оплате:\s*([\d\s\u00a0]+)\s*₽", txt)
    if m:
        out["to_pay"] = int(m.group(1).replace(" ", "").replace("\u00a0", ""))
    ms = re.findall(r"([\d\s\u00a0]+)\s*₽", txt)
    if len(ms) >= 2:
        # футер: «К оплате: N ₽ … <баланс> ₽» — баланс идёт последним
        out["balance_seen"] = int(ms[-1].replace(" ", "").replace("\u00a0", ""))
    btn = order_page.locator(PAY_BUTTON_TESTID)
    if btn.count() == 0:
        btn = win.get_by_text("Откликнуться", exact=True)
    out["send_button_found"] = btn.count() > 0
    return out


def click_send(order_page: Page, ctx: BrowserContext) -> dict:
    """Нажать «Откликнуться» и собрать телеметрию отправки.

    Вызывать ТОЛЬКО с явного разрешения. Ловим RPC /backoffice/api/
    (claimOrder) и graphql-ответы вокруг клика + итоговый URL.
    """
    rpc_events: list[str] = []

    def on_response(resp: Response) -> None:
        try:
            url = resp.url
            if "/backoffice/api/" in url:
                rpc_events.append(f"rpc {url.split('/')[-1][:40]} -> {resp.status}")
        except Exception:
            pass

    ctx.on("response", on_response)
    try:
        btn = order_page.locator(PAY_BUTTON_TESTID)
        if btn.count() == 0:
            btn = order_page.locator(BID_WINDOW).first.get_by_text("Откликнуться", exact=True)
        if btn.count() == 0:
            raise RespondError("кнопка «Откликнуться» не найдена")
        human_pause(1.5, 3.0)
        btn.first.click(delay=random.randint(80, 160))
        order_page.wait_for_timeout(6000)
        outcome = {
            "rpc": rpc_events,
            "url_after": order_page.url[:120],
            "page_text_tail": "",
        }
        try:
            outcome["page_text_tail"] = order_page.locator("body").inner_text(timeout=4000)[-500:]
        except Exception:
            pass
        return outcome
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
