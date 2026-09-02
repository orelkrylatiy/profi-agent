"""Человеческий темп действий (RULES.md §1): паузы и печать."""

from __future__ import annotations

import random
import time


def human_pause(lo: float = 0.6, hi: float = 1.8) -> None:
    """Человеческая пауза между действиями (RULES.md §1)."""
    time.sleep(random.uniform(lo, hi))
