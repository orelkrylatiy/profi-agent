"""Рабочие часы: единый гейт автономных контуров (RULES 8–23)."""
from datetime import datetime

from profi import config
from profi.utils import in_work_hours


class TestWorkHours:
    def test_boundaries_default(self, monkeypatch):
        monkeypatch.setattr(config, "WORK_HOURS", (8, 23))
        assert not in_work_hours(datetime(2026, 9, 3, 7, 59))
        assert in_work_hours(datetime(2026, 9, 3, 8, 0))  # включительно слева
        assert in_work_hours(datetime(2026, 9, 3, 22, 59))
        assert not in_work_hours(datetime(2026, 9, 3, 23, 0))  # не включая справа

    def test_night_outside(self, monkeypatch):
        monkeypatch.setattr(config, "WORK_HOURS", (8, 23))
        for h in (0, 2, 5, 23):
            assert not in_work_hours(datetime(2026, 9, 3, h, 30))

    def test_round_the_clock(self, monkeypatch):
        monkeypatch.setattr(config, "WORK_HOURS", (0, 24))  # ночной тест владельца
        assert all(in_work_hours(datetime(2026, 9, 3, h)) for h in range(24))
