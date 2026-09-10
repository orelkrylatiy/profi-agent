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


def test_live_order_has_no_retry_latency_by_default(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(["Живой заказ"])

    assert respond_mod.hidden_marker(page) is None
    assert page.body.calls == 1
    assert sleeps == []


def test_hidden_marker_retries_once_only_when_requested(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(["Загрузка...", "Клиент отменил заказ"])

    assert respond_mod.hidden_marker(page, retry=True) == "клиент отменил заказ"
    assert page.body.calls == 2
    assert sleeps == [1.5]


def test_hidden_marker_retries_after_transient_read_error(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage([RuntimeError("DOM not ready"), "Заказ отменён"])

    assert respond_mod.hidden_marker(page, retry=True) == "заказ отменён"
    assert page.body.calls == 2
    assert sleeps == [1.5]


def test_generic_client_wording_is_not_unavailable(monkeypatch):
    sleeps = []
    monkeypatch.setattr(respond_mod.time, "sleep", sleeps.append)
    page = _FakePage(
        [
            "Клиент не готов получать домашние задания между уроками",
            "Клиент не готов получать домашние задания между уроками",
        ]
    )

    assert respond_mod.hidden_marker(page, retry=True) is None
    assert page.body.calls == 2
    assert sleeps == [1.5]
