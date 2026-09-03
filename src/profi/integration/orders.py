"""Открытие кандидата → новая вкладка → BoOrderScreen → FullOrder.

Спека §19–21. Правила (RULES.md): клики — Playwright locator.click()
(настоящие CDP Input-события, isTrusted), никаких page.evaluate-действий;
человеческие паузы; одна order-вкладка за раз, закрыть после обработки.
"""

from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import BrowserContext, Page, Response

from profi import config
from profi.integration.feed import _operation_name  # noqa: PLW0603 — общий контракт операции
from profi.utils.pacing import human_pause

log = logging.getLogger("profi.orders")

ORDER_OPERATION = "BoOrderScreen"


class OrderOpenError(Exception):
    pass


def _is_order_response(resp: Response) -> bool:
    try:
        req = resp.request
        if req.method != "POST" or urlparse(req.url).path != "/graphql":
            return False
        return _operation_name(req.post_data_json) == ORDER_OPERATION
    except Exception:
        return False


def _payload_order_id(payload: dict) -> str | None:
    """Order id из BoOrderScreen payload, если структура распознана."""
    try:
        orders = (payload.get("data") or {}).get("orders") or []
        if not orders:
            return None
        root = orders[0] or {}
        bo = root.get("boOrderScreen") or {}
        value = bo.get("id") or root.get("_id")
        return str(value) if value is not None else None
    except Exception:
        return None


def _responses_for_order(responses: list[Response], order_id: str) -> list[Response]:
    """Оставить только BoOrderScreen именно открываемого заказа.

    Listener висит на BrowserContext, поэтому параллельная вкладка/ручное действие
    может прислать BoOrderScreen другого заказа. Не связываем payload с кандидатом
    только по таймингу: это способно записать details B в candidate A и затем
    сгенерировать персональный отклик не тому клиенту.
    """
    matched: list[Response] = []
    expected = str(order_id)
    for resp in responses:
        try:
            if _payload_order_id(resp.json()) == expected:
                matched.append(resp)
        except Exception:
            continue
    return matched


def open_candidate(
    ctx: BrowserContext, feed_page: Page, order_id: str
) -> tuple[Page, list[Response]]:
    """Клик по карточке в ленте → новая вкладка заказа + перехваченные BoOrderScreen.

    Слушатель вешается на контекст ДО клика: ответ летит из ещё не
    существующей вкладки (спека §19).
    """
    captured: list[Response] = []

    def on_response(resp: Response) -> None:
        if _is_order_response(resp):
            captured.append(resp)

    ctx.on("response", on_response)
    try:
        card = feed_page.get_by_test_id(f"{order_id}_order-snippet")
        if card.count() == 0:
            # DOM мог стухнуть/уехать — один рефётч ленты и повторный поиск
            try:
                feed_page.reload(wait_until="domcontentloaded", timeout=45_000)
                feed_page.wait_for_timeout(2_500)
            except Exception:
                pass
            card = feed_page.get_by_test_id(f"{order_id}_order-snippet")
        if card.count() == 0:
            # Заказ ушёл с видимой страницы ленты (очередь копится часами,
            # лента перегенерируется) — это НЕ «заказ недоступен»: карточка
            # открывается напрямую по штатному URL n.php?o=<id>.
            log.info("карточки #%s нет в ленте — открываю по прямому URL", order_id)
            order_page = ctx.new_page()
            # referer ленты ОБЯЗАТЕЛЕН: без него площадка tarpitит прямую
            # навигацию — документ не приходит и за 45 с (03.09, все
            # OPEN_FAIL автопилота); с referer dcl=1.5 с.
            try:
                order_page.goto(
                    f"{config.FEED_URL}?o={order_id}",
                    wait_until="domcontentloaded",
                    timeout=45_000,
                    referer=config.FEED_URL,
                )
            except Exception:
                # Chrome бывает занят (гонка циклов воркера и автопилота,
                # тяжёлые вкладки) — один повтор вместо потери живого
                # кандидата (2026-09-03: goto Timeout на #93467476/#93467371)
                log.warning("прямой URL #%s не открылся за 45 с — повторяю", order_id)
                order_page.goto(
                    f"{config.FEED_URL}?o={order_id}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                    referer=config.FEED_URL,
                )
        else:
            card.scroll_into_view_if_needed(timeout=10_000)
            human_pause()
            with feed_page.expect_popup(timeout=20_000) as popup_info:
                card.click(delay=random.randint(60, 140))
            order_page = popup_info.value
    except OrderOpenError:
        ctx.remove_listener("response", on_response)
        raise
    except Exception as e:
        ctx.remove_listener("response", on_response)
        raise OrderOpenError(f"не смог открыть #{order_id}: {e}") from e

    try:
        order_page.wait_for_load_state("domcontentloaded", timeout=30_000)
        # Спека §19: обязательная проверка o=<orderId> в URL
        qs = parse_qs(urlparse(order_page.url).query)
        if f"{order_id}" not in (qs.get("o") or []):
            raise OrderOpenError(f"открылся не тот заказ: url={order_page.url[:120]}")
        order_page.get_by_test_id("order_card_container").wait_for(timeout=30_000)
        # даём доедреть BoOrderScreen/UpdateOrderViewingEvent
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not captured:
            order_page.wait_for_timeout(250)
        order_page.wait_for_timeout(1500)
        matched = _responses_for_order(captured, order_id)
        if captured and not matched:
            seen_ids = []
            for resp in captured:
                try:
                    seen_ids.append(_payload_order_id(resp.json()))
                except Exception:
                    seen_ids.append(None)
            raise OrderOpenError(
                f"BoOrderScreen не относится к заказу #{order_id}; пойманы ids={seen_ids}"
            )
        captured = matched
    except Exception:
        # вкладку открыли мы (popup/прямой URL): ошибка валидации не должна
        # оставлять её открытой (утечка памяти; 2026-09-03: 4 зависших
        # карточки заказа в живом Chrome). Закрываем и пробрасываем.
        try:
            order_page.close(run_before_unload=False)
        except Exception:
            pass
        raise
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
    return order_page, captured


def extract_dom_texts(order_page: Page) -> dict:
    """Selective DOM extraction (спека §20, Priority 2): UI-only поля карточки."""
    out: dict = {}
    try:
        container = order_page.get_by_test_id("order_card_container")
        out["container_text"] = container.inner_text(timeout=5_000)
        # aria_snapshot — структурированный YAML (устойчивее регэкспов, вход для LLM)
        try:
            out["container_aria"] = container.aria_snapshot()
        except Exception:
            pass
    except Exception as e:
        out["container_error"] = str(e)
    return out


def parse_competition_position(text: str | None) -> int | None:
    """«В этом заказе ваш отклик будет 16-м по рейтингу» → 16."""
    if not text:
        return None
    text = text.replace("\u00a0", " ")
    m = re.search(r"отклик будет\s+(\d+)", text)
    return int(m.group(1)) if m else None


def extract_full_order(payload: dict, dom_text: str | None) -> dict:
    """FullOrder из BoOrderScreen (Priority 1) + DOM (Priority 2).

    Живая структура (2026-08-31, лог logs/m2): data.orders[0].boOrderScreen.
    DOM добавляет профиль клиента (имя, «на Профи с», подтверждение номера,
    онлайн) и позицию отклика.
    """
    orders = (payload.get("data") or {}).get("orders") or []
    if not orders:
        raise OrderOpenError("BoOrderScreen без data.orders")
    root = orders[0]
    bo = root.get("boOrderScreen") or {}

    params: dict[str, dict] = {}
    for p in bo.get("params") or []:
        if p.get("label"):
            params[p["label"]] = p

    def param_text(*labels) -> str | None:
        for lab in labels:
            v = params.get(lab, {}).get("text")
            if v:
                return v
        return None

    geo_entries = [p for p in (bo.get("params") or []) if p.get("code") == "geo"]

    tariff_block = bo.get("tariffsBlock") or {}
    bid_form = (bo.get("bidForms") or [{}])[0] or {}
    slide = bid_form.get("bidSlideData") or {}

    full = {
        "id": str(bo.get("id") or root.get("_id")),
        "subject": bo.get("subject") or root.get("subjects"),
        "card_tags": [
            t["text"] for t in bo.get("tags") or [] if isinstance(t, dict) and t.get("text")
        ],
        "description": param_text("Описание"),
        "student": param_text("Ученик"),
        "wishes": param_text("Пожелания"),
        "address": next(
            (g.get("address", {}).get("addr") for g in geo_entries if g.get("address")), None
        ),
        "client_can_visit": param_text("Клиент может приехать"),
        "remote": param_text("Дистанционно"),
        "created_text": param_text("Детали заказа"),
        "bid_price": ((bo.get("price") or {}).get("value")),
        "has_bid": bo.get("hasBid"),
        "tariff_default": tariff_block.get("defaultTariffType"),
        "tariff_is_mono": tariff_block.get("isMonoTariff"),
        "tariffs": [
            {
                "type": t.get("type"),
                "title": t.get("title"),
                "available": t.get("isAvailable"),
                "price": (t.get("price") or {}).get("value"),
            }
            for t in tariff_block.get("tariffs") or []
        ],
        "price_hash": slide.get("priceHash"),
        "payment_info": (slide.get("paymentInfo") or {}).get("value"),
        "form_elements": [
            {
                "type": e.get("type"),
                "name": e.get("name"),
                "label": e.get("label"),
                "required": e.get("required"),
            }
            for e in slide.get("elements") or []
        ],
        "competition_position": parse_competition_position(dom_text),
        "client_block_dom": _extract_client_block(dom_text),
        "raw_bo_order_screen": bo,
    }
    return full


def _extract_client_block(dom_text: str | None) -> dict:
    """Клиент из DOM-текста карточки: имя, «на Профи с», номер, онлайн, отзывы."""
    out: dict = {}
    if not dom_text:
        return out
    text = dom_text.replace("\u00a0", " ")
    m = re.search(r"На Профи\.?\w*\s+(?:с|ру[сc]?)[^\n]*?(\d{4})", text) or re.search(
        r"На Профи[^\n]*?(\d{1,2}\s+\w+\s+\d{4})", text
    )
    if m:
        out["profile_since"] = m.group(1)
    out["phone_verified"] = "подтверди" in text.lower()
    out["last_online_online_now"] = bool(re.search(r"В сети\s*$", text, re.M))
    m = re.search(r"Оставил[аы]?\s*(\d+)\s*отзыв", text)
    if m:
        out["reviews"] = int(m.group(1))
    # имя — строка после блока «шансы на заказ» (возможна строка-аватар «О»)
    m = re.search(r"шансы на заказ[^\n]*\n+(?:[А-ЯЁ]\n+)?([А-ЯЁ][а-яё]+)\n", text)
    if m:
        out["name"] = m.group(1)
    return out
