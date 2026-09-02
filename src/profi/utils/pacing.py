"""Человеческий темп действий (RULES.md §1): паузы и печать."""

from __future__ import annotations

import random
import time


def human_pause(lo: float = 0.6, hi: float = 1.8) -> None:
    """Человеческая пауза между действиями (RULES.md §1)."""
    time.sleep(random.uniform(lo, hi))


def type_human(page, locator, text: str, clear: bool = False) -> None:
    """Посимвольный ввод чанками по 3–9 символов, паузы 0.15–0.6 с (RULES §1).

    Общий для формы отклика и чатов (раньше дублировался). clear=True:
    тройной клик выделяет уже подставленное сайтом значение (инцидент
    #92799459: дефолтные 2000 + наши 2000 = «20002000»), печать поверх
    выделения его заменяет. На пустом поле безвредно.
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
