"""Парсер строк диалогов + лимит догонялок (инцидент «8 догонялок Алисе»).

Строки взяты из живого aria-снапшота страницы чатов profi (04.09).
"""

from profi.integration.chat import classify_dialog_row
from profi.storage.store import Store


# --- classify_dialog_row: живые форматы строк ---

def test_client_last_is_target_shape():
    row = classify_dialog_row("Алиса 6 лет 0")
    assert row["name"] == "Алиса"
    assert row["who_last"] == "client"
    assert row["last_is_ours"] is False
    assert row["unread"] == 0
    assert row["last_text"] == "6 лет"


def test_ours_last():
    row = classify_dialog_row("Алсу Вы: Здравствуйте! Я преподаю английский. ) 0")
    assert row["name"] == "Алсу"
    assert row["who_last"] == "ours"
    assert row["last_is_ours"] is True
    assert row["last_text"].startswith("Здравствуйте!")


def test_system_robot_last_is_not_client():
    # «Робот: Сообщите, если договоритесь…» площадка шлёт и ПОСЛЕ наших
    # сообщений — такой диалог НЕ цель для ответа (инцидент догонялок).
    row = classify_dialog_row("Курт Робот: Сообщите, если договоритесь работать с клиентом. 0")
    assert row["who_last"] == "system"
    assert row["last_is_ours"] is False
    assert row["last_text"].startswith("Сообщите")


def test_unread_from_trailing_count():
    assert classify_dialog_row("Алиса Привет! Когда удобно? 2")["unread"] == 2
    # время внутри текста не ломает счётчик (последнее число — непрочитанные)
    assert classify_dialog_row("Анна Давайте в 18:00 0")["unread"] == 0
    assert classify_dialog_row("Ирина Занятие 60 минут 1")["unread"] == 1


def test_long_texts_and_last_text_cleanup():
    row = classify_dialog_row(
        'Рузана Вы: Здравствуйте! Алексу 6 лет - самое время начать английский ) 0'
    )
    assert row["name"] == "Рузана"
    assert row["who_last"] == "ours"
    assert row["last_text"].endswith("английский )")


# --- Store.chat_tutor_streak: лимит догонялок ---

def _store_with_dialog(tmp_path, order_id, events):
    store = Store(str(tmp_path / "t.db"))
    for sender, text in events:
        store.log_chat(order_id, "Тест", sender, text)
    return store


def test_streak_counts_only_trailing_tutor_rows(tmp_path):
    store = _store_with_dialog(
        tmp_path, "111",
        [("client", "Привет"), ("tutor", "Ответ 1"), ("tutor", "Догонялка")],
    )
    assert store.chat_tutor_streak("111") == 2


def test_streak_resets_on_client_reply(tmp_path):
    store = _store_with_dialog(
        tmp_path, "222",
        [("tutor", "Ответ 1"), ("tutor", "Догонялка"), ("client", "Ок"), ("tutor", "Ответ 2")],
    )
    assert store.chat_tutor_streak("222") == 1


def test_streak_zero_without_history(tmp_path):
    store = _store_with_dialog(tmp_path, "333", [])
    assert store.chat_tutor_streak("333") == 0


def test_streak_ignores_system_rows(tmp_path):
    store = _store_with_dialog(
        tmp_path, "444",
        [("system", "NEEDS_HUMAN: ..."), ("tutor", "Ответ")],
    )
    assert store.chat_tutor_streak("444") == 1
