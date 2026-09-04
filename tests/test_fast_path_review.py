from __future__ import annotations

from types import SimpleNamespace

import profi.main as main
from profi.fastpath import decide_reply, full_gate_reason


def _details(**overrides):
    details = {
        "id": "93400001",
        "subject": "Информатика",
        "description": "Подготовка к ЕГЭ",
        "bid_price": 200,
        "competition_position": 3,
        "has_bid": False,
        "card_tags": [],
    }
    details.update(overrides)
    return details


def test_malformed_competition_position_is_fail_open(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath.config, "MAX_COMPETITION_POSITION", 20)
    assert full_gate_reason(_details(competition_position="неизвестно")) is None


def test_non_mapping_llm_result_uses_fallback(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_ENABLED", True)
    monkeypatch.setattr(fastpath.config, "PROFILE_FALLBACK_TEMPLATES", ["Ф" * 150])
    monkeypatch.setattr(fastpath.llm_mod, "status", lambda: {"key_masked": "***"})
    monkeypatch.setattr(fastpath.llm_mod, "models_chain", lambda: ["fast"])
    monkeypatch.setattr(fastpath.llm_mod, "chat", lambda *a, **k: "raw")
    monkeypatch.setattr(fastpath.llm_mod, "json_reply", lambda raw: None)
    monkeypatch.setattr(fastpath.llm_mod, "is_limit_error", lambda exc: False)

    decision = decide_reply(
        _details(),
        "93400001",
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )
    assert decision.action == "send"
    assert decision.source == "fallback"


def test_run_once_is_scan_only_even_when_fast_path_enabled(monkeypatch):
    seen = []

    class BM:
        def start(self):
            return "READY"

        def shutdown(self):
            pass

    class Store:
        def __init__(self, path):
            pass

        def close(self):
            pass

    monkeypatch.setattr(main, "BrowserManager", BM)
    monkeypatch.setattr(main, "Store", Store)
    monkeypatch.setattr(main.config, "FAST_PATH_ENABLED", True)
    monkeypatch.setattr(
        main,
        "run_cycle",
        lambda bm, store, *, fast_path=None: seen.append(fast_path) or "OK",
    )

    assert main.run_once() == 0
    assert seen == [False]


def test_worker_run_cycle_defaults_to_configured_fast_path(monkeypatch):
    class StoreSpy:
        def register_feed_seen(self, order_id, last_update):
            return "NEW"

        def create_candidate(self, snippet, reason, priority):
            pass

    snippet = SimpleNamespace(
        id="93400001",
        last_update=1,
        is_fresh=True,
        title="ЕГЭ по информатике",
        description="Подготовка",
        price_raw="2000 ₽",
        geo_remote="Дистанционно",
        geo_remote_suffix="",
        badges=[],
        raw={},
    )
    snap = SimpleNamespace(snippets=[snippet], total_count=1, server_ts=1)
    bm = SimpleNamespace(page=object(), ensure_ready=lambda: "READY")

    class Capture:
        last_diag = []

        def __init__(self, page):
            pass

        def reload_and_capture(self):
            return snap

    seen = []
    monkeypatch.setattr(main, "FeedCapture", Capture)
    monkeypatch.setattr(main, "hard_filter", lambda s: SimpleNamespace(passed=True, reason="pass"))
    monkeypatch.setattr(main.config, "FAST_PATH_ENABLED", True)
    monkeypatch.setattr(main.config, "AUTO_CREATE_CANDIDATES", True)
    monkeypatch.setattr(main.config, "AUTO_LOAD_DETAILS", True)
    monkeypatch.setattr(
        main,
        "load_details",
        lambda bm, store, oid, *, fast_path=False: seen.append(fast_path) or "DETAILS_READY",
    )

    assert main.run_cycle(bm, StoreSpy()) == "OK"
    assert seen == [True]
