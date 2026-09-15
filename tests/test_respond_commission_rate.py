"""commission-режим: в форме отклика не должно быть ставки.

Макс, 15.09: «надо убеждаться, что мы не отправляем в форме стоимость —
бывает, что она автоматически подставляется». Сайт автозаполнением может
вернуть прошлую цену — клиент увидит платный отклик вместо комиссионного.
Два гейта: самолечение в fill_form (ensure_no_commission_rate) и жёсткая
отмена в click_send перед кнопкой.
"""

from __future__ import annotations

import pytest

from profi.integration import respond as respond_mod
from profi.utils.pacing import clear_field


class _FakeInput:
    def __init__(self, value: str):
        self._value = value
        self.cleared = False

    def input_value(self, timeout=2_000):
        del timeout
        return "" if self.cleared else self._value

    def click(self, **kwargs):
        del kwargs
        if self.cleared:
            self._value = ""


class _FakeInputList:
    def __init__(self, inputs):
        self._inputs = inputs

    def all(self):
        return self._inputs


class _FakeWin:
    def __init__(self, *inputs):
        self.inputs = list(inputs)
        self.clear_calls = 0

    def locator(self, selector):
        assert selector == "input:visible"
        return _FakeInputList(self.inputs)

    def clear_non_empty(self):
        for el in self.inputs:
            if el.input_value().strip():
                el.cleared = True
                self.clear_calls += 1


class _FakeKeyboard:
    def __init__(self):
        self.presses: list[str] = []

    def press(self, key):
        self.presses.append(key)


class _FakePage:
    def __init__(self, win):
        self._win = win
        self.keyboard = _FakeKeyboard()

    def get_by_test_id(self, test_id):
        assert test_id == respond_mod.BID_WINDOW_TESTID
        return _TestIdTarget(self._win)


class _TestIdTarget:
    def __init__(self, win):
        self._win = win

    @property
    def first(self):
        return self._win


def _patch_sleep(monkeypatch):
    monkeypatch.setattr(respond_mod.time, "sleep", lambda s: None)
    sleeps = []
    monkeypatch.setattr(
        "profi.utils.pacing.time.sleep", lambda s: sleeps.append(s), raising=True
    )
    return sleeps


def test_clear_field_selects_all_and_backspaces(monkeypatch):
    sleeps = _patch_sleep(monkeypatch)
    page = _FakePage(_FakeWin())
    inp = _FakeInput("2000")
    clicks = []
    monkeypatch.setattr(
        inp, "click", lambda **k: clicks.append(k) or inp.__setattr__("cleared", True)
    )

    clear_field(page, inp)

    assert any(k.get("click_count") == 3 for k in clicks)
    assert page.keyboard.presses[-1] == "Backspace"
    assert "Control+a" in page.keyboard.presses
    assert sleeps  # человеческие паузы между нажатиями были


def test_ensure_no_commission_rate_clean_when_all_inputs_empty(monkeypatch):
    _patch_sleep(monkeypatch)
    win = _FakeWin(_FakeInput(""), _FakeInput(""))
    page = _FakePage(win)

    assert respond_mod.ensure_no_commission_rate(page, win) is None
    assert win.clear_calls == 0  # чистить нечего


def test_ensure_no_commission_rate_heals_autofilled_rate(monkeypatch):
    sleeps = _patch_sleep(monkeypatch)
    prefilled = _FakeInput("2000")
    win = _FakeWin(prefilled, _FakeInput(""))
    page = _FakePage(win)
    monkeypatch.setattr(win, "clear_non_empty", win.clear_non_empty)
    # самолечение: clear_field должен снять подстановку
    monkeypatch.setattr(
        respond_mod,
        "clear_field",
        lambda page, el: setattr(el, "cleared", True) or win.__setattr__("clear_calls", 1),
    )

    leak = respond_mod.ensure_no_commission_rate(page, win)

    assert leak is None, "после очистки утечки быть не должно"
    assert win.clear_calls == 1
    assert sleeps == []


def test_ensure_no_commission_rate_reports_persistent_leak(monkeypatch):
    _patch_sleep(monkeypatch)
    prefilled = _FakeInput("2000")  # очистка не помогает: cleared не меняет значение
    win = _FakeWin(prefilled)
    page = _FakePage(win)
    monkeypatch.setattr(respond_mod, "clear_field", lambda page, el: None)

    leak = respond_mod.ensure_no_commission_rate(page, win)

    assert leak == "2000"


def test_fill_form_commission_aborts_on_persistent_rate(monkeypatch):
    _patch_sleep(monkeypatch)
    prefilled = _FakeInput("2000")
    win = _FakeWin(prefilled)
    page = _FakePage(win)

    class _Area:
        first = None

        def __init__(self):
            _Area.first = self

        def wait_for(self, **k):
            del k

        def count(self):
            return 1

    monkeypatch.setattr(
        win,
        "locator",
        lambda sel: _Area() if sel == "textarea" else _FakeInputList(win.inputs),
    )
    page.wait_for_timeout = lambda ms: None
    monkeypatch.setattr(respond_mod, "type_human", lambda *a, **k: None)
    monkeypatch.setattr(respond_mod, "clear_field", lambda page, el: None)
    monkeypatch.setattr(respond_mod, "read_footer", lambda p: {"to_pay": None})

    with pytest.raises(respond_mod.RespondError, match="подставленная ставка"):
        respond_mod.fill_form(page, 2000, "Т" * 150, mode="commission")


class _Btn:
    def __init__(self, on_click=None):
        self._on_click = on_click
        self.clicks = 0

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self, **k):
        self.clicks += 1
        if self._on_click:
            self._on_click(**k)


def test_click_send_commission_aborts_before_click_on_leaked_rate(monkeypatch):
    sleeps = _patch_sleep(monkeypatch)
    win = _FakeWin(_FakeInput("2000"))
    page = _FakePage(win)
    ctx = type("_Ctx", (), {})()
    ctx.on = lambda *a, **k: None
    btn = _Btn(on_click=lambda **k: (_ for _ in ()).throw(AssertionError("кнопку жать нельзя")))
    monkeypatch.setattr(
        page,
        "get_by_test_id",
        lambda test_id: btn
        if test_id == respond_mod.PAY_BUTTON_TESTID
        else _TestIdTarget(win),
    )
    monkeypatch.setattr(respond_mod, "human_pause", lambda *a, **k: None)

    with pytest.raises(respond_mod.RespondError, match="commission"):
        respond_mod.click_send(page, ctx, rate=None)
    assert btn.clicks == 0, "клик не должен случиться"
    assert sleeps == []


def test_click_send_pay_mode_keeps_expected_rate_gate(monkeypatch):
    """regression: pay-гейт не сломан — правильная ставка проходит к клику."""
    _patch_sleep(monkeypatch)
    win = _FakeWin(_FakeInput("2000"))
    ctx = type("_Ctx", (), {})()
    ctx.on = lambda *a, **k: None

    btn = _Btn()
    monkeypatch.setattr(respond_mod, "human_pause", lambda *a, **k: None)

    class _PageWithBtn(_FakePage):
        def get_by_test_id(self, test_id):
            if test_id == respond_mod.PAY_BUTTON_TESTID:
                return btn
            return super().get_by_test_id(test_id)

    fpage = _PageWithBtn(win)
    fpage.wait_for_timeout = lambda ms: None
    fpage.url = "https://profi.ru/ok"
    fpage.get_by_text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("нет модалки"))

    outcome = respond_mod.click_send(fpage, ctx, rate=2000)
    assert btn.clicks == 1, "pay-режим: кнопка должна быть нажата"
    assert outcome["url_after"] == "https://profi.ru/ok"
