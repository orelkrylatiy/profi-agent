"""Анти-инъекция: контакты/ссылки в текстах для клиента запрещены (RULES.md)."""

from __future__ import annotations

import re

# Ссылки, e-mail, мессенджеры — как есть
_CONTACTS_RE = re.compile(
    r"https?://|www\.|[\w.\-]+@[\w.\-]+|t\.me|telegram|whatsapp|телеграм",
    re.I,
)

# Кандидат «телефона»: цифры с разделителями (пробел/-/скобки) между цифрами
_PHONE_RUN_RE = re.compile(r"\+?\d[\d\s\-()]*\d")

# Реальный телефон — ≥10 цифр в прогоне. Меньше (годы «2025-2026» = 8,
# цены «45 000» = 5) — обычный учебный текст, не контакт.
_PHONE_MIN_DIGITS = 10


def _looks_like_phone(candidate: str) -> bool:
    return sum(ch.isdigit() for ch in candidate) >= _PHONE_MIN_DIGITS


def has_contacts(text: str) -> bool:
    """True, если в тексте есть ссылка/телефон/e-mail/мессенджер."""
    if _CONTACTS_RE.search(text):
        return True
    return any(_looks_like_phone(m.group(0)) for m in _PHONE_RUN_RE.finditer(text))


# Цена: цифры рядом с валютой/единицей ставки. В тарифе commission цену
# клиенту в текстах не пишем (решение владельца 04.09).
_PRICE_RE = re.compile(
    r"\d[\d\s ]{0,6}\s*(?:₽|руб|тыс|/час|в час|за час|за урок|за занятие)"
    r"|(?:ставк\w*|цена|стоимость)\s*[:—-]?\s*\d",
    re.I,
)


def has_price(text: str) -> bool:
    """True, если в тексте упомянута цена/ставка."""
    return bool(_PRICE_RE.search(text))


def strip_price_sentences(text: str) -> tuple[str, int]:
    """Вырезать предложения с ценой. Возврат: (текст, число срезанных)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in parts if not _PRICE_RE.search(s)]
    return " ".join(kept), len(parts) - len(kept)
