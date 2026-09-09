"""Рабочие часы автономных контуров в явном business timezone.

Единый гейт для автопилота, воркера ленты и чатов: вне окна браузер
не трогаем вообще. Время бизнеса не должно зависеть от timezone ОС/VPS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from profi import config


def business_timezone() -> tzinfo:
    """Configured IANA timezone with offline Windows fallback for Yekaterinburg."""
    try:
        return ZoneInfo(config.TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        if config.TIMEZONE_NAME == "Asia/Yekaterinburg":
            return timezone(timedelta(hours=5), name="Asia/Yekaterinburg")
        raise


def business_now(now: datetime | None = None) -> datetime:
    """Return an aware datetime in the configured business timezone."""
    tz = business_timezone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        # Explicit naive values in tests/manual callers are business-local by contract.
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def in_work_hours(now: datetime | None = None) -> bool:
    """True внутри config.WORK_HOURS (часы business timezone, [lo, hi))."""
    lo, hi = config.WORK_HOURS
    return lo <= business_now(now).hour < hi
