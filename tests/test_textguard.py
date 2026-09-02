"""Анти-инъекция: контакты/ссылки запрещены, но учебные числа — не контакты.

Регрессия из ревью: «Готовлю к ЕГЭ 2025-2026 учебного года» не должно
палиться как телефон (инцидент класса «постчек отклонил валидный текст»).
"""

from profi.utils.textguard import has_contacts


class TestNotContacts:
    def test_year_range(self):
        assert not has_contacts("Готовлю к ЕГЭ 2025-2026 учебного года")

    def test_year_range_spaced(self):
        assert not has_contacts("подготовку веду с 2025 по 2026 год")

    def test_prices(self):
        assert not has_contacts("занятие 45 000 ₽, пробное 2000")

    def test_grades_and_durations(self):
        assert not has_contacts("9 класс, занимаемся 2 раза в неделю по 90 минут")

    def test_clean_reply(self):
        assert not has_contacts(
            "Здравствуйте! Готовлю к ЕГЭ дистанционно, урок 60-90 минут. Когда удобно начать?"
        )


class TestContacts:
    def test_phone_solid(self):
        assert has_contacts("звоните 89991234567")

    def test_phone_spaced(self):
        assert has_contacts("мой телефон +7 999 123 45 67")

    def test_phone_dashed(self):
        assert has_contacts("8-999-123-45-67")

    def test_url(self):
        assert has_contacts("посмотрите http://site.ru/about")

    def test_email(self):
        assert has_contacts("пишите на tutor@example.com")

    def test_telegram_words(self):
        assert has_contacts("давайте в telegram")
        assert has_contacts("мой тг: t.me/xyz")
