"""Парсер строк диалогов + лимит догонялок (инцидент «8 догонялок Алисе»)
+ ретрай потерянных сообщений (инцидент 05.09 «Усмонали»).

Строки взяты из живого aria-снапшота страницы чатов profi (04.09).
"""

import time

from profi.integration.chat import classify_dialog_row, ensure_desktop_width
from profi.main import _chat_target
from profi.storage.store import Store


# --- ensure_desktop_width: узкое окно = мобильный режим виджета (05.09) ---

class _FakeSession:
    def __init__(self):
        self.sent = []

    def send(self, method, params=None):
        self.sent.append((method, params))
        if method == "Browser.getWindowForTarget":
            return {"windowId": 42, "bounds": {}}
        return {}


class _FakeContext:
    def __init__(self):
        self.session = _FakeSession()

    def new_cdp_session(self, page):
        return self.session


class _FakePage:
    def __init__(self, inner_width):
        self._w = inner_width
        self.context = _FakeContext()
        self.waits = 0

    def evaluate(self, _expr):
        return self._w

    def wait_for_timeout(self, _ms):
        self.waits += 1


def test_narrow_window_gets_resized():
    page = _FakePage(767)
    ensure_desktop_width(page)
    methods = [m for m, _ in page.context.session.sent]
    assert "Browser.setWindowBounds" in methods
    bounds = dict(page.context.session.sent)["Browser.setWindowBounds"]["bounds"]
    assert bounds["width"] >= 900


def test_wide_window_left_alone():
    page = _FakePage(1087)
    ensure_desktop_width(page)
    assert page.context.session.sent == []


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

def _store_with_dialog(tmp_path, order_id, events, client_name="Тест"):
    store = Store(str(tmp_path / "t.db"))
    for sender, text in events:
        store.log_chat(order_id, client_name, sender, text)
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


# --- _chat_target: ретрай потерянных сообщений (инцидент 05.09 «Усмонали») ---

def _target(store, row_text):
    return _chat_target(store, classify_dialog_row(row_text))


def test_unread_client_message_is_target(tmp_path):
    store = _store_with_dialog(tmp_path, "10", [])
    assert _target(store, "Алиса Привет! Когда удобно? 2")


def test_send_failed_with_zero_unread_is_retried(tmp_path):
    # инцидент 05.09: клиент написал, отправка упала, счётчик 0
    store = _store_with_dialog(
        tmp_path, "11",
        [("client", "Ты в каком городе"), ("system", "SEND_FAILED: текст остался в поле")],
        client_name="Усмонали",
    )
    assert _target(store, "Усмонали Максим Ты в каком городе 0")


def test_two_send_failed_in_a_row_gives_up(tmp_path):
    store = _store_with_dialog(
        tmp_path, "12",
        [
            ("client", "вопрос"),
            ("system", "SEND_FAILED: раз"),
            ("client", "вопрос"),
            ("system", "SEND_FAILED: два"),
        ],
        client_name="Усмонали",
    )
    assert not _target(store, "Усмонали вопрос 0")


def test_needs_human_not_retried_without_unread(tmp_path):
    store = _store_with_dialog(
        tmp_path, "13",
        [("client", "торг"), ("system", "NEEDS_HUMAN: торгуется")],
        client_name="Борис",
    )
    assert not _target(store, "Борис Давай дешевле 0")


def test_needs_human_with_unread_also_blocked(tmp_path):
    # решение по последнему сообщению принято — не переигрываем
    store = _store_with_dialog(
        tmp_path, "14",
        [("client", "торг"), ("system", "NEEDS_HUMAN: торгуется")],
        client_name="Борис",
    )
    assert not _target(store, "Борис Ну так что, давай дешевле 1")


def test_our_last_message_not_target(tmp_path):
    store = _store_with_dialog(tmp_path, "15", [("tutor", "Здравствуйте!")])
    assert not _target(store, "Алсу Вы: Здравствуйте! 0")


def test_answered_dialog_not_target_even_client_last_stale(tmp_path):
    # последний в логе tutor: на последнее видимое client-сообщение мы уже
    # ответили — не цель (новое сообщение клиента подняло бы unread).
    store = _store_with_dialog(
        tmp_path, "16", [("client", "ок"), ("tutor", "Отлично")], client_name="Ирина",
    )
    assert not _target(store, "Ирина Отлично 0")


def test_unanswered_client_with_zero_unread_retried(tmp_path):
    # клиент написал, мы даже не пытались (воркер перезапнулся) — ретраим
    store = _store_with_dialog(
        tmp_path, "17", [("client", "Ты в каком городе")], client_name="Усмонали",
    )
    assert _target(store, "Усмонали Максим Ты в каком городе 0")


def test_stale_unanswered_message_not_retried(tmp_path):
    # сообщение старше 2 часов и ответ так и не ушёл — оставляем владельцу
    store = _store_with_dialog(
        tmp_path, "18", [("client", "Ты в каком городе")], client_name="Усмонали",
    )
    store.conn.execute(
        "UPDATE chat_log SET created_at = ? WHERE order_id = '18'",
        (int(time.time()) - 3 * 3600,),
    )
    store.conn.commit()
    assert not _target(store, "Усмонали Максим Ты в каком городе 0")
