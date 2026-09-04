"""LLM layer: providers plus lightweight client-copy style middleware."""

from __future__ import annotations

import logging

from profi.copy_style import (
    CHAT_STYLE_OVERRIDE,
    OUTREACH_STYLE_OVERRIDE,
    client_copy_issues,
    style_retry_instruction,
    style_variation,
)
from profi.llm.client import (
    chat as _chat,
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


def chat(
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 900,
    model: str | None = None,
) -> str:
    """Call the provider and conditionally retry obviously templated client copy.

    Only the two client-facing prompts are touched. The retry is best-effort:
    provider errors or invalid retry JSON fall back to the first valid response,
    so copy polish can never turn a usable lead into a technical failure.
    """

    channel = _copy_channel(system)
    if channel is None:
        return _chat(system, user, temperature, max_tokens, model)

    override = OUTREACH_STYLE_OVERRIDE if channel == "outreach" else CHAT_STYLE_OVERRIDE
    # main.py still carries the older cosmetic _style_variation(). Appending
    # the structural variant here makes the last instruction about message
    # shape, not about random punctuation.
    styled_system = system + override + style_variation(channel)
    first = _chat(styled_system, user, temperature, max_tokens, model)

    first_text = _copy_text(first, channel)
    if not first_text:
        return first
    first_issues = client_copy_issues(first_text, channel=channel)
    if not first_issues:
        return first

    log.info("client-copy style retry: channel=%s issues=%s", channel, first_issues)
    try:
        second = _chat(
            styled_system + style_retry_instruction(first_issues),
            user,
            temperature,
            max_tokens,
            model,
        )
    except Exception:
        return first

    second_text = _copy_text(second, channel)
    if not second_text:
        return first
    second_issues = client_copy_issues(second_text, channel=channel)

    # Never replace a valid first response with a retry that is equally or more
    # template-like. This is a style improvement layer, not a business gate.
    if len(second_issues) < len(first_issues):
        return second
    return first


__all__ = ["chat", "is_limit_error", "json_reply", "models_chain", "set_model", "status"]
