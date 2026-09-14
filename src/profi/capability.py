"""Persisted read-only account capability state for the response fast-path.

The worker should keep monitoring the feed even when an account cannot currently
respond. This module stores a tiny per-account state file next to the SQLite DB
so a restart does not immediately hammer the same broken response UI again.

A capability state is deliberately evidence-based:
- explicit money/tariff signals can block the response path for a bounded time;
- unknown UI is reported as UI_UNKNOWN, never guessed to be "no balance";
- order-specific unavailability is not an account capability failure.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from profi import config
from profi.utils.workhours import business_now

UNKNOWN = "UNKNOWN"
READY = "READY"
NO_BALANCE = "NO_BALANCE"
COMMISSION_UNAVAILABLE = "COMMISSION_UNAVAILABLE"
COMMISSION_DAILY_LIMIT = "COMMISSION_DAILY_LIMIT"
AUTH_REQUIRED = "AUTH_REQUIRED"
UI_UNKNOWN = "UI_UNKNOWN"

BLOCKING_STATUSES = {
    NO_BALANCE,
    COMMISSION_UNAVAILABLE,
    COMMISSION_DAILY_LIMIT,
    UI_UNKNOWN,
}


def _env_minutes(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def standard_recheck_seconds() -> int:
    return _env_minutes("PROFI_CAPABILITY_RECHECK_MIN", 30) * 60


def ui_unknown_recheck_seconds() -> int:
    return _env_minutes("PROFI_CAPABILITY_UI_UNKNOWN_RECHECK_MIN", 10) * 60


def state_path(db_path: Path | str | None = None) -> Path:
    db = Path(db_path or config.DB_PATH)
    return db.with_suffix(".capability.json")


@dataclass(frozen=True)
class CapabilityState:
    status: str = UNKNOWN
    reason: str = "not checked yet"
    checked_at: int = 0
    blocked_until: int = 0
    respond_mode: str | None = None
    balance_rub: int | None = None
    to_pay_rub: int | None = None

    def is_blocked(self, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        return self.status in BLOCKING_STATUSES and self.blocked_until > current

    def probe_due(self, now: int | None = None) -> bool:
        return not self.is_blocked(now)

    def public_dict(self) -> dict:
        return asdict(self)


def load_state(path: Path | None = None) -> CapabilityState:
    target = path or state_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("capability state is not an object")
        return CapabilityState(
            status=str(raw.get("status") or UNKNOWN),
            reason=str(raw.get("reason") or ""),
            checked_at=int(raw.get("checked_at") or 0),
            blocked_until=int(raw.get("blocked_until") or 0),
            respond_mode=str(raw["respond_mode"]) if raw.get("respond_mode") else None,
            balance_rub=_optional_int(raw.get("balance_rub")),
            to_pay_rub=_optional_int(raw.get("to_pay_rub")),
        )
    except (OSError, ValueError, TypeError):
        return CapabilityState()


def save_state(state: CapabilityState, path: Path | None = None) -> CapabilityState:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state.public_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    return state


def mark(
    status: str,
    reason: str,
    *,
    ttl_s: int | None = None,
    blocked_until: int | None = None,
    balance_rub: int | None = None,
    to_pay_rub: int | None = None,
    respond_mode: str | None = None,
    path: Path | None = None,
    now: int | None = None,
) -> CapabilityState:
    checked_at = int(time.time()) if now is None else int(now)
    if status == READY:
        until = 0
    elif blocked_until is not None:
        until = int(blocked_until)
    else:
        until = checked_at + int(ttl_s or standard_recheck_seconds())
    state = CapabilityState(
        status=status,
        reason=" ".join(str(reason).split())[:240],
        checked_at=checked_at,
        blocked_until=until,
        respond_mode=respond_mode or config.RESPOND_MODE,
        balance_rub=_optional_int(balance_rub),
        to_pay_rub=_optional_int(to_pay_rub),
    )
    return save_state(state, path)


def mark_ready(
    reason: str = "response form available",
    *,
    balance_rub: int | None = None,
    to_pay_rub: int | None = None,
    path: Path | None = None,
) -> CapabilityState:
    return mark(
        READY,
        reason,
        balance_rub=balance_rub,
        to_pay_rub=to_pay_rub,
        path=path,
    )


def mark_ui_unknown(
    reason: str = "response UI is not recognized", *, path: Path | None = None
) -> CapabilityState:
    return mark(UI_UNKNOWN, reason, ttl_s=ui_unknown_recheck_seconds(), path=path)


def mark_commission_daily_limit(reason: str, *, path: Path | None = None) -> CapabilityState:
    now = business_now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return mark(
        COMMISSION_DAILY_LIMIT,
        reason,
        blocked_until=int(tomorrow.timestamp()),
        path=path,
    )


def classify_form_error(exc: Exception, mode: str) -> str | None:
    """Map response-form evidence to an account capability status.

    ``None`` means the failure is order-specific and must not poison account
    state. The historical ``CommissionExhaustedError`` is overloaded by the
    integration layer: explicit "commission unavailable" wording wins, while
    other instances of that exception retain the legacy daily-limit meaning.
    Ambiguous DOM failures become UI_UNKNOWN rather than guessed NO_BALANCE.
    """
    name = type(exc).__name__
    text = " ".join(str(exc).lower().split())

    if name == "OrderHiddenError":
        return None

    balance_markers = (
        "недостаточно средств",
        "недостаточно денег",
        "пополните баланс",
        "пополнить баланс",
        "не хватает средств",
    )
    if any(marker in text for marker in balance_markers):
        return NO_BALANCE

    commission_unavailable_markers = (
        "нет опции «комиссия»",
        "опция «комиссия» в модалке не найдена",
        "тариф «комиссия» недоступен",
        "доступен только платный отклик",
        "комиссия не применилась",
    )
    if mode == "commission" and any(marker in text for marker in commission_unavailable_markers):
        return COMMISSION_UNAVAILABLE

    daily_limit_markers = (
        "подождите до завтра",
        "дневной лимит",
        "не больше 20 раз в день",
        "лимит profi исчерпан",
    )
    if mode == "commission" and (
        any(marker in text for marker in daily_limit_markers)
        or name == "CommissionExhaustedError"
    ):
        return COMMISSION_DAILY_LIMIT

    # Generic RespondError means Profi rendered a response surface we no
    # longer recognize. Arbitrary RuntimeError/Playwright/network failures are
    # technical per-order failures and must not freeze every account candidate.
    if name == "RespondError":
        return UI_UNKNOWN
    return None


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
