"""Анти-инъекция: контакты/ссылки в текстах для клиента запрещены (RULES.md)."""

from __future__ import annotations

import re

_CONTACTS_RE = re.compile(
    r"https?://|www\.|[\w.\-]+@[\w.\-]+|\+?\d[\d\s\-()]{8,}|t\.me|telegram|whatsapp|телеграм",
    re.I,
)


def has_contacts(text: str) -> bool:
    """True, если в тексте есть ссылка/телефон/e-mail/мессенджер."""
    return bool(_CONTACTS_RE.search(text))
