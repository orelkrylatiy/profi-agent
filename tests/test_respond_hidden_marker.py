from __future__ import annotations

from profi.integration import respond as respond_mod


class _FakeBody:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def inner_text(self, timeout=0):
        del timeout
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _FakePage:
    def __init__(self, values):
        self.body = _FakeBody(values)

    def locator(self, selector):
        assert selector == "body"
        return self.body


def test_hidden_marker_returns_immediately_when_present(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(["Заказ скрыт — на него нельзя откликнуться"])

    assert respond_mod.hidden_marker(page) == "заказ скрыт"
    assert page.body.calls == 1
    assert sleeps == []


def test_hidden_marker_retries_once_for_async_render(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(["Загрузка...", "Клиент отменил заказ"])

    assert respond_mod.hidden_marker(page) == "клиент отменил"
    assert page.body.calls == 2
    assert sleeps == [1.5]


def test_hidden_marker_retries_once_after_transient_read_error(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage([RuntimeError("DOM not ready"), "Заказ отменён"])

    assert respond_mod.hidden_marker(page) == "заказ отменён"
    assert page.body.calls == 2
    assert sleeps == [1.5]


def test_hidden_marker_stops_after_one_retry(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(["Живой заказ", "Всё ещё живой заказ"])

    assert respond_mod.hidden_marker(page) is None
    assert page.body.calls == 2
    assert sleeps == [1.5]
