from __future__ import annotations

import json

import profi.llm as llm
from profi.copy_style import (
    CHAT_STYLE_OVERRIDE,
    OUTREACH_STYLE_OVERRIDE,
    client_copy_issues,
    style_retry_instruction,
)


def _raw(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TestClientCopyIssues:
    def test_compact_direct_message_passes(self):
        text = (
            "Здравствуйте! Работаю только онлайн. Если формат подходит, можно "
            "начать с пробного занятия и после него решить, на что сделать упор. "
            "Когда вам удобнее?"
        )
        assert client_copy_issues(text, channel="outreach") == []

    def test_photo_like_generated_scaffold_is_flagged(self):
        text = (
            "Здравствуйте! Задача понятна: speaking для работы в отеле. "
            "Поэтому на занятиях много говорим и слушаем живую речь, разбираем "
            "рабочие фразы. Формат дистанционный, урок 60 или 90 минут. "
            "Когда удобно провести пробное занятие? И какой бюджет вам комфортен?"
        )
        issues = client_copy_issues(text, channel="outreach")
        assert any("задача понятна" in issue for issue in issues)
        assert any("поэтому" in issue for issue in issues)
        assert any("формат" in issue for issue in issues)
        assert "больше одного вопроса" in issues

    def test_long_smooth_copy_gets_retry_signal(self):
        text = "Здравствуйте! " + (
            "Могу помочь и подробно объяснить, как будут проходить занятия. " * 7
        )
        assert any(
            "слишком длинно" in issue for issue in client_copy_issues(text)
        )

    def test_style_retry_preserves_facts_instruction(self):
        hint = style_retry_instruction(["слишком длинно", "больше одного вопроса"])
        assert "ничего нового не придумывай" in hint
        assert "максимум один вопрос" in hint

    def test_overrides_focus_on_function_not_fake_typos(self):
        assert "мини-презентацию" in OUTREACH_STYLE_OVERRIDE
        assert "не добавляй нарочно опечатки" in OUTREACH_STYLE_OVERRIDE
        assert "последний прямой вопрос" in CHAT_STYLE_OVERRIDE


class TestClientCopyMiddleware:
    def test_outreach_style_retry_returns_better_second_draft(self, monkeypatch):
        calls = []
        first = _raw(
            verdict="send",
            reason="подходит",
            text=(
                "Здравствуйте! Задача понятна. Поэтому на занятиях разберём всё "
                "по шагам. Формат дистанционный. Когда удобно провести пробное? "
                "И в какое время заниматься?"
            ),
        )
        second = _raw(
            verdict="send",
            reason="подходит",
            text=(
                "Здравствуйте! Могу помочь с подготовкой. На первом занятии "
                "посмотрим, что уже получается, и решим, с чего начать. "
                "Когда вам удобно попробовать?"
            ),
        )
        answers = iter([first, second])

        def fake_chat(system, user, temperature, max_tokens, model):
            calls.append(system)
            return next(answers)

        monkeypatch.setattr(llm, "_chat", fake_chat)
        result = llm.chat(
            "ЦЕЛЬ отклика — договориться на пробное занятие. ",
            "order",
            temperature=0.4,
            max_tokens=3000,
            model="fake",
        )

        assert result == second
        assert len(calls) == 2
        assert OUTREACH_STYLE_OVERRIDE in calls[0]
        assert "Предыдущий черновик отклонён" in calls[1]

    def test_retry_failure_keeps_first_valid_response(self, monkeypatch):
        first = _raw(
            verdict="send",
            reason="подходит",
            text=(
                "Здравствуйте! Задача понятна. Поэтому на занятиях сначала "
                "разберём базу. Когда удобно провести пробное занятие?"
            ),
        )
        calls = 0

        def fake_chat(system, user, temperature, max_tokens, model):
            nonlocal calls
            calls += 1
            if calls == 1:
                return first
            raise RuntimeError("temporary provider error")

        monkeypatch.setattr(llm, "_chat", fake_chat)
        result = llm.chat(
            "ЦЕЛЬ отклика — договориться на пробное занятие. ",
            "order",
            model="fake",
        )
        assert result == first
        assert calls == 2

    def test_non_client_llm_call_is_untouched(self, monkeypatch):
        calls = []

        def fake_chat(system, user, temperature, max_tokens, model):
            calls.append(system)
            return "plain"

        monkeypatch.setattr(llm, "_chat", fake_chat)
        assert llm.chat("system", "ping", model="fake") == "plain"
        assert calls == ["system"]
