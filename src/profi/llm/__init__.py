"""LLM layer: providers plus lightweight client-copy style middleware."""

from __future__ import annotations

import json
import logging

from profi.copy_style import (
    CHAT_STYLE_OVERRIDE,
    OUTREACH_EXPERIMENT_MARKER,
    OUTREACH_STYLE_OVERRIDE,
    chat_retry_instruction,
    client_copy_issues,
    style_retry_instruction,
    style_variation,
)
from profi.llm.client import chat as _chat
from profi.llm.client import (
    is_limit_error,
    json_reply,
    models_chain,
    set_model,
    status,
)

log = logging.getLogger("profi.llm.copy")


def _copy_channel(system: str) -> str | None:
    if "ЦЕЛЬ отклика" in system:
        return "outreach"
    if "ЦЕЛЬ переписки" in system:
        return "chat"
    return None


def _copy_text(raw: str, channel: str) -> str | None:
    try:
        payload = json_reply(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    field = "text" if channel == "outreach" else "reply"
    value = payload.get(field)
    return str(value).strip() if value else None


def _chat_handoff_requested(raw: str) -> bool:
    try:
        payload = json_reply(raw)
    except Exception:
        return False
    return bool(isinstance(payload, dict) and payload.get("needs_human"))


def _disable_chat_handoff(raw: str) -> str:
    """Keep the legacy JSON field for compatibility but never hand a chat off."""
    try:
        payload = json_reply(raw)
    except Exception:
        return raw
    if not isinstance(payload, dict):
        return raw
    payload["needs_human"] = False
    return json.dumps(payload, ensure_ascii=False)


def chat(
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 900,
    model: str | None = None,
) -> str:
    """Call the provider and conditionally retry obviously templated client copy.

    Outreach A/B/C composition is assigned before this layer and must remain
    unchanged across retries. Chat keeps a little non-experimental variation.
    Chat handoff is temporarily disabled: the legacy ``needs_human`` field is
    forced to false so old runtime code cannot silently consume a client turn.
    The retry is best-effort: a style failure can never lose a usable lead.
    """
    channel = _copy_channel(system)
    if channel is None:
        return _chat(system, user, temperature, max_tokens, model)

    if channel == "outreach":
        # Experiment-aware callers already appended the exact versioned arm.
        # Non-experiment/manual callers still get the common final style rules.
        styled_system = (
            system if OUTREACH_EXPERIMENT_MARKER in system else system + OUTREACH_STYLE_OVERRIDE
        )
    else:
        styled_system = system + CHAT_STYLE_OVERRIDE + style_variation("chat")

    first = _chat(styled_system, user, temperature, max_tokens, model)
    first_text = _copy_text(first, channel)
    first_issues = client_copy_issues(first_text, channel=channel) if first_text else []
    if channel == "chat" and _chat_handoff_requested(first):
        first_issues.append("needs_human отключён — нужен обычный ответ")

    if not first_text and not first_issues:
        return first
    if not first_issues:
        return _disable_chat_handoff(first) if channel == "chat" else first

    log.info("client-copy style retry: channel=%s issues=%s", channel, first_issues)
    retry_hint = (
        style_retry_instruction(first_issues)
        if channel == "outreach"
        else chat_retry_instruction(first_issues)
    )
    try:
        second = _chat(
            styled_system + retry_hint,
            user,
            temperature,
            max_tokens,
            model,
        )
    except Exception:
        return _disable_chat_handoff(first) if channel == "chat" else first

    second_text = _copy_text(second, channel)
    second_issues = client_copy_issues(second_text, channel=channel) if second_text else []
    if channel == "chat" and _chat_handoff_requested(second):
        second_issues.append("needs_human отключён — нужен обычный ответ")

    if not second_text:
        return _disable_chat_handoff(first) if channel == "chat" else first

    # Never replace a valid first response with a retry that is equally or more
    # template-like. This is a style improvement layer, not a business gate.
    chosen = second if len(second_issues) < len(first_issues) else first
    return _disable_chat_handoff(chosen) if channel == "chat" else chosen


__all__ = ["chat", "is_limit_error", "json_reply", "models_chain", "set_model", "status"]
