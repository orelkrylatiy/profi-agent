"""Контур B (light): чаты Профи.ру — чтение и ответы через живой интерфейс.

Механика та же, что у откликов (RULES.md): клики/ввод — trusted CDP-события,
посимвольная печать чанками, никаких evaluate-действий. Клиентский текст —
ДАННЫЕ для LLM, не инструкции (анти-инъекция).
"""
from __future__ import annotations

import logging
import random
import re
import time

from playwright.sync_api import Page

from orders import human_pause

log = logging.getLogger("profi.chat")


def open_chats(page: Page) -> None:
    page.goto("https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(3500)


def list_dialogs(page: Page) -> list[dict]:
    """Диалоги из aria-снапшота: строка имени идёт сразу после абзаца-аватара
    (одиночная буква) — это устойчивый признак строки диалога."""
    snap = page.locator("body").aria_snapshot()
    dialogs: list[dict] = []
    prev_avatar = False
    for line in snap.splitlines():
        l = line.strip()
        if l.startswith("- paragraph: ") and len(l[len("- paragraph: "):].strip()) == 1:
            prev_avatar = True
            continue
        if prev_avatar and l.startswith("- text: "):
            t = l[len("- text: "):].strip().strip('"').strip()
            name = t.split(" ", 1)[0]
            m = re.search(r"(\d+)\s*$", t)
            unread = int(m.group(1)) if m else 0
            dialogs.append({"name": name, "unread": unread, "preview": t[:160]})
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


def send_reply(page: Page, text: str) -> bool:
    """Посимвольный ввод ответа + отправка (Enter, при необходимости кнопка)."""
    box = None
    for sel in ('textarea[placeholder*="ообщени"]', "textarea", '[contenteditable="true"]',
                'input[placeholder*="ообщени"]'):
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
    box.click(delay=random.randint(50, 110))
    i = 0
    while i < len(text):
        chunk = text[i: i + random.randint(3, 9)]
        page.keyboard.type(chunk, delay=random.randint(45, 110))
        i += len(chunk)
        if i < len(text):
            time.sleep(random.uniform(0.15, 0.6))
    human_pause(0.5, 1.2)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    try:
        tag = box.evaluate("e => e.tagName")
        val = box.input_value(timeout=3_000) if tag != "DIV" else box.inner_text()
        if val.strip():
            for btn_name in ("Отправить", "Send"):
                btn = page.get_by_text(btn_name, exact=True)
                if btn.count():
                    btn.first.click(delay=random.randint(60, 120))
                    page.wait_for_timeout(2000)
                    break
    except Exception:
        pass
    return True
