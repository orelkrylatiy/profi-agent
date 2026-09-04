"""Fresh-order fast path: decide and respond while the order page is still open.

The worker owns the fresh order page. This module never opens an order itself, so
happy-path processing is one open -> one decision -> one send -> one close.
SQLite remains the durable state/idempotency layer; no background retry is needed
for candidates that reached this flow.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from profi import config
from profi import llm as llm_mod
from profi.integration import respond as respond_mod
from profi.utils import has_contacts


@dataclass(frozen=True)
class Decision:
    action: str  # send | skip | failed
    reason: str
    text: str | None = None
    source: str | None = None  # llm | fallback | rules


def _card_tags(details: dict) -> list[str]:
    tags = details.get("card_tags")
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    raw = ((details.get("raw_bo_order_screen") or {}).get("tags")) or []
    return [
        str(tag["text"]) for tag in raw if isinstance(tag, dict) and tag.get("text") is not None
    ]


def full_gate_reason(details: dict) -> str | None:
    """Terminal deterministic gates available from the full order card."""
    if any("ваканс" in tag.lower() for tag in _card_tags(details)):
        return "карточка помечена как возможная вакансия"

    try:
        bid_price = int(details.get("bid_price") or 0)
    except (TypeError, ValueError):
        bid_price = 0
    if config.MAX_RESPONSE_PRICE_RUB and bid_price > config.MAX_RESPONSE_PRICE_RUB:
        return f"цена отклика {bid_price} ₽ > {config.MAX_RESPONSE_PRICE_RUB} ₽"

    position = details.get("competition_position")
    if (
        config.MAX_COMPETITION_POSITION
        and position is not None
        and int(position) > config.MAX_COMPETITION_POSITION
    ):
        return f"позиция {position} > {config.MAX_COMPETITION_POSITION}"

    if details.get("has_bid"):
        return "уже есть отклик"
    return None


def normalize_reply_text(text: str) -> tuple[str | None, str | None]:
    """Apply the same safety/length contract to LLM and fallback text."""
    text = str(text or "").strip()
    if has_contacts(text):
        return None, "постчек нашёл контакты/ссылку в тексте"
    if len(text) > 500:
        cut = max(text.rfind(mark, 0, 500) for mark in ".!?")
        if cut >= 99:
            text = text[: cut + 1]
        else:
            return None, f"текст {len(text)} симв. без границы предложения до 500"
    if len(text) < 100:
        return None, "текст слишком короткий"
    return text, None


def choose_fallback(order_id: str, templates: Sequence[str]) -> str | None:
    """Stable per-order template choice: varied, deterministic, testable."""
    if not templates:
        return None
    digest = hashlib.sha256(str(order_id).encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(templates)
    return str(templates[index]).strip()


def _fallback_decision(order_id: str, reason: str) -> Decision:
    if not config.PROFILE_FALLBACK_ENABLED:
        return Decision("failed", reason, None, None)
    raw = choose_fallback(order_id, config.PROFILE_FALLBACK_TEMPLATES)
    if not raw:
        return Decision("failed", f"{reason}; fallback-профиль пуст", None, None)
    text, invalid = normalize_reply_text(raw)
    if invalid:
        return Decision("failed", f"{reason}; fallback отклонён: {invalid}", None, "fallback")
    return Decision("send", reason, text, "fallback")


def decide_reply(
    details: dict,
    order_id: str,
    *,
    system_prompt_factory: Callable[[], str],
    user_prompt: str,
    llm_blocked: bool = False,
    on_limit: Callable[[Exception], None] | None = None,
) -> Decision:
    """Rules -> LLM when available -> safe profile fallback on LLM failure.

    A semantic LLM `skip` is terminal and never replaced with a template. Fallback
    is only a resilience path when the model is unavailable/invalid, after all
    deterministic gates have already passed.
    """
    gate = full_gate_reason(details)
    if gate:
        return Decision("skip", gate, None, "rules")

    if llm_blocked:
        return _fallback_decision(order_id, "LLM недоступна: fallback")

    try:
        status = llm_mod.status()
    except Exception as exc:
        return _fallback_decision(order_id, f"LLM status error: {exc}")
    if not status.get("key_masked"):
        return _fallback_decision(order_id, "LLM-ключ не задан: fallback")

    try:
        chain = list(llm_mod.models_chain())
    except Exception as exc:
        return _fallback_decision(order_id, f"LLM models error: {exc}")
    if not chain:
        return _fallback_decision(order_id, "LLM models chain пуст: fallback")

    plan = [(chain[0], 3000), (chain[0], 4500)] + [(model, 4500) for model in chain[1:]]
    last_error: Exception | None = None
    for model, max_tokens in plan:
        try:
            raw = llm_mod.chat(
                system_prompt_factory(),
                user_prompt,
                temperature=0.4,
                max_tokens=max_tokens,
                model=model,
            )
            verdict = llm_mod.json_reply(raw)
        except Exception as exc:
            last_error = exc
            try:
                limited = llm_mod.is_limit_error(exc)
            except Exception:
                limited = False
            if limited:
                if on_limit is not None:
                    on_limit(exc)
                return _fallback_decision(order_id, "LLM на лимите: fallback")
            continue

        action = str(verdict.get("verdict") or "").strip().lower()
        reason = str(verdict.get("reason") or "")[:200]
        if action == "skip":
            return Decision("skip", reason or "LLM: skip", None, "llm")
        if action != "send":
            last_error = ValueError(f"неизвестный verdict {action!r}")
            continue

        text, invalid = normalize_reply_text(str(verdict.get("text") or ""))
        if invalid:
            return _fallback_decision(order_id, f"LLM-текст отклонён: {invalid}; fallback")
        return Decision("send", reason or "LLM: send", text, "llm")

    return _fallback_decision(order_id, f"LLM/JSON недоступна: {last_error}")


def _payment_due(mode: str, footer: dict) -> tuple[int | None, str]:
    to_pay = footer.get("to_pay")
    if mode == "commission":
        if to_pay:
            return None, f"режим комиссии, а к оплате {to_pay} ₽ — тариф выбран неверно"
        return 0, ""
    if to_pay is None:
        return None, "не смог прочитать «К оплате»"
    try:
        to_pay = int(to_pay)
    except (TypeError, ValueError):
        return None, "не смог распознать «К оплате»"
    if config.MAX_RESPONSE_PRICE_RUB and to_pay > config.MAX_RESPONSE_PRICE_RUB:
        return None, f"к оплате {to_pay} ₽ > потолка {config.MAX_RESPONSE_PRICE_RUB} ₽"
    return to_pay, ""


def _terminal(store, order_id: str, *, send_status: str, draft_status: str, note: str) -> str:
    store.set_draft(order_id, draft_status, error=note if draft_status == "error" else None)
    store.set_send_status(order_id, send_status)
    store.set_note(order_id, note)
    return send_status


def mark_terminal_open_failure(store, order_id: str, exc: Exception) -> None:
    """No background reopen: an exhausted open attempt is terminal."""
    note = f"технический сбой открытия, без повтора: {str(exc)[:180]}"
    _terminal(store, order_id, send_status="failed", draft_status="error", note=note)


def process_open_candidate(
    order_page,
    ctx,
    store,
    order_id: str,
    details: dict,
    *,
    system_prompt_factory: Callable[[], str],
    user_prompt: str,
    llm_blocked: bool = False,
    on_limit: Callable[[Exception], None] | None = None,
) -> str:
    """Finish a fresh candidate using the already-open order page.

    The page lifecycle belongs to the caller and is never closed here. Every
    normal outcome is terminal for this candidate: sent/unknown/skipped/failed.
    """
    if config.DAILY_SEND_LIMIT and store.sends_today() >= config.DAILY_SEND_LIMIT:
        return _terminal(
            store,
            order_id,
            send_status="skipped",
            draft_status="skipped",
            note="скип: дневной лимит отправок исчерпан",
        )

    decision = decide_reply(
        details,
        order_id,
        system_prompt_factory=system_prompt_factory,
        user_prompt=user_prompt,
        llm_blocked=llm_blocked,
        on_limit=on_limit,
    )
    if decision.action == "skip":
        store.set_draft(order_id, "skipped", source=decision.source)
        store.set_send_status(order_id, "skipped")
        store.set_note(order_id, f"скип {decision.source or 'flow'}: {decision.reason}")
        return "skipped"
    if decision.action != "send" or not decision.text:
        return _terminal(
            store,
            order_id,
            send_status="failed",
            draft_status="error",
            note=f"fast-path: {decision.reason}",
        )

    store.set_draft(
        order_id,
        "generated",
        text=decision.text,
        source=decision.source,
    )
    if not store.claim_send(order_id):
        store.set_note(order_id, "fast-path: send уже захвачен/завершён другим процессом")
        return "already_processed"

    try:
        respond_mod._open_respond_form_inner(order_page, config.RESPOND_MODE)
        footer = respond_mod.fill_form(
            order_page,
            config.RATE,
            decision.text,
            mode=config.RESPOND_MODE,
        )
    except respond_mod.OrderHiddenError as exc:
        store.set_send_status(order_id, "skipped")
        store.set_note(order_id, f"скип: заказ скрыт — {str(exc)[:160]}")
        return "skipped"
    except Exception as exc:
        store.set_send_status(order_id, "failed")
        store.set_note(order_id, f"fast-path form failed: {str(exc)[:180]}")
        return "failed"

    due, why = _payment_due(config.RESPOND_MODE, footer)
    if due is None:
        store.set_send_status(order_id, "skipped")
        store.set_note(order_id, f"скип: {why}")
        return "skipped"

    # Recheck the account-wide daily gate immediately before the irreversible click.
    if config.DAILY_SEND_LIMIT and store.sends_today() >= config.DAILY_SEND_LIMIT:
        store.set_send_status(order_id, "skipped")
        store.set_note(order_id, "скип: дневной лимит достигнут перед отправкой")
        return "skipped"

    try:
        outcome = respond_mod.click_send(
            order_page,
            ctx,
            rate=None if config.RESPOND_MODE == "commission" else config.RATE,
        )
    except Exception as exc:
        # click_send уже начал необратимую операцию: при потере связи нельзя
        # утверждать, что отправки не было. unknown terminal предотвращает retry.
        store.set_send_status(order_id, "unknown")
        store.record_response(order_id, config.RESPOND_MODE, due)
        store.set_note(order_id, f"fast-path click outcome unknown: {str(exc)[:180]}")
        return "unknown"

    url_after = str(outcome.get("url_after") or "")
    if "r.php" in url_after and f"id={order_id}" in url_after:
        status = "sent"
    elif respond_mod.send_failed(outcome):
        status = "failed"
    else:
        status = "unknown"

    store.set_send_status(order_id, status)
    if status in {"sent", "unknown"}:
        store.record_response(order_id, config.RESPOND_MODE, due)
    store.set_note(
        order_id,
        f"{decision.reason} | source={decision.source} | send={status}",
    )
    return status
