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

from profi.integration.orders import open_candidate
from profi.utils.pacing import human_pause

log = logging.getLogger("profi.respond")

TARIFFS_BLOCK_TESTID = "orderCard/tariffs"
BID_WINDOW_TESTID = "bid_window_container"
PAY_BUTTON_TESTID = "payment_methods_form_pay_button"
COMMISSION_RE = re.compile("комисси", re.IGNORECASE)
# страница после клика показывает это при отказе RPC (инцидент #92799459, rpc 400)
SEND_ERROR_MARKER = "произошла ошибка"


def send_failed(outcome: dict) -> bool:
    """True, если после клика «Откликнуться» площадка показала ошибку."""
    tail = (outcome.get("page_text_tail") or "").lower()
    return SEND_ERROR_MARKER in tail


class RespondError(Exception):
    pass


SUIT_GATE_TEXT = "Вам подходит этот заказ"


def _pass_suit_gate(order_page: Page) -> bool:
    """Новый гейт на карточке: «Вам подходит этот заказ? Нет / Да».

    Если есть — человеческим кликом жмём «Да» и ждём появления блока тарифов.
    Возвращает True, если гейт был пройден.
    """
    gate = order_page.get_by_text(SUIT_GATE_TEXT, exact=False)
    if gate.count() == 0:
        return False
    human_pause(0.6, 1.4)
    yes = order_page.get_by_text("Да", exact=True)
    if yes.count() == 0:
        raise RespondError("гейт «Вам подходит этот заказ?» есть, а кнопки «Да» нет")
    yes.first.click(delay=random.randint(70, 150))
    human_pause(0.8, 1.6)
    try:
        order_page.get_by_test_id(TARIFFS_BLOCK_TESTID).first.wait_for(timeout=5_000)
    except Exception:
        # новый флоу: после «Да» тарифы не в блоке, а в модалке «Написать клиенту»
        pass
    return True


WRITE_CLIENT_CTA = "Написать клиенту"


def _open_via_write_client(order_page: Page) -> None:
    """Новый флоу (09.2026): вместо блока тарифов на карточке — CTA
    «Написать клиенту» → модалка «Выберите тариф» → «Продолжить».
    В модалке дефолт уже «Комиссия», отдельный выбор не нужен.
    """
    cta = order_page.get_by_test_id("order_card_container").get_by_text(
        WRITE_CLIENT_CTA, exact=False
    )
    if cta.count() == 0:
        raise RespondError("нет ни блока тарифов, ни CTA «Написать клиенту»")
    human_pause(0.6, 1.2)
    cta.first.click(delay=random.randint(70, 150))
    try:
        cont = order_page.get_by_text("Продолжить", exact=True)
        cont.first.wait_for(timeout=10_000)
    except Exception as exc:
        raise RespondError(f"модалка «Выберите тариф» не появилась: {exc}") from exc
    human_pause(0.8, 1.6)
    cont.first.click(delay=random.randint(70, 150))


def select_tariff(order_page: Page, mode: str) -> None:
    """Выбрать тариф отклика в блоке тарифов.

    mode="pay" (дефолт): ничего не делаем — площадка сама подставляет
    платный тариф отклика. mode="commission": человеческим кликом выбираем
    карточку «Комиссия»; если её нет/недоступна — RespondError (отправка отменится).
    """
    if mode != "commission":
        return
    block = order_page.get_by_test_id(TARIFFS_BLOCK_TESTID)
    if block.count() == 0:
        raise RespondError("блок тарифов не найден — не могу выбрать «Комиссию»")
    txt = block.first.inner_text(timeout=5_000)
    if not COMMISSION_RE.search(txt):
        raise RespondError(
            "тариф «Комиссия» недоступен на аккаунте (в блоке только платный отклик). "
            f"Текст блока: {txt[:200]!r}"
        )
    human_pause(0.6, 1.4)
    card = block.first.get_by_text(COMMISSION_RE).first
    card.click(delay=random.randint(70, 150))
    human_pause(0.5, 1.2)


def open_respond_form(
    ctx: BrowserContext, feed_page: Page, order_id: str, mode: str = "pay"
) -> Page:
    """Открыть заказ и форму отклика (без заполнения)."""
    order_page, _captured = open_candidate(ctx, feed_page, order_id)
    if order_page.get_by_test_id(TARIFFS_BLOCK_TESTID).count() == 0:
        _pass_suit_gate(order_page)
    if order_page.get_by_test_id(TARIFFS_BLOCK_TESTID).count() == 0:
        # проф.ру убрал блок тарифов: новый флоу через «Написать клиенту»
        _open_via_write_client(order_page)
        order_page.get_by_test_id(BID_WINDOW_TESTID).wait_for(timeout=15_000)
        human_pause(0.5, 1.2)
        return order_page
    select_tariff(order_page, mode)
    cta = order_page.get_by_test_id(TARIFFS_BLOCK_TESTID).get_by_text("Продолжить")
    if cta.count() == 0:
        raise RespondError("CTA «Продолжить» не найден в блоке тарифов")
    human_pause(0.8, 2.0)
    cta.first.click(delay=random.randint(70, 150))
    order_page.get_by_test_id(BID_WINDOW_TESTID).wait_for(timeout=15_000)
    human_pause(0.5, 1.2)
    return order_page


def _type_human(page: Page, locator, text: str, clear: bool = False) -> None:
    """Посимвольный ввод чанками по 3–9 символов, паузы 0.15–0.6 с (RULES §1).

    clear=True: тройной клик выделяет уже подставленное сайтом значение
    (инцидент #92799459: дефолтные 2000 + наши 2000 = «20002000»),
    печать поверх выделения его заменяет. На пустом поле безвредно.
    """
    if clear:
        locator.click(click_count=3, delay=random.randint(50, 110))
    else:
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
    win = order_page.get_by_test_id(BID_WINDOW_TESTID).first
    inputs = win.locator("input")
    textarea = win.locator("textarea").first
    if textarea.count() == 0:
        raise RespondError("textarea сообщения не найдена в форме")

    human_pause(0.6, 1.5)
    # stavka — числовой INPUT (первый input в окне); сайт может подставить
    # своё значение — тройной клик выделяет его, ввод заменяет
    stavka = inputs.first
    _type_human(order_page, stavka, str(rate), clear=True)
    got = (stavka.input_value(timeout=3_000) or "").strip()
    if got != str(rate):
        raise RespondError(
            f"поле ставки после ввода {got!r}, ожидалось {rate!r} — отправка отменена"
        )
    human_pause(0.7, 1.6)
    _type_human(order_page, textarea, text, clear=True)

    # даём UI пересчитать цену
    order_page.wait_for_timeout(1500)
    return read_footer(order_page)


def read_footer(order_page: Page) -> dict:
    """К оплате / баланс / текст кнопки из окна формы."""
    win = order_page.get_by_test_id(BID_WINDOW_TESTID).first
    txt = win.inner_text(timeout=5_000)
    out = {"footer_text": txt[-400:]}
    m = re.search(r"К оплате:\s*([\d\s\u00a0]+)\s*₽", txt)
    if m:
        out["to_pay"] = int(m.group(1).replace(" ", "").replace("\u00a0", ""))
    ms = re.findall(r"([\d\s\u00a0]+)\s*₽", txt)
    if len(ms) >= 2:
        # футер: «К оплате: N ₽ … <баланс> ₽» — баланс идёт последним
        out["balance_seen"] = int(ms[-1].replace(" ", "").replace("\u00a0", ""))
    btn = order_page.get_by_test_id(PAY_BUTTON_TESTID)
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
        btn = order_page.get_by_test_id(PAY_BUTTON_TESTID)
        if btn.count() == 0:
            btn = order_page.get_by_test_id(BID_WINDOW_TESTID).first.get_by_text(
                "Откликнуться", exact=True
            )
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
