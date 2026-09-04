from __future__ import annotations

import json
from pathlib import Path

import profi.llm as llm
from profi import copy_style
from profi.integration import chat as chat_mod
from profi.llm import client as llm_client


class _FakeBox:
    def __init__(self, values):
        self.values = list(values)
        self.index = 0

    def is_visible(self):
        return True

    def evaluate(self, _script):
        return "TEXTAREA"

    def input_value(self, timeout=3_000):
        del timeout
        if self.index < len(self.values):
            value = self.values[self.index]
            self.index += 1
        else:
            value = self.values[-1]
        if isinstance(value, Exception):
            raise value
        return value


class _FakeLocator:
    def __init__(self, box):
        self.box = box

    def count(self):
        return 1

    def nth(self, _index):
        return self.box


class _NoButton:
    @property
    def first(self):
        return self

    def count(self):
        return 0

    def click(self, **_kwargs):  # pragma: no cover - count() is zero
        raise AssertionError("button must not be clicked")


class _Keyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class _FakePage:
    def __init__(self, box):
        self.box = box
        self.keyboard = _Keyboard()

    def locator(self, _selector):
        return _FakeLocator(self.box)

    def get_by_text(self, _name, exact=True):
        del exact
        return _NoButton()

    def wait_for_timeout(self, _ms):
        return None


def test_chat_prompt_does_not_invent_schedule_and_disables_handoff():
    prompt = copy_style.CHAT_STYLE_OVERRIDE
    assert "НЕ ПРИДУМЫВАЙ свободные окна" in prompt
    assert "нет календаря преподавателя" in prompt
    assert "когда клиенту удобно" in prompt
    assert "needs_human=false" in prompt


def test_chat_retry_has_no_outreach_experiment_language():
    hint = copy_style.chat_retry_instruction(["слишком длинно"])
    assert "эксперимент" not in hint.lower()
    assert "конкретный оффер" not in hint.lower()
    assert "когда клиенту удобно" in hint
    assert "needs_human=false" in hint


def test_chat_middleware_retries_handoff_and_forces_false(monkeypatch):
    answers = iter(
        [
            json.dumps(
                {"reply": "", "needs_human": True, "note": "раньше передавали владельцу"},
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "reply": "Этот момент лучше уточнить отдельно. Когда вам удобно продолжить?",
                    "needs_human": False,
                    "note": "",
                },
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    def fake_chat(system, user, temperature, max_tokens, model):
        calls.append(system)
        return next(answers)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    raw = llm.chat("ЦЕЛЬ переписки — договориться на пробное занятие. ", "dialog", model="fake")
    payload = llm.json_reply(raw)

    assert len(calls) == 2
    assert payload["needs_human"] is False
    assert payload["reply"]
    assert "needs_human отключён" in calls[1]


def test_send_reply_refuses_existing_manual_draft(monkeypatch):
    page = _FakePage(_FakeBox(["Я уже начал писать ответ руками"]))
    typed = []
    monkeypatch.setattr(chat_mod, "human_pause", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_mod, "type_human", lambda _p, _b, text: typed.append(text))

    assert chat_mod.send_reply(page, "Автоматический ответ") is False
    assert typed == []
    assert page.keyboard.pressed == []


def test_send_reply_fails_closed_if_box_detaches_after_enter(monkeypatch):
    page = _FakePage(_FakeBox(["", RuntimeError("detached")]))
    typed = []
    monkeypatch.setattr(chat_mod, "human_pause", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_mod, "type_human", lambda _p, _b, text: typed.append(text))

    assert chat_mod.send_reply(page, "Нормальный ответ") is False
    assert typed == ["Нормальный ответ"]
    assert page.keyboard.pressed == ["Enter"]


def test_send_reply_accepts_readable_empty_box_after_enter(monkeypatch):
    page = _FakePage(_FakeBox(["", ""]))
    monkeypatch.setattr(chat_mod, "human_pause", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_mod, "type_human", lambda *_a, **_k: None)

    assert chat_mod.send_reply(page, "Нормальный ответ") is True
    assert page.keyboard.pressed == ["Enter"]


def test_send_reply_rejects_text_that_remains_after_enter(monkeypatch):
    page = _FakePage(_FakeBox(["", "не ушло", "не ушло"]))
    monkeypatch.setattr(chat_mod, "human_pause", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_mod, "type_human", lambda *_a, **_k: None)

    assert chat_mod.send_reply(page, "Нормальный ответ") is False


def test_openai_compatible_path_uses_requested_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_client, "provider", lambda: "glm")
    monkeypatch.setattr(llm_client, "_key", lambda _provider: ("key", "GLM_API_KEY"))
    monkeypatch.setattr(llm_client, "_fallback_key", lambda: (None, "GLM_API_KEY_2"))
    monkeypatch.setattr(llm_client, "_base", lambda _provider: "https://example.invalid")

    def fake_post(url, headers, payload):
        captured.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(llm_client, "_post", fake_post)
    result = llm_client._chat_openai_style("system", "user", 0.2, 123, "glm-test-model")

    assert result == "ok"
    assert captured["payload"]["model"] == "glm-test-model"


def test_legacy_chat_cron_restarts_chrome_only_for_dead_cdp():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "chat_cron.sh").read_text(encoding="utf-8")
    assert '"error": "cdp_dead"' in script
    assert "grep -q '\"ok\": false'" not in script
