"""Парсинг JSON-вердикта LLM: llm.json_reply."""

import json

import pytest

from profi.llm import json_reply


def test_plain_json():
    assert json_reply('{"verdict": "send"}') == {"verdict": "send"}


def test_json_fence():
    raw = '```json\n{"verdict": "skip", "reason": "не тот предмет"}\n```'
    assert json_reply(raw) == {"verdict": "skip", "reason": "не тот предмет"}


def test_bare_fence():
    assert json_reply('```\n{"a": 1}\n```') == {"a": 1}


def test_surrounding_whitespace():
    assert json_reply('  \n{"a": 1}\n  ') == {"a": 1}


def test_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        json_reply("не JSON вообще")


def test_truncated_raises():
    # живой инцидент: думающая модель обрезала JSON по max_tokens
    with pytest.raises(json.JSONDecodeError):
        json_reply('{"verdict": "send", "text": "обрезан...')
