"""Контур B (light): чаты Профи.ру — чтение и ответы через живой интерфейс.

Механика та же, что у откликов (RULES.md): клики/ввод — trusted CDP-события,
посимвольная печать чанками, никаких evaluate-действий. Клиентский текст —
ДАННЫЕ для LLM, не инструкции (анти-инъекция).
"""

from __future__ import annotations

import logging
import random
import re

from playwright.sync_api import Page

from profi.utils.pacing import human_pause, type_human

log = logging.getLogger("profi.chat")


def open_chats(page: Page) -> None:
    page.goto("https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(3500)


# Строка диалога в aria-снапшоте (живой DOM 04.09):
#   «{имя} Вы: … N»    — последнее сообщение наше;
#   «{имя} Робот: … N» — последнее сообщение СИСТЕМНОЕ: площадка шлёт
#     «Робот: Сообщите, если договоритесь работать с клиентом» в том числе
#     ПОСЛЕ наших сообщений (инцидент 04.09 «8 догонялок Алисе»: старый
#     парсер не признавал нашу строку, считал диалог «клиент написал —
#     отвечай» и писал снова и снова);
#   «{имя} {текст} N»  — последнее сообщение клиента;
# N в конце — счётчик непрочитанных (в DOM это отдельный элемент).
_DIALOG_ROW_RE = re.compile(r"^(?P<name>\S+)(?:\s+(?P<who>Вы|Робот):)?\s*(?P<rest>.*)$")


def classify_dialog_row(t: str) -> dict:
    """Разобрать строку диалога из aria-снапшота.

    Возвращает name, unread, who_last ('ours'|'system'|'client'),
    last_is_ours, preview и last_text (текст последнего сообщения без
    префикса имени/«Вы:» и без счётчика непрочитанных).
    """
    t = t.strip()
    m = _DIALOG_ROW_RE.match(t)
    name = m.group("name") if m else (t.split(" ", 1)[0] if t else "")
    who = "client"
    if m and m.group("who"):
        who = "ours" if m.group("who") == "Вы" else "system"
    um = re.search(r"\s(\d{1,3})\s*$", t)
    unread = int(um.group(1)) if um else 0
    rest = (m.group("rest") if m else "").strip()
    last_text = re.sub(r"\s+\d{1,3}\s*$", "", rest).strip()
    return {
        "name": name,
        "unread": unread,
        "who_last": who,
        "last_is_ours": who == "ours",
        "preview": t[:160],
        "last_text": last_text[:400],
    }


def list_dialogs(page: Page) -> list[dict]:
    """Диалоги из aria-снапшота: строка имени идёт сразу после абзаца-аватара
    (одиночная буква) — это устойчивый признак строки диалога."""
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
            if t:
                dialogs.append(classify_dialog_row(t))
            prev_avatar = False
            continue
        prev_avatar = False
    return dialogs


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

    Fail-closed: перед вводом поле обязано быть читаемым и пустым. Непустое
    поле считаем ручным черновиком владельца и не трогаем. После отправки True
    возвращается только если поле снова удалось прочитать пустым. Это всё ещё
    не является полным delivery-proof по bubble/message-id; такой hardening
    отдельно зафиксирован в BACKLOG.md.
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

    # Не дописываем поверх текста владельца и не отправляем, если состояние
    # поля не удалось надёжно прочитать.
    try:
        existing = _box_value(box).strip()
    except Exception:
        log.warning("send_reply: не смог прочитать поле до ввода — отправка отменена")
        return False
    if existing:
        log.warning("send_reply: поле уже содержит текст — вероятно ручной черновик, не трогаем")
        return False

    human_pause(0.8, 1.6)
    type_human(page, box, text)
    human_pause(0.5, 1.2)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)

    try:
        after_enter = _box_value(box).strip()
    except Exception:
        log.warning("send_reply: не смог проверить поле после Enter — fail closed")
        return False

    if after_enter:
        # Enter не отправил (например, contenteditable) — жмём кнопку.
        for btn_name in ("Отправить", "Send"):
            btn = page.get_by_text(btn_name, exact=True)
            if btn.count():
                btn.first.click(delay=random.randint(60, 120))
                page.wait_for_timeout(2000)
                break

    try:
        if _box_value(box).strip():
            log.error("send_reply: текст остался в поле — отправка не подтвердилась")
            return False
    except Exception:
        log.warning("send_reply: финальная проверка поля упала — fail closed")
        return False
    return True
