from __future__ import annotations

from types import SimpleNamespace

import pytest

from profi import capability


def test_capability_state_persists_and_expires(tmp_path):
    path = tmp_path / "info.capability.json"
    state = capability.mark(
        capability.NO_BALANCE,
        "balance is below the response price",
        ttl_s=60,
        balance_rub=0,
        to_pay_rub=200,
        path=path,
        now=1_000,
    )
    assert state.is_blocked(now=1_059)
    assert not state.is_blocked(now=1_060)

    loaded = capability.load_state(path)
    assert loaded.status == capability.NO_BALANCE
    assert loaded.balance_rub == 0
    assert loaded.to_pay_rub == 200
    assert loaded.blocked_until == 1_060


def test_capability_classifier_does_not_guess_balance_from_unknown_ui():
    err = RuntimeError("нет ни блока тарифов, ни CTA «Написать клиенту»")
    assert capability.classify_form_error(err, "pay") == capability.UI_UNKNOWN


def test_capability_classifier_recognizes_specific_signals():
    no_money = RuntimeError("Недостаточно средств. Пополните баланс")
    assert capability.classify_form_error(no_money, "pay") == capability.NO_BALANCE

    no_commission = RuntimeError("в модалке тарифа нет опции «Комиссия» — доступен только платный отклик")
    assert (
        capability.classify_form_error(no_commission, "commission")
        == capability.COMMISSION_UNAVAILABLE
    )

    daily = RuntimeError("тариф «Комиссия» заблокирован: Подождите до завтра")
    assert capability.classify_form_error(daily, "commission") == capability.COMMISSION_DAILY_LIMIT


class _Store:
    def __init__(self):
        self.calls: list[tuple] = []
        self.send_status = "not_sent"

    def sends_today(self):
        return 0

    def assign_prompt_variant(self, order_id, experiment_id, variants):
        self.calls.append(("prompt", order_id))
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
        self.calls.append(("claim", order_id))
        self.send_status = "sending"
        return True

    def record_response(self, order_id, mode, paid_rub):
        self.calls.append(("response", mode, paid_rub))


def _details():
    return {
        "id": "94000001",
        "subject": "Информатика",
        "description": "Подготовка к ЕГЭ",
        "student": "Иван, 11 класс",
        "remote": "Да",
        "bid_price": 200,
        "competition_position": 2,
        "has_bid": False,
        "card_tags": [],
    }


@pytest.fixture
def isolated_capability(tmp_path, monkeypatch):
    path = tmp_path / "account.capability.json"
    monkeypatch.setattr(capability, "state_path", lambda db_path=None: path)
    return path


def test_pay_mode_no_balance_blocks_before_llm(monkeypatch, isolated_capability):
    import profi.fastpath as fastpath

    store = _Store()
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda p, mode: p)
    monkeypatch.setattr(
        fastpath.respond_mod,
        "read_footer",
        lambda p: {"to_pay": 200, "balance_seen": 0},
    )
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: pytest.fail("LLM must not run when balance is insufficient"),
    )

    result = fastpath.process_open_candidate(
        object(),
        object(),
        store,
        "94000001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "skipped"
    state = capability.load_state(isolated_capability)
    assert state.status == capability.NO_BALANCE
    assert state.balance_rub == 0
    assert state.to_pay_rub == 200
    assert not any(call[0] == "prompt" for call in store.calls) is False


def test_active_capability_block_skips_response_ui_and_llm(monkeypatch, isolated_capability):
    import profi.fastpath as fastpath

    capability.mark(
        capability.NO_BALANCE,
        "balance is below the response price",
        ttl_s=3_600,
        path=isolated_capability,
    )
    store = _Store()
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
    monkeypatch.setattr(
        fastpath.respond_mod,
        "_open_respond_form_inner",
        lambda *a, **k: pytest.fail("response UI must not be opened during capability cooldown"),
    )
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: pytest.fail("LLM must not run during capability cooldown"),
    )

    result = fastpath.process_open_candidate(
        object(),
        object(),
        store,
        "94000001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )
    assert result == "skipped"
    assert not any(call[0] == "prompt" for call in store.calls)


def test_unknown_response_ui_sets_short_account_cooldown(monkeypatch, isolated_capability):
    import profi.fastpath as fastpath

    store = _Store()
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)

    def boom(page, mode):
        raise RuntimeError("нет ни блока тарифов, ни CTA «Написать клиенту»")

    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", boom)
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: pytest.fail("LLM must not run after unknown form failure"),
    )

    result = fastpath.process_open_candidate(
        object(),
        object(),
        store,
        "94000001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )
    assert result == "failed"
    assert capability.load_state(isolated_capability).status == capability.UI_UNKNOWN


def test_commission_paid_footer_marks_commission_unavailable(monkeypatch, isolated_capability):
    import profi.fastpath as fastpath

    store = _Store()
    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)
    monkeypatch.setattr(fastpath, "commission_paused", lambda: False)
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "commission")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda p, mode: p)
    monkeypatch.setattr(fastpath.respond_mod, "read_footer", lambda p: {"to_pay": 117})
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: pytest.fail("LLM must not run if commission did not apply"),
    )

    result = fastpath.process_open_candidate(
        SimpleNamespace(),
        object(),
        store,
        "94000001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )
    assert result == "skipped"
    state = capability.load_state(isolated_capability)
    assert state.status == capability.COMMISSION_UNAVAILABLE
    assert state.to_pay_rub == 117
