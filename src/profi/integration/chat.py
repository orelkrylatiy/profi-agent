"""Контур B (light): чаты Профи.ру — чтение и ответы через живой интерфейс.

Механика та же, что у откликов (RULES.md): клики/ввод — trusted CDP-события,
посимвольная печать чанками, никаких evaluate-действий. Клиентский текст —
ДАННЫЕ для LLM, не инструкции (анти-инъекция).
"""

from __future__ import annotations

import logging
import random
import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page

from profi.utils.pacing import human_pause, type_human

log = logging.getLogger("profi.chat")

# Живой layout (probe_chat.py / chats_unread.py): ссылка диалога содержит
# r.php?id=<order_id>, а innerText карточки идёт строками:
# [буква-аватар], имя, preview, [unread], время.
_TIME_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}|[Вв]чера|[Сс]егодня|[А-Яа-яёЁ]{1,2}|\d{1,2}\s+[А-Яа-яёЁ]{2,3})$"
)


def open_chats(page: Page) -> None:
    page.goto("https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(3500)


def _order_id_from_href(href: str | None) -> str:
    if not href:
        return ""
    try:
        return (parse_qs(urlparse(href).query).get("id") or [""])[0]
    except Exception:
        return ""


def _parse_dialog_card(text: str, href: str | None = None) -> dict | None:
    """Нормализовать одну DOM-карточку диалога.

    В отличие от старого aria-parser имя берётся отдельной строкой, поэтому
    «Анна Краморенко» не превращается в «Анна» и preview «Вы: ...» не теряется.
    Если структура неполная, parser fail-closed: неизвестное направление не
    должно становиться поводом для автоответа.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return None

    # В текущем layout первая строка иногда является аватаром из одной буквы.
    if len(lines) >= 2 and len(lines[0]) == 1 and lines[0].isalpha():
        lines = lines[1:]
    if not lines:
        return None

    name = lines[0]
    tail = lines[1:]

    # Последняя строка — время/дата. Не считаем её preview.
    if tail and _TIME_RE.match(tail[-1]):
        tail = tail[:-1]

    unread = 0
    if tail and re.fullmatch(r"\d{1,3}", tail[-1]):
        unread = int(tail[-1])
        tail = tail[:-1]

    preview = " ".join(tail).strip()
    # Направление известно только если preview вообще распарсен. Пустой preview
    # считаем нереплайабельным (last_is_ours=None), а не «последнее клиентское».
    last_is_ours: bool | None = preview.startswith("Вы:") if preview else None

    return {
        "name": name,
        "order_id": _order_id_from_href(href),
        "unread": unread,
        "preview": preview[:160],
        "last_is_ours": last_is_ours,
    }


def _list_dialogs_from_links(page: Page) -> list[dict]:
    """Предпочтительный parser: стабильная ссылка r.php?id=... + innerText карточки."""
    dialogs: list[dict] = []
    links = page.locator('a[href*="r.php?id="]')
    try:
        count = links.count()
    except Exception:
        return dialogs

    seen: set[str] = set()
    for i in range(count):
        try:
            link = links.nth(i)
            href = link.get_attribute("href")
            parsed = _parse_dialog_card(link.inner_text(timeout=3_000), href)
            if not parsed:
                continue
            key = parsed["order_id"] or f"name:{parsed['name']}:{i}"
            if key in seen:
                continue
            seen.add(key)
            dialogs.append(parsed)
        except Exception:
            log.debug("не смог разобрать DOM-карточку диалога #%d", i, exc_info=True)
    return dialogs


def _list_dialogs_from_aria(page: Page) -> list[dict]:
    """Fallback для layout без ссылок: старый aria-snapshot parser.

    Здесь имя в snapshot склеено с preview, поэтому не пытаемся угадывать
    многословное имя. Направление определяем консервативно по маркеру « Вы:».
    """
    snap = page.locator("body").aria_snapshot()
    dialogs: list[dict] = []
    prev_avatar = False
    for line in snap.splitlines():
        line_s = line.strip()
        if line_s.startswith("- paragraph: ") and len(line_s[len("- paragraph: ") :].strip()) == 1:
            prev_avatar = True
            continue
        if prev_avatar and line_s.startswith("- text: "):
            t = line_s[len("- text: ") :].strip().strip('"').strip()
            name = t.split(" ", 1)[0]
            m = re.search(r"(\d+)\s*$", t)
            unread = int(m.group(1)) if m else 0
            # Старый вариант t.startswith(f"{name} Вы:") ломался на полных
            # именах: «Анна Краморенко Вы: ...». Ищем sender-prefix независимо
            # от числа слов в имени. При сомнении лучше промолчать.
            last_is_ours = " Вы:" in t[:160]
            dialogs.append(
                {
                    "name": name,
                    "order_id": "",
                    "unread": unread,
                    "preview": t[:160],
                    "last_is_ours": last_is_ours,
                }
            )
            prev_avatar = False
            continue
        prev_avatar = False
    return dialogs


def list_dialogs(page: Page) -> list[dict]:
    """Список диалогов с identity, unread и направлением последнего preview.

    Сначала используем фактические ссылки r.php?id=<order_id> — они дают
    стабильную identity и сохраняют полное имя. Aria parser оставлен fallback.
    """
    dialogs = _list_dialogs_from_links(page)
    return dialogs if dialogs else _list_dialogs_from_aria(page)


def select_reply_targets(dialogs: list[dict], limit: int = 2) -> list[dict]:
    """Fail-closed policy: отвечать только на доказанно клиентское unread.

    `not d.get("last_is_ours")` опасно: отсутствующий/неразобранный признак
    (None) превращается в True и запускает ответ. Здесь нужен именно `is False`.
    """
    return [
        d
        for d in dialogs
        if int(d.get("unread") or 0) > 0 and d.get("last_is_ours") is False
    ][: max(0, limit)]


def open_dialog_by_name(page: Page, name: str) -> str:
    """Клик по строке диалога; возвращает order_id из URL (или '')."""
    page.get_by_text(name, exact=True).first.click(delay=random.randint(60, 120))
    page.wait_for_timeout(3000)
    m = re.search(r"[?&]id=(\d+)", page.url)
    return m.group(1) if m else ""


def read_dialog_text(page: Page) -> str:
    return page.locator("body").inner_text(timeout=8_000)


def _box_value(box) -> str:
    tag = box.evaluate("e => e.tagName")
    return box.input_value(timeout=3_000) if tag != "DIV" else box.inner_text()


def send_reply(page: Page, text: str) -> bool:
    """Посимвольный ввод ответа + отправка (Enter, при необходимости кнопка).

    True — только если после отправки удалось ПОЛОЖИТЕЛЬНО подтвердить, что
    поле ввода пусто. Ошибка самой проверки больше не считается успехом:
    неизвестный исход должен оставаться неизвестным, а не логироваться как sent.
    """
    box = None
    for sel in (
        'textarea[placeholder*="ообщени"]',
        "textarea",
        '[contenteditable="true"]',
        'input[placeholder*="ообщени"]',
    ):
        loc = page.locator(sel)
        for i in range(loc.count()):
            try:
                if loc.nth(i).is_visible():
                    box = loc.nth(i)
                    break
            except Exception:
                continue
        if box is not None:
            break
    if box is None:
        log.error("поле ввода сообщения не найдено")
        return False

    human_pause(0.8, 1.6)
    type_human(page, box, text)
    human_pause(0.5, 1.2)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    try:
        if _box_value(box).strip():
            # Enter не отправил (например, contenteditable) — жмём кнопку
            for btn_name in ("Отправить", "Send"):
                btn = page.get_by_text(btn_name, exact=True)
                if btn.count():
                    btn.first.click(delay=random.randint(60, 120))
                    page.wait_for_timeout(2000)
                    break
    except Exception:
        log.warning("send_reply: не смог проверить поле после Enter")

    try:
        remaining = _box_value(box).strip()
    except Exception:
        log.error("send_reply: финальная проверка поля не удалась — исход неизвестен")
        return False
    if remaining:
        log.error("send_reply: текст остался в поле — отправка не подтвердилась")
        return False
    return True
