"""Контур B: регрессии на self-reply, парсинг диалогов и подтверждение отправки.

Это не coverage-driven тесты. Здесь зафиксированы инварианты, нарушение которых
может привести к сообщению не тому клиенту, дублю своего ответа или ложному sent.
"""

from __future__ import annotations

import sqlite3

import profi.main as main
from profi.integration import chat


class TestDialogCardParsing:
    def test_client_message_with_multiword_name(self):
        d = chat._parse_dialog_card(
            "А\n\nАнна Краморенко\nЗдравствуйте, можно завтра?\n2\n20:51\n",
            "/backoffice/r.php?id=93323334&filter=open",
        )
        assert d == {
            "name": "Анна Краморенко",
            "order_id": "93323334",
            "unread": 2,
            "preview": "Здравствуйте, можно завтра?",
            "last_is_ours": False,
        }

    def test_own_message_with_multiword_name_is_detected(self):
        # Регрессия главного self-reply бага: старый parser брал name='Анна'
        # и не узнавал строку «Анна Краморенко Вы: ...».
        d = chat._parse_dialog_card(
            "А\n\nАнна Краморенко\nВы: Да, завтра удобно\n1\nВт\n",
            "/backoffice/r.php?id=42",
        )
        assert d["name"] == "Анна Краморенко"
        assert d["last_is_ours"] is True
        assert d["unread"] == 1

    def test_no_avatar_is_supported(self):
        d = chat._parse_dialog_card(
            "Вера\nДобрый день\n1\nВчера\n",
            "/backoffice/r.php?id=77",
        )
        assert d["name"] == "Вера"
        assert d["preview"] == "Добрый день"
        assert d["last_is_ours"] is False

    def test_date_is_not_part_of_preview(self):
        d = chat._parse_dialog_card(
            "И\nИрина\nКогда удобно?\n3\n2 окт\n",
            "/backoffice/r.php?id=10",
        )
        assert d["preview"] == "Когда удобно?"
        assert d["unread"] == 3

    def test_empty_preview_is_not_proven_client_message(self):
        d = chat._parse_dialog_card(
            "А\nАнна\n1\n20:51\n",
            "/backoffice/r.php?id=1",
        )
        assert d["preview"] == ""
        assert d["last_is_ours"] is None

    def test_bad_href_does_not_invent_identity(self):
        d = chat._parse_dialog_card("Анна\nПривет\n1\n20:51", "/backoffice/r.php")
        assert d["order_id"] == ""


class _FakeLink:
    def __init__(self, text: str, href: str):
        self.text = text
        self.href = href

    def inner_text(self, timeout=None):
        return self.text

    def get_attribute(self, name):
        return self.href if name == "href" else None


class _Collection:
    def __init__(self, items):
        self.items = list(items)

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]


class _SnapshotBody:
    def __init__(self, snapshot: str):
        self.snapshot = snapshot

    def aria_snapshot(self):
        return self.snapshot


class _DialogListPage:
    def __init__(self, links=(), snapshot=""):
        self.links = _Collection(links)
        self.body = _SnapshotBody(snapshot)

    def locator(self, selector):
        if selector == 'a[href*="r.php?id="]':
            return self.links
        if selector == "body":
            return self.body
        raise AssertionError(selector)


class TestDialogList:
    def test_links_are_primary_and_keep_stable_order_id(self):
        page = _DialogListPage(
            links=[
                _FakeLink(
                    "А\nАнна Краморенко\nВы: Уже ответил\n1\n20:51",
                    "/backoffice/r.php?id=111&filter=open",
                ),
                _FakeLink(
                    "В\nВера\nМожно сегодня?\n2\nВт",
                    "/backoffice/r.php?id=222&filter=open",
                ),
            ]
        )
        dialogs = chat.list_dialogs(page)
        assert [d["order_id"] for d in dialogs] == ["111", "222"]
        assert dialogs[0]["name"] == "Анна Краморенко"
        assert dialogs[0]["last_is_ours"] is True
        assert dialogs[1]["last_is_ours"] is False

    def test_duplicate_href_is_deduplicated(self):
        page = _DialogListPage(
            links=[
                _FakeLink("А\nАнна\nПривет\n1\n20:51", "/backoffice/r.php?id=1"),
                _FakeLink("А\nАнна\nПривет\n1\n20:51", "/backoffice/r.php?id=1"),
            ]
        )
        assert len(chat.list_dialogs(page)) == 1

    def test_aria_fallback_detects_own_message_after_multiword_name(self):
        snapshot = "\n".join(
            [
                "- paragraph: А",
                '- text: "Анна Краморенко Вы: Да, договорились 1"',
            ]
        )
        dialogs = chat.list_dialogs(_DialogListPage(snapshot=snapshot))
        assert len(dialogs) == 1
        assert dialogs[0]["last_is_ours"] is True


class TestTargetSelection:
    def test_only_unread_with_proven_client_last(self):
        dialogs = [
            {"name": "client", "unread": 1, "last_is_ours": False},
            {"name": "ours", "unread": 2, "last_is_ours": True},
            {"name": "read", "unread": 0, "last_is_ours": False},
            {"name": "unknown", "unread": 3, "last_is_ours": None},
            {"name": "missing", "unread": 4},
        ]
        assert [d["name"] for d in chat.select_reply_targets(dialogs)] == ["client"]

    def test_limit_two_and_order_preserved(self):
        dialogs = [
            {"name": str(i), "unread": 1, "last_is_ours": False} for i in range(5)
        ]
        assert [d["name"] for d in chat.select_reply_targets(dialogs)] == ["0", "1"]

    def test_zero_limit(self):
        dialogs = [{"name": "x", "unread": 1, "last_is_ours": False}]
        assert chat.select_reply_targets(dialogs, limit=0) == []


class _FakeBox:
    def __init__(self, *, fail_on_final_read=False):
        self.value = ""
        self.reads = 0
        self.fail_on_final_read = fail_on_final_read

    def is_visible(self):
        return True

    def evaluate(self, script):
        return "TEXTAREA"

    def input_value(self, timeout=None):
        self.reads += 1
        if self.fail_on_final_read and self.reads >= 2:
            raise RuntimeError("detached")
        return self.value


class _FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        assert key == "Enter"
        if self.page.enter_sends:
            self.page.box.value = ""


class _FakeButton:
    def __init__(self, page):
        self.page = page

    def click(self, delay=None):
        self.page.box.value = ""


class _ButtonCollection:
    def __init__(self, page, exists):
        self.page = page
        self.exists = exists
        self.first = _FakeButton(page)

    def count(self):
        return 1 if self.exists else 0


class _SendPage:
    def __init__(self, *, has_box=True, enter_sends=True, button_sends=False, fail_final=False):
        self.box = _FakeBox(fail_on_final_read=fail_final)
        self.has_box = has_box
        self.enter_sends = enter_sends
        self.button_sends = button_sends
        self.keyboard = _FakeKeyboard(self)

    def locator(self, selector):
        if selector == 'textarea[placeholder*="ообщени"]' and self.has_box:
            return _Collection([self.box])
        return _Collection([])

    def get_by_text(self, name, exact=True):
        return _ButtonCollection(self, self.button_sends and name == "Отправить")

    def wait_for_timeout(self, ms):
        pass


class TestSendReply:
    @staticmethod
    def _patch_typing(monkeypatch):
        monkeypatch.setattr(chat, "human_pause", lambda *a, **k: None)
        monkeypatch.setattr(chat, "type_human", lambda page, box, text: setattr(box, "value", text))

    def test_enter_success(self, monkeypatch):
        self._patch_typing(monkeypatch)
        assert chat.send_reply(_SendPage(enter_sends=True), "Нормальный ответ клиенту") is True

    def test_button_fallback_success(self, monkeypatch):
        self._patch_typing(monkeypatch)
        page = _SendPage(enter_sends=False, button_sends=True)
        assert chat.send_reply(page, "Нормальный ответ клиенту") is True

    def test_text_left_in_box_is_failure(self, monkeypatch):
        self._patch_typing(monkeypatch)
        page = _SendPage(enter_sends=False, button_sends=False)
        assert chat.send_reply(page, "Нормальный ответ клиенту") is False

    def test_no_input_is_failure(self, monkeypatch):
        self._patch_typing(monkeypatch)
        assert chat.send_reply(_SendPage(has_box=False), "Нормальный ответ клиенту") is False

    def test_unknown_final_verification_is_not_success(self, monkeypatch):
        # Регрессия: раньше финальный input_value exception проглатывался и
        # send_reply возвращал True, хотя факт отправки не был подтверждён.
        self._patch_typing(monkeypatch)
        page = _SendPage(enter_sends=False, button_sends=True, fail_final=True)
        assert chat.send_reply(page, "Нормальный ответ клиенту") is False


class _AutoPage:
    def close(self, run_before_unload=False):
        pass

    def screenshot(self, path, full_page=False):
        pass


class _AutoCtx:
    def new_page(self):
        return _AutoPage()


class TestRunChatAutoSelfReplyRegression:
    def _base(self, monkeypatch, tmp_path):
        from profi.integration import chat as chat_mod

        monkeypatch.setattr(main, "in_work_hours", lambda *a, **k: True)
        monkeypatch.setattr(main, "_llm_cooldown_until", lambda: 0)
        monkeypatch.setattr(main, "_lock_acquire", lambda path: True)
        monkeypatch.setattr(main.config, "AUTOPILOT_LOCK", tmp_path / "no-real-lock")
        monkeypatch.setattr(main.config, "DB_PATH", tmp_path / "chat.db")
        monkeypatch.setattr(chat_mod, "open_chats", lambda page: None)
        monkeypatch.setattr(chat_mod, "human_pause", lambda *a, **k: None)
        return chat_mod

    def test_unread_own_message_never_opens_dialog(self, monkeypatch, tmp_path):
        chat_mod = self._base(monkeypatch, tmp_path)
        monkeypatch.setattr(
            chat_mod,
            "list_dialogs",
            lambda page: [{"name": "Анна", "unread": 1, "last_is_ours": True}],
        )
        monkeypatch.setattr(
            chat_mod,
            "open_dialog_by_name",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("own message was opened")),
        )
        assert main.run_chat_auto(ctx=_AutoCtx()) == 0

    def test_client_message_can_reach_send_once(self, monkeypatch, tmp_path):
        from profi import llm as llm_mod

        chat_mod = self._base(monkeypatch, tmp_path)
        monkeypatch.setattr(
            chat_mod,
            "list_dialogs",
            lambda page: [{"name": "Вера", "unread": 1, "last_is_ours": False}],
        )
        opened = []
        sent = []
        monkeypatch.setattr(
            chat_mod, "open_dialog_by_name", lambda page, name: opened.append(name) or "123"
        )
        monkeypatch.setattr(chat_mod, "read_dialog_text", lambda page: "Вера: Можно завтра?")
        monkeypatch.setattr(chat_mod, "send_reply", lambda page, text: sent.append(text) or True)
        monkeypatch.setattr(llm_mod, "models_chain", lambda: ["fake"])
        monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: "{}")
        monkeypatch.setattr(
            llm_mod,
            "json_reply",
            lambda raw: {
                "reply": "Да, давайте подберём удобное время для пробного занятия.",
                "needs_human": False,
                "note": "",
            },
        )
        assert main.run_chat_auto(ctx=_AutoCtx()) == 0
        assert opened == ["Вера"]
        assert len(sent) == 1

        con = sqlite3.connect(tmp_path / "chat.db")
        assert con.execute("SELECT COUNT(*) FROM chat_log WHERE sender='tutor'").fetchone()[0] == 1
        con.close()

    def test_one_dialog_failure_does_not_block_next(self, monkeypatch, tmp_path):
        from profi import llm as llm_mod

        chat_mod = self._base(monkeypatch, tmp_path)
        monkeypatch.setattr(
            chat_mod,
            "list_dialogs",
            lambda page: [
                {"name": "Broken", "unread": 1, "last_is_ours": False},
                {"name": "Good", "unread": 1, "last_is_ours": False},
            ],
        )

        def open_dialog(page, name):
            if name == "Broken":
                raise RuntimeError("broken dialog")
            return "2"

        sent = []
        monkeypatch.setattr(chat_mod, "open_dialog_by_name", open_dialog)
        monkeypatch.setattr(chat_mod, "read_dialog_text", lambda page: "Можно завтра?")
        monkeypatch.setattr(chat_mod, "send_reply", lambda page, text: sent.append(text) or True)
        monkeypatch.setattr(llm_mod, "models_chain", lambda: ["fake"])
        monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: "{}")
        monkeypatch.setattr(
            llm_mod,
            "json_reply",
            lambda raw: {
                "reply": "Да, можем обсудить удобное время пробного занятия.",
                "needs_human": False,
                "note": "",
            },
        )
        assert main.run_chat_auto(ctx=_AutoCtx()) == 0
        assert len(sent) == 1
