from __future__ import annotations

from types import SimpleNamespace

from profi.storage import Store


def _candidate(store: Store, order_id: str) -> None:
    store.create_candidate(
        SimpleNamespace(id=order_id, last_update=1, title="test", raw={"id": order_id}),
        None,
        None,
    )
    store.assign_prompt_variant(order_id, "exp", ("A",))


def test_prompt_view_measures_send_rate_and_reply_yield_over_llm_evaluated(tmp_path):
    store = Store(tmp_path / "exp.db")
    try:
        # LLM send + client reply.
        _candidate(store, "1")
        store.set_draft("1", "generated", text="Первый текст " * 12, source="llm")
        store.set_send_status("1", "sent")
        assert store.mark_client_reply("1") is True

        # LLM send without reply.
        _candidate(store, "2")
        store.set_draft("2", "generated", text="Второй текст " * 12, source="llm")
        store.set_send_status("2", "sent")

        # LLM explicit skip: variant affected the business decision, so this is
        # part of the experiment denominator even though no text was generated.
        _candidate(store, "3")
        store.set_draft("3", "skipped", source="llm")
        store.set_send_status("3", "skipped")

        # Provider outage -> profile fallback. Variant did not drive the final
        # reply, so it must not dilute the LLM experiment denominator.
        _candidate(store, "4")
        store.set_draft("4", "generated", text="Fallback текст " * 12, source="fallback")
        store.set_send_status("4", "sent")

        row = store.conn.execute(
            "SELECT * FROM v_prompt_experiments WHERE prompt_experiment='exp' AND prompt_variant='A'"
        ).fetchone()

        assert row["assigned"] == 4
        assert row["evaluated"] == 3
        assert row["generated"] == 2
        assert row["fallbacks"] == 1
        assert row["sent"] == 2
        assert row["replied"] == 1
        assert row["send_rate_pct"] == 66.7
        assert row["reply_rate_pct"] == 50.0
        assert row["reply_yield_pct"] == 33.3
    finally:
        store.close()
