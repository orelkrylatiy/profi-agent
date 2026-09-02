"""Регрессионные тесты на фиксы ревью 2026-09-02 (P0/P1/P2)."""

import importlib
import os
import time
from datetime import datetime
from pathlib import Path

import profi.main as main


class TestNowRu:
    def test_known_date(self):
        # 2026-09-02 — среда (вычислено по календарю)
        assert main._now_ru(datetime(2026, 9, 2, 21, 30)) == "Сейчас 21:30, среда."

    def test_monday(self):
        assert main._now_ru(datetime(2026, 8, 31, 1, 5)) == "Сейчас 01:05, понедельник."

    def test_no_hardcoded_weekday(self):
        # восемь дней подряд — восемь разных дней
        days = {main._now_ru(datetime(2026, 9, d)).split(", ")[-1] for d in range(1, 8)}
        assert len(days) == 7


class TestWorkerPattern:
    def test_tagged_only_own_account(self, monkeypatch):
        monkeypatch.setenv("PROFI_RHYTHM_TAG", "lang")
        pat = main._worker_pattern()
        assert pat == r"profi\.main --rhythm-tag lang$"
        import re

        assert re.search(pat, "uv run python -m profi.main --rhythm-tag lang")
        assert not re.search(pat, "uv run python -m profi.main --rhythm-tag info")
        assert not re.search(pat, "python -m profi.main autopilot")  # автопилот не трогаем

    def test_untagged_matches_any_worker(self, monkeypatch):
        monkeypatch.delenv("PROFI_RHYTHM_TAG", raising=False)
        pat = main._worker_pattern()
        import re

        assert re.search(pat, "python -m profi.main")
        assert re.search(pat, "python -m profi.main --rhythm-tag info")
        assert not re.search(pat, "python -m profi.main autopilot")


class TestLockAcquire:
    def test_fresh_acquire_and_conflict(self, tmp_path):
        lock = tmp_path / "autopilot.lock"
        assert main._lock_acquire(lock) is True
        assert main._lock_acquire(lock) is False  # сосед жив — выходим

    def test_stale_lock_taken_over(self, tmp_path):
        lock = tmp_path / "autopilot.lock"
        lock.write_text("")
        old = time.time() - 31 * 60
        os.utime(lock, (old, old))  # имитируем OOM: лок остался с прошлой эпохи
        assert main._lock_acquire(lock) is True

    def test_young_lock_not_taken(self, tmp_path):
        lock = tmp_path / "autopilot.lock"
        lock.write_text("")
        assert main._lock_acquire(lock) is False


class TestVacancyGate:
    def test_new_cards_card_tags(self):
        d = {"card_tags": ["1500 ₽", "Возможно, вакансия"]}
        assert main._is_vacancy_card(d) is True

    def test_old_cards_raw_fallback(self):
        d = {"raw_bo_order_screen": {"tags": [{"text": "Возможно, вакансия"}]}}
        assert main._is_vacancy_card(d) is True

    def test_description_word_not_a_trigger(self):
        # «это не вакансия, ищу наставника» в тексте заказа — НЕ гейт (ревью P2)
        d = {"description": "Это не вакансия, ищу наставника для сына", "card_tags": ["до 600 ₽"]}
        assert main._is_vacancy_card(d) is False

    def test_clean_card(self):
        d = {"raw_bo_order_screen": {"tags": [{"text": "Заказ от школьника"}]}}
        assert main._is_vacancy_card(d) is False


class TestChatSystemPersona:
    """CHAT_SYSTEM должен говорить персоной АККАУНТА, а не «репетитором
    информатики» для всех (ревью P0-2), и брать ставку из config.RATE."""

    def test_lang_persona_in_chat(self, monkeypatch):
        # config.PERSONA читается при импорте конфига — патчим атрибут,
        # промпты пересобираем reload(main)
        monkeypatch.setattr(main.config, "PERSONA", "lang")
        try:
            mod = importlib.reload(main)
            assert "английск" in mod.CHAT_SYSTEM
            assert "информатик" not in mod.CHAT_SYSTEM
            assert str(mod.config.RATE) in mod.CHAT_SYSTEM  # ставка из config, не литерал
        finally:
            monkeypatch.undo()
            importlib.reload(main)

    def test_default_persona_and_rate(self):
        assert "ставка" in main.CHAT_SYSTEM
        assert str(main.config.RATE) in main.CHAT_SYSTEM

    def test_triage_has_goal_and_json(self):
        assert "ЦЕЛЬ отклика" in main.TRIAGE_SYSTEM
        assert "СТРОГО JSON" in main.TRIAGE_SYSTEM
        assert "информатик" in main.TRIAGE_SYSTEM.lower()


class TestLockPath:
    def test_lock_is_path(self):
        assert isinstance(main.config.DATA_DIR / "autopilot.lock", Path)


class TestPaymentDue:
    """Гейты оплаты зависят от режима (комиссия: предоплаты нет)."""

    def test_pay_normal(self):
        assert main._payment_due("pay", {"to_pay": 300}) == (300, "")

    def test_pay_no_to_pay(self):
        due, why = main._payment_due("pay", {})
        assert due is None and "К оплате" in why

    def test_pay_over_limit(self, monkeypatch):
        monkeypatch.setattr(main.config, "MAX_RESPONSE_PRICE_RUB", 500)
        due, why = main._payment_due("pay", {"to_pay": 501})
        assert due is None and "потолка" in why

    def test_commission_zero_and_none_ok(self):
        assert main._payment_due("commission", {"to_pay": 0}) == (0, "")
        assert main._payment_due("commission", {}) == (0, "")

    def test_commission_with_price_cancels(self):
        due, why = main._payment_due("commission", {"to_pay": 117})
        assert due is None and "выбран неверно" in why
