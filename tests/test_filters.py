"""Hard-фильтры: parse_price_max + hard_filter (спека разд. 14)."""

import pytest

from profi import config
from profi.filters import hard_filter, parse_price_max
from profi.models import OrderSnippet


def make_snippet(**kw) -> OrderSnippet:
    defaults = dict(
        id="1",
        title="Репетитор информатики",
        description="Нужна подготовка к ЕГЭ",
        price_raw="1000 ₽",
        last_update=1700000000,
        score=None,
    )
    defaults.update(kw)
    return OrderSnippet(**defaults)


@pytest.fixture(autouse=True)
def filter_rules(monkeypatch):
    """Детерминированные правила фильтрации, независимые от окружения."""
    monkeypatch.setattr(config, "SUBJECT_KEYWORDS", ["информатик", "программирован"])
    monkeypatch.setattr(config, "VACANCY_PATTERNS", ["ваканс"])
    monkeypatch.setattr(config, "REMOTE_ONLY", True)
    monkeypatch.setattr(config, "MIN_RATE", None)


class TestParsePriceMax:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("450–600 ₽", 600),
            ("до 2100 ₽", 2100),
            ("45 000 ₽", 45000),  # пробел — разряды
            ("45\u00a0000 ₽", 45000),  # nbsp — разряды
            ("1000", 1000),  # без знака валюты
        ],
    )
    def test_parses_max(self, raw, expected):
        assert parse_price_max(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["от 2000 ₽", None, "", "договорная"],
    )
    def test_unknown_ceiling_returns_none(self, raw):
        # «от N» — потолок неизвестен; пустое/нечисловое — тоже
        assert parse_price_max(raw) is None


class TestHardFilter:
    def test_pass(self):
        s = make_snippet(geo_remote="Дистанционно")
        assert hard_filter(s).passed

    def test_vacancy_skipped_in_title(self):
        s = make_snippet(title="Вакансия преподавателя информатики")
        v = hard_filter(s)
        assert not v.passed and "вакансию" in v.reason

    def test_vacancy_skipped_in_badges(self):
        s = make_snippet(badges=["вакансия"], geo_remote="Дистанционно")
        assert not hard_filter(s).passed

    def test_subject_not_matched(self):
        s = make_snippet(title="Репетитор по математике", geo_remote="Дистанционно")
        v = hard_filter(s)
        assert not v.passed and "предмет" in v.reason

    def test_remote_empty_skipped(self):
        s = make_snippet(geo_remote="")
        v = hard_filter(s)
        assert not v.passed and "очно" in v.reason

    def test_remote_none_passed(self):
        # философия спеки: сомневаемся в поле (None) — не режем заказ
        s = make_snippet(geo_remote=None)
        assert hard_filter(s).passed

    def test_min_rate_off_ignores_price(self, monkeypatch):
        monkeypatch.setattr(config, "MIN_RATE", None)
        s = make_snippet(price_raw="100 ₽", geo_remote="Дистанционно")
        assert hard_filter(s).passed

    def test_min_rate_low_budget_skipped(self, monkeypatch):
        monkeypatch.setattr(config, "MIN_RATE", 500)
        s = make_snippet(price_raw="до 400 ₽", geo_remote="Дистанционно")
        v = hard_filter(s)
        assert not v.passed and "бюджет" in v.reason
