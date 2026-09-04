from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import profi.main as main
from profi import llm as llm_mod
from profi.fastpath import (
    Decision,
    choose_fallback,
    decide_reply,
    full_gate_reason,
    normalize_reply_text,
    process_open_candidate,
)
from profi.integration.orders import OrderOpenError
from profi.storage import Store


@pytest.fixture(autouse=True)
def _fastpath_inside_work_hours(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)


def _details(**overrides):
    base = {
        "id": "93400001",
        "subject": "Информатика",
        "description": "Подготовка к ЕГЭ по информатике",
        "student": "Иван, 11 класс",
        "remote": "Да",
        "bid_price": 250,
        "competition_position": 3,
        "has_bid": False,
        "card_tags": [],
        "client_block_dom": {"name": "Анна"},
    }
    base.update(overrides)
    return base


def _candidate(store: Store, order_id: str = "93400001") -> None:
    snippet = SimpleNamespace(
        id=order_id,
        last_update=1,
        title="ЕГЭ по информатике",
        raw={"id": order_id},
    )
    store.create_candidate(snippet, "rule-pass", None)


class TestFullGates:
    def test_clean_candidate_passes(self):
        assert full_gate_reason(_details()) is None

    def test_vacancy_card_is_terminal_skip(self):
        assert "ваканс" in full_gate_reason(_details(card_tags=["Возможно, вакансия"])).lower()

    def test_expensive_response_is_terminal_skip(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.config, "MAX_RESPONSE_PRICE_RUB", 500)
        assert "501" in full_gate_reason(_details(bid_price=501))

    def test_bad_competition_position_is_terminal_skip(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.config, "MAX_COMPETITION_POSITION", 20)
        assert "21" in full_gate_reason(_details(competition_position=21))

    def test_existing_bid_is_terminal_skip(self):
        assert "уже" in full_gate_reason(_details(has_bid=True)).lower()


class TestReplyText:
    def test_long_text_is_cut_on_sentence_boundary(self):
        text = "А" * 240 + ". " + "Б" * 280 + "."
        normalized, why = normalize_reply_text(text)
        assert why is None
        assert normalized == "А" * 240 + "."
        assert len(normalized) <= 500

    def test_contacts_are_rejected(self):
        normalized, why = normalize_reply_text(
            "Напишите мне +7 999 123 45 67, обсудим занятия." * 3
        )
        assert normalized is None
        assert "контакт" in why.lower()

    def test_short_text_is_rejected(self):
        normalized, why = normalize_reply_text("Могу помочь.")
        assert normalized is None
        assert "корот" in why.lower()

    def test_fallback_choice_is_stable_per_order(self):
        templates = ["A" * 120, "B" * 120, "C" * 120]
        assert choose_fallback("93400001", templates) == choose_fallback("93400001", templates)
        assert choose_fallback("93400001", templates) in templates


class TestDecision:
    def test_valid_llm_send_wins_over_fallback(self, monkeypatch):
        import profi.fastpath as fastpath

        text = "Готов помочь с подготовкой к ЕГЭ по информатике. " * 3
        monkeypatch.setattr(fastpath.llm_mod, "status", lambda: {"key_masked": "***"})
        monkeypatch.setattr(fastpath.llm_mod, "models_chain", lambda: ["fast"])
        monkeypatch.setattr(fastpath.llm_mod, "chat", lambda *a, **k: "raw")
        monkeypatch.setattr(
            fastpath.llm_mod,
            "json_reply",
            lambda raw: {"verdict": "send", "reason": "подходит", "text": text},
        )
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )
        assert decision.action == "send"
        assert decision.source == "llm"
        assert decision.text

    def test_llm_skip_does_not_fallback(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.llm_mod, "status", lambda: {"key_masked": "***"})
        monkeypatch.setattr(fastpath.llm_mod, "models_chain", lambda: ["fast"])
        monkeypatch.setattr(fastpath.llm_mod, "chat", lambda *a, **k: "raw")
        monkeypatch.setattr(
            fastpath.llm_mod,
            "json_reply",
            lambda raw: {"verdict": "skip", "reason": "не наш формат", "text": ""},
        )
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", ["F" * 150])
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )
        assert decision.action == "skip"
        assert decision.source == "llm"

    def test_cooldown_uses_fallback_without_calling_llm(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", ["Ш" * 150])
        monkeypatch.setattr(
            fastpath.llm_mod,
            "chat",
            lambda *a, **k: pytest.fail("LLM must not be called during cooldown"),
        )
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
            llm_blocked=True,
        )
        assert decision == Decision("send", "LLM недоступна: fallback", "Ш" * 150, "fallback")

    def test_limit_error_sets_cooldown_and_falls_back(self, monkeypatch):
        import profi.fastpath as fastpath

        class LimitError(RuntimeError):
            pass

        err = LimitError("429 limit")
        seen = []
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", ["Ф" * 150])
        monkeypatch.setattr(fastpath.llm_mod, "status", lambda: {"key_masked": "***"})
        monkeypatch.setattr(fastpath.llm_mod, "models_chain", lambda: ["fast"])
        monkeypatch.setattr(fastpath.llm_mod, "chat", lambda *a, **k: (_ for _ in ()).throw(err))
        monkeypatch.setattr(fastpath.llm_mod, "is_limit_error", lambda e: e is err)
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
            on_limit=seen.append,
        )
        assert decision.action == "send"
        assert decision.source == "fallback"
        assert seen == [err]

    def test_bad_llm_text_falls_back(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", ["Н" * 150])
        monkeypatch.setattr(fastpath.llm_mod, "status", lambda: {"key_masked": "***"})
        monkeypatch.setattr(fastpath.llm_mod, "models_chain", lambda: ["fast"])
        monkeypatch.setattr(fastpath.llm_mod, "chat", lambda *a, **k: "raw")
        monkeypatch.setattr(
            fastpath.llm_mod,
            "json_reply",
            lambda raw: {"verdict": "send", "reason": "ok", "text": "слишком коротко"},
        )
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )
        assert decision.action == "send"
        assert decision.source == "fallback"

    def test_no_llm_and_no_fallback_is_terminal_failure(self, monkeypatch):
        import profi.fastpath as fastpath

        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", False)
        monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", [])
        decision = decide_reply(
            _details(),
            "93400001",
            system_prompt_factory=lambda: "system",
            user_prompt="order",
            llm_blocked=True,
        )
        assert decision.action == "failed"
        assert decision.text is None


class TestStoreFastPathStates:
    def test_details_ready_claims_candidate_from_legacy_autopilot(self, tmp_path):
        store = Store(tmp_path / "test.db")
        try:
            _candidate(store)
            store.update_details_for_fast_path("93400001", json.dumps(_details()))
            row = store.get_candidate("93400001")
            assert row["details_status"] == "ready"
            assert row["draft_status"] == "generating"
        finally:
            store.close()

    def test_send_claim_is_atomic_and_one_shot(self, tmp_path):
        store = Store(tmp_path / "test.db")
        try:
            _candidate(store)
            assert store.claim_send("93400001") is True
            assert store.claim_send("93400001") is False
            assert store.get_candidate("93400001")["send_status"] == "sending"
        finally:
            store.close()

    def test_draft_source_is_persisted(self, tmp_path):
        store = Store(tmp_path / "test.db")
        try:
            _candidate(store)
            store.set_draft("93400001", "generated", text="Т" * 150, source="fallback")
            row = store.get_candidate("93400001")
            assert row["draft_status"] == "generated"
            assert row["draft_source"] == "fallback"
            assert row["draft_text"] == "Т" * 150
        finally:
            store.close()


class _FakeStore:
    def __init__(self):
        self.calls = []
        self.send_status = "not_sent"
        self.sent_today = 0

    def sends_today(self):
        return self.sent_today

    def set_draft(self, order_id, status, text=None, source=None, error=None):
        self.calls.append(("draft", status, text, source, error))

    def set_send_status(self, order_id, status):
        self.send_status = status
        self.calls.append(("send", status))
        return True

    def set_note(self, order_id, note):
        self.calls.append(("note", note))
        return True

    def claim_send(self, order_id):
        if self.send_status != "not_sent":
            return False
        self.send_status = "sending"
        self.calls.append(("claim", order_id))
        return True

    def record_response(self, order_id, mode, paid_rub):
        self.calls.append(("response", mode, paid_rub))


class TestProcessOpenCandidate:
    def test_sends_on_the_same_page_and_records_source(self, monkeypatch):
        import profi.fastpath as fastpath

        page = object()
        ctx = object()
        store = _FakeStore()
        monkeypatch.setattr(
            fastpath,
            "decide_reply",
            lambda *a, **k: Decision("send", "подходит", "Т" * 150, "fallback"),
        )
        opened = []
        monkeypatch.setattr(
            fastpath.respond_mod,
            "_open_respond_form_inner",
            lambda p, mode: opened.append(p) or p,
        )
        monkeypatch.setattr(
            fastpath.respond_mod,
            "fill_form",
            lambda p, rate, text, mode: {"to_pay": 200, "send_button_found": True},
        )
        monkeypatch.setattr(
            fastpath.respond_mod,
            "click_send",
            lambda p, c, rate=None: {"url_after": "https://profi.ru/backoffice/r.php?id=93400001"},
        )
        monkeypatch.setattr(fastpath.respond_mod, "send_failed", lambda outcome: False)
        monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
        monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)
        monkeypatch.setattr(fastpath.config, "MAX_RESPONSE_PRICE_RUB", 500)

        status = process_open_candidate(
            page,
            ctx,
            store,
            "93400001",
            _details(),
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )

        assert status == "sent"
        assert opened == [page]
        assert ("draft", "generated", "Т" * 150, "fallback", None) in store.calls
        assert ("response", "pay", 200) in store.calls

    def test_platform_send_error_is_terminal_failed(self, monkeypatch):
        import profi.fastpath as fastpath

        store = _FakeStore()
        monkeypatch.setattr(
            fastpath,
            "decide_reply",
            lambda *a, **k: Decision("send", "подходит", "Т" * 150, "llm"),
        )
        monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda p, mode: p)
        monkeypatch.setattr(
            fastpath.respond_mod,
            "fill_form",
            lambda *a, **k: {"to_pay": 200, "send_button_found": True},
        )
        monkeypatch.setattr(fastpath.respond_mod, "click_send", lambda *a, **k: {"url_after": ""})
        monkeypatch.setattr(fastpath.respond_mod, "send_failed", lambda outcome: True)
        monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
        monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)

        status = process_open_candidate(
            object(),
            object(),
            store,
            "93400001",
            _details(),
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )
        assert status == "failed"
        assert store.send_status == "failed"
        assert not any(c[0] == "response" for c in store.calls)

    def test_unknown_send_is_terminal_and_never_retried(self, monkeypatch):
        import profi.fastpath as fastpath

        store = _FakeStore()
        monkeypatch.setattr(
            fastpath,
            "decide_reply",
            lambda *a, **k: Decision("send", "подходит", "Т" * 150, "llm"),
        )
        monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda p, mode: p)
        monkeypatch.setattr(fastpath.respond_mod, "fill_form", lambda *a, **k: {"to_pay": 200})
        monkeypatch.setattr(fastpath.respond_mod, "click_send", lambda *a, **k: {"url_after": ""})
        monkeypatch.setattr(fastpath.respond_mod, "send_failed", lambda outcome: False)
        monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
        monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)

        status = process_open_candidate(
            object(),
            object(),
            store,
            "93400001",
            _details(),
            system_prompt_factory=lambda: "system",
            user_prompt="order",
        )
        assert status == "unknown"
        assert store.send_status == "unknown"
        assert any(c[0] == "response" for c in store.calls)
        assert store.claim_send("93400001") is False


class TestWorkerIntegration:
    def test_load_details_fast_path_runs_before_page_close(self, monkeypatch):
        import profi.fastpath as fastpath

        class Page:
            closed = False

            def close(self, **kwargs):
                self.closed = True

        page = Page()
        response = SimpleNamespace(json=lambda: {"ok": True})
        bm = SimpleNamespace(context=lambda: object(), page=object())

        class StoreSpy:
            def __init__(self):
                self.claimed = False

            def update_details_for_fast_path(self, order_id, payload):
                self.claimed = True

            def update_details(self, *args):
                pytest.fail("legacy update_details must not be used by fast-path")

        store = StoreSpy()
        monkeypatch.setattr(main, "human_pause", lambda: None)
        monkeypatch.setattr(main, "open_candidate", lambda ctx, feed, oid: (page, [response]))
        monkeypatch.setattr(main, "extract_dom_texts", lambda p: {"container_text": "dom"})
        monkeypatch.setattr(main, "extract_full_order", lambda payload, dom: _details())
        monkeypatch.setattr(main.time, "sleep", lambda _: None)

        seen = []

        def process(p, ctx, st, oid, details, **kwargs):
            assert p is page
            assert page.closed is False
            assert store.claimed is True
            seen.append(oid)
            return "sent"

        monkeypatch.setattr(fastpath, "process_open_candidate", process)
        assert main.load_details(bm, store, "93400001", fast_path=True) == "DETAILS_READY"
        assert seen == ["93400001"]
        assert page.closed is True

    def test_worker_does_not_sleep_just_because_llm_is_in_cooldown(self, monkeypatch):
        class BM:
            def __init__(self):
                self.started = False

            def start(self):
                self.started = True
                return "READY"

            def shutdown(self):
                pass

            def context(self):
                return object()

        class DummyStore:
            def __init__(self, path):
                pass

            def close(self):
                pass

        bm = BM()
        monkeypatch.setattr(main, "BrowserManager", lambda: bm)
        monkeypatch.setattr(main, "Store", DummyStore)
        monkeypatch.setattr(main, "in_work_hours", lambda: True)
        monkeypatch.setattr(main, "_llm_cooldown_until", lambda: int(time.time()) + 3600)
        monkeypatch.setattr(main, "_send_pause_active", lambda: False)
        monkeypatch.setattr(main, "run_cycle", lambda bm, store: "OK")
        monkeypatch.setattr(main.config, "CHAT_CHECK_EVERY_CYCLES", 999)
        monkeypatch.setattr(
            main.time,
            "sleep",
            lambda seconds: pytest.fail(f"worker unexpectedly slept for {seconds}s"),
        )
        assert main.run_loop(max_cycles=1) == 0
        assert bm.started is True


class TestLegacyAutopilotNoRetry:
    def test_order_open_failure_becomes_terminal(self, tmp_path, monkeypatch):
        db = tmp_path / "autopilot.db"
        store = Store(db)
        try:
            _candidate(store)
            store.update_details("93400001", "ready", json.dumps(_details()))
        finally:
            store.close()

        monkeypatch.setattr(main.config, "FAST_PATH_ENABLED", False)
        monkeypatch.setattr(main.config, "DB_PATH", db)
        monkeypatch.setattr(main.config, "AUTOPILOT_LOCK", tmp_path / "autopilot.lock")
        monkeypatch.setattr(main.config, "AUTOPILOT_LOG", tmp_path / "autopilot.log")
        monkeypatch.setattr(main.config, "DAILY_SEND_LIMIT", 0)
        monkeypatch.setattr(main, "in_work_hours", lambda now=None: True)
        monkeypatch.setattr(main, "_llm_cooldown_until", lambda: 0)
        monkeypatch.setattr(main, "_worker_running", lambda: False)
        monkeypatch.setattr(main, "_worker_pause", lambda on: None)
        monkeypatch.setattr(
            main, "run_respond", lambda *a, **k: (_ for _ in ()).throw(OrderOpenError("boom"))
        )
        monkeypatch.setattr(llm_mod, "status", lambda: {"key_masked": "***"})
        monkeypatch.setattr(llm_mod, "models_chain", lambda: ["fast"])
        monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: "raw")
        monkeypatch.setattr(
            llm_mod,
            "json_reply",
            lambda raw: {
                "verdict": "send",
                "reason": "подходит",
                "text": "Готов помочь с подготовкой к ЕГЭ по информатике. " * 3,
            },
        )
        monkeypatch.setattr(llm_mod, "is_limit_error", lambda e: False)

        assert main.run_autopilot() == 0
        check = Store(db)
        try:
            row = check.get_candidate("93400001")
            assert row["send_status"] == "failed"
            assert row["draft_status"] == "error"
        finally:
            check.close()
