from __future__ import annotations

from types import SimpleNamespace

from profi.storage import Store


def _candidate(store: Store, order_id: str) -> None:
    store.create_candidate(
        SimpleNamespace(
            id=order_id,
            last_update=1,
            title="test",
            raw={"id": order_id},
        ),
        None,
        None,
    )


def test_claim_send_records_start_timestamp(tmp_path):
    store = Store(tmp_path / "state.db")
    try:
        _candidate(store, "1")
        assert store.claim_send("1") is True
        row = store.get_candidate("1")
        assert row["send_status"] == "sending"
        assert row["send_started_at"] is not None
    finally:
        store.close()


def test_stale_sending_becomes_terminal_unknown_without_retry(tmp_path):
    store = Store(tmp_path / "state.db")
    try:
        _candidate(store, "1")
        assert store.claim_send("1") is True
        store.conn.execute(
            "UPDATE candidates SET send_started_at=?, updated_at=? WHERE order_id='1'",
            (100, 100),
        )
        store.conn.commit()

        result = store.reconcile_stale_sending(max_age_s=300, now=1000)
        row = store.get_candidate("1")
        assert result == 1
        assert row["send_status"] == "unknown"
        assert row["sent_at"] == 1000
        assert "stale sending" in (row["last_error"] or "").lower()
        assert store.claim_send("1") is False
    finally:
        store.close()


def test_fresh_sending_is_not_reconciled(tmp_path):
    store = Store(tmp_path / "state.db")
    try:
        _candidate(store, "1")
        assert store.claim_send("1") is True
        store.conn.execute(
            "UPDATE candidates SET send_started_at=?, updated_at=? WHERE order_id='1'",
            (900, 900),
        )
        store.conn.commit()

        assert store.reconcile_stale_sending(max_age_s=300, now=1000) == 0
        assert store.get_candidate("1")["send_status"] == "sending"
    finally:
        store.close()


def test_old_database_is_migrated_with_send_started_at(tmp_path):
    db = tmp_path / "old.db"
    store = Store(db)
    try:
        store.conn.execute("DROP VIEW v_responses")
        store.conn.execute("DROP VIEW v_prompt_experiments")
        store.conn.execute("ALTER TABLE candidates DROP COLUMN send_started_at")
        store.conn.commit()
    finally:
        store.close()

    migrated = Store(db)
    try:
        columns = {row[1] for row in migrated.conn.execute("PRAGMA table_info(candidates)")}
        assert "send_started_at" in columns
    finally:
        migrated.close()
