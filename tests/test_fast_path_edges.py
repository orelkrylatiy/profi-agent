from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import profi.main as main
from profi.fastpath import Decision, normalize_reply_text, process_open_candidate
from profi.profiles import load_profile
from profi.storage import Store


@pytest.fixture(autouse=True)
def _fastpath_inside_work_hours(monkeypatch):
    import profi.fastpath as fastpath

    monkeypatch.setattr(fastpath, "in_work_hours", lambda: True)


ROOT = Path(__file__).resolve().parents[1]


def _details():
    return {
        "id": "93400001",
        "subject": "Информатика",
        "description": "ЕГЭ по информатике",
        "bid_price": 200,
        "competition_position": 2,
        "has_bid": False,
        "card_tags": [],
    }


class _StoreSpy:
    def __init__(self):
        self.status = "not_sent"
        self.calls = []

    def sends_today(self):
        return 0

    def set_draft(self, order_id, status, text=None, source=None, error=None):
        self.calls.append(("draft", status, source))
        return True

    def claim_send(self, order_id):
        if self.status != "not_sent":
            return False
        self.status = "sending"
        return True

    def set_send_status(self, order_id, status):
        self.status = status
        self.calls.append(("send", status))
        return True

    def set_note(self, order_id, note):
        self.calls.append(("note", note))
        return True

    def record_response(self, order_id, mode, paid_rub):
        self.calls.append(("response", mode, paid_rub))


def test_click_exception_is_unknown_and_terminal(monkeypatch):
    import profi.fastpath as fastpath

    store = _StoreSpy()
    monkeypatch.setattr(
        fastpath,
        "decide_reply",
        lambda *a, **k: Decision("send", "подходит", "Т" * 150, "llm"),
    )
    monkeypatch.setattr(fastpath.respond_mod, "_open_respond_form_inner", lambda page, mode: page)
    monkeypatch.setattr(
        fastpath.respond_mod,
        "fill_form",
        lambda *a, **k: {"to_pay": 200, "send_button_found": True},
    )
    monkeypatch.setattr(
        fastpath.respond_mod,
        "click_send",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("connection lost after click")),
    )
    monkeypatch.setattr(fastpath.config, "RESPOND_MODE", "pay")
    monkeypatch.setattr(fastpath.config, "DAILY_SEND_LIMIT", 0)

    result = process_open_candidate(
        object(),
        object(),
        store,
        "93400001",
        _details(),
        system_prompt_factory=lambda: "system",
        user_prompt="order",
    )

    assert result == "unknown"
    assert store.status == "unknown"
    assert ("response", "pay", 200) in store.calls
    assert store.claim_send("93400001") is False


def test_fast_path_default_on_and_explicit_rollback_off():
    env = os.environ.copy()
    env.pop("PROFI_FAST_PATH", None)
    proc = subprocess.run(
        [sys.executable, "-c", "import profi.config as c; print(int(c.FAST_PATH_ENABLED))"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "1"

    env["PROFI_FAST_PATH"] = "0"
    proc = subprocess.run(
        [sys.executable, "-c", "import profi.config as c; print(int(c.FAST_PATH_ENABLED))"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0"


def test_existing_database_migrates_draft_source(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE candidates (
            order_id TEXT PRIMARY KEY,
            first_seen_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source_last_update INTEGER NOT NULL,
            title TEXT,
            snippet_json TEXT,
            triage_reason TEXT,
            priority INTEGER,
            details_status TEXT NOT NULL,
            details_json TEXT,
            details_loaded_at INTEGER,
            draft_status TEXT NOT NULL,
            draft_text TEXT,
            draft_generated_at INTEGER,
            send_status TEXT NOT NULL,
            sent_at INTEGER,
            last_error TEXT,
            respond_mode TEXT,
            paid_rub INTEGER
        );
        """
    )
    conn.commit()
    conn.close()

    store = Store(db)
    try:
        columns = {row[1] for row in store.conn.execute("PRAGMA table_info(candidates)")}
        assert "draft_source" in columns
        view_sql = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name='v_responses'"
        ).fetchone()[0]
        assert "draft_source" in view_sql
    finally:
        store.close()


def test_profile_fallback_templates_pass_runtime_textguard():
    for profile_name in ("info", "languages"):
        profile = load_profile(profile_name, ROOT / "profiles")
        assert profile.fallback_enabled
        assert profile.fallback_templates
        for template in profile.fallback_templates:
            text, reason = normalize_reply_text(template)
            assert reason is None, (profile_name, reason)
            assert text == template


def test_legacy_autopilot_is_noop_when_fast_path_enabled(monkeypatch):
    monkeypatch.setattr(main.config, "FAST_PATH_ENABLED", True)
    monkeypatch.setattr(
        main,
        "_lock_acquire",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not acquire autopilot lock")),
    )
    assert main.run_autopilot() == 0


def test_legacy_autopilot_remains_available_for_rollback(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "FAST_PATH_ENABLED", False)
    monkeypatch.setattr(main.config, "DB_PATH", tmp_path / "empty.db")
    monkeypatch.setattr(main.config, "AUTOPILOT_LOCK", tmp_path / "autopilot.lock")
    monkeypatch.setattr(main, "in_work_hours", lambda now=None: True)
    monkeypatch.setattr(main, "_llm_cooldown_until", lambda: 0)
    assert main.run_autopilot() == 0
