from __future__ import annotations

import pytest

from profi.fastpath import Decision, process_open_candidate


class _Store:
    def __init__(self):
        self.status = "not_sent"
        self.calls = []

    def sends_today(self):
        return 0

    def assign_prompt_variant(self, order_id, experiment_id, variants):
        self.calls.append(("prompt", experiment_id, "A"))
        return "A"

    def set_draft(self, order_id, status, text=None, source=None, error=None):
        self.calls.append(("draft", status))
        return True

    def claim_send(self, order_id):
        if self.status != "not_sent":
            return False
        self.status = "sending"
        return True

    def set_send_status(self, order_id, status):
        self.status = status
        self.calls.append(("send", status))
        return True

    def set_note(self, order_id, note):
        self.calls.append(("note", note))
        return True

    def record_response(self, order_id, mode, paid_rub):
        self.calls.append(("response", mode, paid_rub))


def _details():
    return {
        "id": "93400001",
        "bid_price": 200,
        "competition_position": 2,
        "has_bid": False,
        "card_tags": [],
    }


def test_outside_work_hours_skips_before_llm(monkeypatch):
    import profi.fastpath as fastpath

    store = _Store()
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: False)
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: pytest.fail("LLM/decision must not run outside work hours"),
    )

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93400001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "skipped"
    assert store.status == "skipped"
    assert not any(call[0] == "prompt" for call in store.calls)


def test_work_hours_rechecked_immediately_before_click(monkeypatch):
    import profi.fastpath as fastpath

    store = _Store()
    checks = iter([True, False])
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: next(checks))
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: Decision("send", "подходит", "Т" * 150, "llm"),
    )
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda page, mode: page)
    monkeypatch.setattr(fastpath.respond_mod, "fill_form", lambda *a, **k: {"to_pay": 200})
    monkeypatch.setattr(
        fastpath.respond_mod,
        "click_send",
        lambda *a, **k: pytest.fail("click must not happen after work-hours boundary"),
    )
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93400001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "skipped"
    assert store.status == "skipped"
    assert ("prompt", "outreach_offer_v1", "A") in store.calls
    assert not any(call[0] == "response" for call in store.calls)
