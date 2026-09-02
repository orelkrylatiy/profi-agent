"""Адресат сообщения: родитель или сам ученик (main._recipient_hint)."""
from profi.main import _recipient_hint


def make_order(student=None, client=None) -> dict:
    d: dict = {}
    if student is not None:
        d["student"] = student
    if client is not None:
        d["client_block_dom"] = {"name": client}
    return d


class TestParent:
    def test_student_and_client_differ(self):
        hint = _recipient_hint(make_order("Артём, 11 класс", "Ольга"))
        assert "РОДИТЕЛЬ" in hint or "родитель" in hint
        assert "Артём" in hint
        assert "родителю" in hint  # вопросы — родителю, не школьнику

    def test_student_without_client_name(self):
        # имя клиента не вытащилось из DOM — всё равно предполагаем родителя
        hint = _recipient_hint(make_order("Артём, 11 класс"))
        assert "родитель" in hint

    def test_client_case_insensitive_match(self):
        hint = _recipient_hint(make_order("артём", "Артём"))
        assert "самим учеником" in hint


class TestSelfStudent:
    def test_same_name(self):
        hint = _recipient_hint(make_order("Артём", "Артём"))
        assert "самим учеником" in hint
        assert "напрямую" in hint


class TestUnknown:
    def test_no_student_neutral(self):
        hint = _recipient_hint(make_order(client="Ольга"))
        assert "неясно" in hint and "нейтрально" in hint

    def test_empty_order_neutral(self):
        hint = _recipient_hint({})
        assert "неясно" in hint
