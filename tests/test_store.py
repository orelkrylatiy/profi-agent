"""SQLite-память: дедуп ленты, статусы кандидатов, денежные гейты (спека разд. 13, 17–18)."""

from profi.models import OrderSnippet
from profi.storage import Store


def make_store(tmp_path) -> Store:
    return Store(tmp_path / "test.db")


def make_snippet(order_id="1", last_update=100) -> OrderSnippet:
    return OrderSnippet(
        id=order_id,
        title="t",
        description="d",
        price_raw=None,
        last_update=last_update,
        score=None,
        raw={"id": order_id},
    )


class TestFeedSeen:
    def test_new_unchanged_updated(self, tmp_path):
        store = make_store(tmp_path)
        assert store.register_feed_seen("1", 100) == "NEW"
        assert store.register_feed_seen("1", 100) == "UNCHANGED"
        assert store.register_feed_seen("1", 200) == "UPDATED"

    def test_none_last_update_treated_as_zero(self, tmp_path):
        store = make_store(tmp_path)
        assert store.register_feed_seen("1", None) == "NEW"
        assert store.register_feed_seen("1", None) == "UNCHANGED"


class TestCandidates:
    def test_create_defaults(self, tmp_path):
        store = make_store(tmp_path)
        store.create_candidate(make_snippet(), "rule-pass", None)
        row = store.get_candidate("1")
        assert row["details_status"] == "pending"
        assert row["draft_status"] == "pending"
        assert row["send_status"] == "not_sent"

    def test_set_send_status_missing_order(self, tmp_path):
        store = make_store(tmp_path)
        assert store.set_send_status("404", "sent") is False

    def test_ensure_candidate_keeps_statuses(self, tmp_path):
        store = make_store(tmp_path)
        store.create_candidate(make_snippet(), None, None)
        store.set_send_status("1", "sent")
        store.ensure_candidate("1", "новый тайтл")
        assert store.get_candidate("1")["send_status"] == "sent"


class TestMoneyGates:
    def test_sends_today_counts_sent_and_unknown_only(self, tmp_path):
        store = make_store(tmp_path)
        for oid, status in (("1", "sent"), ("2", "unknown"), ("3", "skipped"), ("4", "not_sent")):
            store.create_candidate(make_snippet(oid), None, None)
            store.set_send_status(oid, status)
        assert store.sends_today() == 2  # skipped и not_sent не списывают лимит

    def test_sends_today_only_since_midnight(self, tmp_path):
        import datetime as dt
        import time

        store = make_store(tmp_path)
        store.create_candidate(make_snippet("1"), None, None)
        store.set_send_status("1", "sent")
        midnight = int(
            dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        store.conn.execute("UPDATE candidates SET sent_at = ?", (midnight - 3600,))
        store.conn.commit()
        time.sleep(0.01)
        assert store.sends_today() == 0


class TestChatLog:
    def test_last_sent_only_tutor(self, tmp_path):
        store = make_store(tmp_path)
        store.log_chat("1", "Вера", "client", "Здравствуйте!")
        assert store.last_chat_sent_at("1") is None
        store.log_chat("1", "Вера", "tutor", "Добрый день!")
        assert store.last_chat_sent_at("1") is not None


class TestResponsesView:
    def test_v_responses_extracts_price(self, tmp_path):
        store = make_store(tmp_path)
        store.create_candidate(make_snippet("1"), "резон", None)
        store.update_details("1", "ready", '{"bid_price": 300, "competition_position": 5}')
        store.set_send_status("1", "sent")
        row = store.conn.execute("SELECT * FROM v_responses WHERE order_id='1'").fetchone()
        assert row["bid_price"] == 300
        assert row["position"] == 5
        assert row["send_status"] == "sent"


def test_wal_mode(tmp_path):
    # два процесса на одной БД (воркер + автопилот) — WAL обязателен (ревью P2)
    store = make_store(tmp_path)
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


class TestMoneyFacts:
    def test_record_response_and_paid(self, tmp_path):
        store = make_store(tmp_path)
        store.create_candidate(make_snippet("1"), None, None)
        store.update_details("1", "ready", '{"bid_price": 300}')
        store.set_send_status("1", "sent")
        store.record_response("1", "commission", 0)
        row = store.conn.execute("SELECT * FROM v_responses WHERE order_id='1'").fetchone()
        assert row["respond_mode"] == "commission"
        assert row["paid"] == 0  # комиссия: вперёд не платим

    def test_paid_falls_back_to_bid_price_for_old_rows(self, tmp_path):
        store = make_store(tmp_path)
        store.create_candidate(make_snippet("2"), None, None)
        store.update_details("2", "ready", '{"bid_price": 240}')
        store.set_send_status("2", "sent")
        row = store.conn.execute("SELECT * FROM v_responses WHERE order_id='2'").fetchone()
        assert row["paid"] == 240  # старые отправки: цена из карточки

    def test_migration_adds_columns_to_old_db(self, tmp_path):
        store = make_store(tmp_path)
        store.conn.execute("DROP VIEW v_responses")  # вьюха мешает DROP COLUMN
        store.conn.execute("ALTER TABLE candidates DROP COLUMN respond_mode")
        store.conn.execute("ALTER TABLE candidates DROP COLUMN paid_rub")
        store.conn.commit()
        store.close()
        store2 = make_store(tmp_path)  # повторное открытие дожимает миграцию
        cols = {r[1] for r in store2.conn.execute("PRAGMA table_info(candidates)")}
        assert {"respond_mode", "paid_rub"} <= cols
