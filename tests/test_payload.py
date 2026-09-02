"""Компактный слепок карточки для LLM (main._llm_order_payload)."""

from profi.main import _client_summary, _llm_order_payload


def make_order() -> dict:
    return {
        "id": "93395453",
        "subject": "Олимпиады по информатике",
        "description": "Python, C++",
        "student": "Тимур, 10 класс.",
        "wishes": "Подготовка к ВСОШ",
        "remote": "Москва (МСК+0)",
        "address": None,
        "client_block_dom": {
            "name": "Ольга",
            "profile_since": "2009",
            "phone_verified": True,
            "reviews": 10,
        },
        "bid_price": "256",
        "has_bid": False,
        "competition_position": 26,
        # мусор, который раньше съедал лимит промпта:
        "price_hash": "TUM2RVd2eTV4SWp5a3VkcDgyN3pVUWVoSk5p…" * 100,
        "form_elements": [{"type": "INPUT", "name": "stavka"}],
        "raw_bo_order_screen": {"analyticsData": "…" * 5000},
    }


def test_payload_contains_key_fields():
    p = _llm_order_payload(make_order())
    d = json_loads(p)
    assert d["student"] == "Тимур, 10 класс."
    assert d["competition_position"] == 26
    assert d["client"] == "имя Ольга; на Профи с 2009; телефон подтверждён; отзывов: 10"


def test_payload_excludes_junk():
    p = _llm_order_payload(make_order())
    assert "price_hash" not in p
    assert "form_elements" not in p
    assert "raw_bo_order_screen" not in p
    assert len(p) < 1500  # было ~6000+, почти всё — price_hash


def test_payload_without_client_block():
    d = make_order()
    d.pop("client_block_dom")
    d2 = json_loads(_llm_order_payload(d))
    assert d2["client"] is None


def json_loads(s: str) -> dict:
    import json

    return json.loads(s)


class TestClientSummary:
    def test_empty(self):
        assert _client_summary(None) is None
        assert _client_summary({}) is None

    def test_partial(self):
        assert _client_summary({"reviews": 3}) == "отзывов: 3"


def test_send_failed_detector():
    from profi.integration.respond import send_failed

    assert send_failed({"page_text_tail": "Ставка\nПроизошла ошибка. Попробуйте снова"})
    assert not send_failed({"page_text_tail": "Отклик отправлен, всё хорошо"})
    assert not send_failed({})
