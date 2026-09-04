from __future__ import annotations

import json

import profi.llm as llm
from profi.copy_style import (
    CHAT_STYLE_OVERRIDE,
    OUTREACH_EXPERIMENT_ID,
    OUTREACH_EXPERIMENT_MARKER,
    OUTREACH_STYLE_OVERRIDE,
    OUTREACH_VARIANT_IDS,
    client_copy_issues,
    outreach_variant_prompt,
    style_retry_instruction,
)


def _raw(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TestClientCopyIssues:
    def test_compact_direct_message_passes(self):
        text = (
            "Здравствуйте! Могу помочь с подготовкой. Предлагаю начать с пробного "
            "занятия и после него решить, на чём сделать упор. Когда вам удобнее?"
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
        assert any("переход к методике" in issue for issue in issues)
        assert any("формат" in issue for issue in issues)
        assert "больше одного вопроса" in issues

    def test_long_smooth_copy_gets_retry_signal(self):
        text = "Здравствуйте! " + (
            "Могу помочь и подробно объяснить, как будут проходить занятия. " * 7
        )
        assert any("слишком длинно" in issue for issue in client_copy_issues(text))

    def test_style_retry_preserves_experiment_arm(self):
        hint = style_retry_instruction(["слишком длинно", "больше одного вопроса"])
        assert "ТОТ ЖЕ экспериментальный вариант" in hint
        assert "ничего нового не придумывай" in hint.lower()
        assert "максимум один вопрос" in hint

    def test_all_three_versioned_prompts_exist(self):
        assert OUTREACH_VARIANT_IDS == ("A", "B", "C")
        for variant in OUTREACH_VARIANT_IDS:
            prompt = outreach_variant_prompt(variant)
            assert OUTREACH_STYLE_OVERRIDE in prompt
            assert OUTREACH_EXPERIMENT_ID in prompt
            assert f"VARIANT={variant}" in prompt
            assert OUTREACH_EXPERIMENT_MARKER in prompt

    def test_overrides_prefer_offer_over_deep_personalization(self):
        assert "конкретный оффер" in OUTREACH_STYLE_OVERRIDE.lower()
        assert "глубокая персонализация" in OUTREACH_STYLE_OVERRIDE.lower()
        assert "не добавляй нарочно опечатки" in OUTREACH_STYLE_OVERRIDE.lower()
        assert "последний прямой вопрос" in CHAT_STYLE_OVERRIDE


class TestClientCopyMiddleware:
    def test_outreach_experiment_arm_survives_style_retry(self, monkeypatch):
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
                "Здравствуйте! Могу помочь с подготовкой. Предлагаю начать с "
                "пробного занятия и после него решить, на чём сделать упор. "
                "Когда вам удобно?"
            ),
        )
        answers = iter([first, second])

        def fake_chat(system, user, temperature, max_tokens, model):
            calls.append(system)
            return next(answers)

        monkeypatch.setattr(llm, "_chat", fake_chat)
        system = "ЦЕЛЬ отклика — договориться на пробное занятие. " + outreach_variant_prompt("A")
        result = llm.chat(system, "order", temperature=0.4, max_tokens=3000, model="fake")

        assert result == second
        assert len(calls) == 2
        assert all("VARIANT=A" in call for call in calls)
        assert all(call.count(OUTREACH_EXPERIMENT_MARKER) == 1 for call in calls)

    def test_non_experiment_outreach_still_gets_common_override(self, monkeypatch):
        calls = []
        answer = _raw(
            verdict="send",
            reason="ok",
            text=(
                "Здравствуйте! Могу помочь с подготовкой. Предлагаю начать с "
                "пробного занятия. Когда вам удобно?"
            ),
        )

        def fake_chat(system, user, temperature, max_tokens, model):
            calls.append(system)
            return answer

        monkeypatch.setattr(llm, "_chat", fake_chat)
        llm.chat("ЦЕЛЬ отклика — договориться на пробное занятие. ", "order", model="fake")
        assert OUTREACH_STYLE_OVERRIDE in calls[0]

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
        system = "ЦЕЛЬ отклика — договориться на пробное занятие. " + outreach_variant_prompt("B")
        result = llm.chat(system, "order", model="fake")
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
