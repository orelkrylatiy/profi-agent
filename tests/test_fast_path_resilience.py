from __future__ import annotations

from datetime import datetime

import pytest

from profi import config
from profi.fastpath import commission_paused, mark_commission_exhausted, process_open_candidate
from profi.integration import respond as respond_mod
from profi.utils.workhours import business_timezone, in_work_hours


class _Store:
    def __init__(self):
        self.send_status = "not_sent"
        self.calls = []

    def sends_today(self):
        return 0

    def assign_prompt_variant(self, order_id, experiment_id, variants):
        self.calls.append(("prompt", experiment_id, "A"))
        return "A"

    def set_draft(self, order_id, status, text=None, source=None, error=None):
        self.calls.append(("draft", status, text, source, error))
        return True

    def set_send_status(self, order_id, status):
        self.send_status = status
        self.calls.append(("send", status))
        return True

    def set_note(self, order_id, note):
        self.calls.append(("note", note))
        return True

    def claim_send(self, order_id):
        if self.send_status != "not_sent":
            return False
        self.send_status = "sending"
        self.calls.append(("claim", order_id))
        return True

    def record_response(self, order_id, mode, paid_rub):
        self.calls.append(("response", mode, paid_rub))


def _details():
    return {
        "id": "93790001",
        "bid_price": 200,
        "competition_position": 2,
        "has_bid": False,
        "card_tags": [],
    }


def _configure_pay(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
    monkeypatch.setattr(fastpath.config, "MAX_RESPONSE_PRICE_RUB", 500)


def test_ambiguous_missing_respond_ui_is_technical_failed(monkeypatch):
    import profi.fastpath as fastpath

    _configure_pay(monkeypatch)
    store = _Store()
    monkeypatch.setattr(
        fastpath.respond_mod,
        "_open_respond_form_inner",
        lambda *args: (_ for _ in ()).throw(
            respond_mod.RespondError("нет ни блока тарифов, ни CTA «Написать клиенту»")
        ),
    )
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *args, **kwargs: pytest.fail("decision must not run after broken respond UI"),
    )

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93790001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "failed"
    assert store.send_status == "failed"
    assert any(call[0] == "draft" and call[1] == "error" for call in store.calls)


def test_confirmed_hidden_order_is_skipped_and_draft_is_terminal(monkeypatch):
    import profi.fastpath as fastpath

    _configure_pay(monkeypatch)
    store = _Store()
    monkeypatch.setattr(
        fastpath.respond_mod,
        "_open_respond_form_inner",
        lambda *args: (_ for _ in ()).throw(
            respond_mod.OrderHiddenError("заказ скрыт (маркер 'клиент отменил заказ')")
        ),
    )

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93790001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "skipped"
    assert store.send_status == "skipped"
    assert any(call[0] == "draft" and call[1] == "skipped" for call in store.calls)


def test_llm_cooldown_fallback_reaches_real_send_path(monkeypatch):
    import profi.fastpath as fastpath

    _configure_pay(monkeypatch)
    store = _Store()
    fallback = (
        "Здравствуйте! Могу помочь с задачей. Предлагаю начать с пробного занятия, "
        "определить текущий уровень и дальше составить понятный план работы. Когда вам удобно?"
    )
    monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
    monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", [fallback])
    monkeypatch.setattr(
        fastpath.llm_mod,
        "chat",
        lambda *args, **kwargs: pytest.fail("LLM must not be called during cooldown"),
    )
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda page, mode: page)
    monkeypatch.setattr(
        fastpath.respond_mod,
        "fill_form",
        lambda page, rate, text, mode: {"to_pay": 200, "send_button_found": True},
    )
    monkeypatch.setattr(
        fastpath.respond_mod,
        "click_send",
        lambda page, ctx, rate=None: {
            "url_after": "https://profi.ru/backoffice/r.php?id=93790001"
        },
    )
    monkeypatch.setattr(fastpath.respond_mod, "send_failed", lambda outcome: False)

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93790001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
        llm_blocked=True,
    )

    assert result == "sent"
    assert store.send_status == "sent"
    assert any(
        call[0] == "draft" and call[1] == "generated" and call[3] == "fallback"
        for call in store.calls
    )
    assert ("response", "pay", 200) in store.calls


def test_early_commission_skip_finalizes_draft(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "commission")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
    store = _Store()
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda page, mode: page)
    monkeypatch.setattr(fastpath.respond_mod, "read_footer", lambda page: {"to_pay": 150})
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *args, **kwargs: pytest.fail("LLM must not run after commission mismatch"),
    )

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93790001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "skipped"
    assert any(call[0] == "draft" and call[1] == "skipped" for call in store.calls)


def test_overnight_work_hours_cover_midnight_but_stop_at_one(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE_NAME", "Asia/Yekaterinburg")
    monkeypatch.setattr(config, "WORK_HOURS", (8, 25))

    assert in_work_hours(datetime(2026, 9, 10, 23, 59)) is True
    assert in_work_hours(datetime(2026, 9, 11, 0, 59)) is True
    assert in_work_hours(datetime(2026, 9, 11, 1, 0)) is False
    assert in_work_hours(datetime(2026, 9, 11, 7, 59)) is False
    assert in_work_hours(datetime(2026, 9, 11, 8, 0)) is True


def test_commission_pause_uses_business_date(tmp_path, monkeypatch):
    import profi.fastpath as fastpath

    marker = tmp_path / "commission-exhausted"
    monkeypatch.setattr(fastpath.config, "COMMISSION_EXHAUSTED_FILE", marker)
    tz = business_timezone()
    monkeypatch.setattr(
        fastpath,
        "business_now",
        lambda: datetime(2026, 9, 11, 0, 30, tzinfo=tz),
    )

    mark_commission_exhausted()
    assert marker.read_text(encoding="utf-8") == "2026-09-11"
    assert commission_paused() is True
