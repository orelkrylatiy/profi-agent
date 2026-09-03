from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _ts(day: str, hour: int) -> int:
    dt = datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(
        tzinfo=ZoneInfo("Asia/Yekaterinburg")
    )
    return int(dt.timestamp())


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE feed_seen (
            order_id TEXT PRIMARY KEY,
            last_update INTEGER NOT NULL,
            first_seen_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL
        );
        CREATE TABLE candidates (
            order_id TEXT PRIMARY KEY,
            first_seen_at INTEGER NOT NULL,
            details_status TEXT NOT NULL,
            details_loaded_at INTEGER,
            draft_status TEXT NOT NULL,
            draft_generated_at INTEGER,
            send_status TEXT NOT NULL,
            sent_at INTEGER,
            paid_rub INTEGER,
            respond_mode TEXT
        );
        CREATE TABLE chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            client_name TEXT,
            sender TEXT NOT NULL,
            text TEXT,
            created_at INTEGER NOT NULL
        );
        """
    )
    current = _ts("2026-09-03", 12)
    old = _ts("2026-09-02", 12)
    conn.execute(
        "INSERT INTO feed_seen VALUES (?, 1, ?, ?)",
        ("93412345", current, current),
    )
    conn.execute(
        "INSERT INTO feed_seen VALUES (?, 1, ?, ?)",
        ("old-order", old, old),
    )
    conn.execute(
        "INSERT INTO candidates VALUES (?, ?, 'ready', ?, 'generated', ?, 'sent', ?, 300, 'pay')",
        ("93412345", current, current, current, current),
    )
    conn.execute(
        "INSERT INTO chat_log (order_id, client_name, sender, text, created_at) "
        "VALUES (?, ?, 'tutor', ?, ?)",
        ("93412345", "Анна", "Секретный текст переписки", current),
    )
    conn.execute(
        "INSERT INTO chat_log (order_id, client_name, sender, text, created_at) "
        "VALUES (?, ?, 'system', 'NEEDS_HUMAN: торг по цене', ?)",
        ("93412345", "Анна", current),
    )
    conn.commit()
    conn.close()


def test_daily_report_is_aggregate_only(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    _make_db(tmp_path / "data" / "info.db")
    (tmp_path / "logs" / "worker-info.log").write_text(
        "2026-09-03 13:00:00 ERROR profi.main: FEED_CAPTURE_ERROR client=Анна "
        "order=93412345 url=https://secret.example/x\n"
        "2026-09-02 13:00:00 ERROR profi.main: OPEN_FAIL old-order\n",
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "ops" / "daily_report.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path),
            "--date",
            "2026-09-03",
            "--timezone",
            "Asia/Yekaterinburg",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    report_path = tmp_path / proc.stdout.strip()
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)

    assert report["totals"]["new_orders"] == 1
    assert report["totals"]["candidates_created"] == 1
    assert report["totals"]["responses_sent"] == 1
    assert report["totals"]["recorded_paid_rub"] == 300
    assert report["totals"]["chat_replies"] == 1
    assert report["totals"]["needs_human"] == 1
    assert report["logs"]["events"] == {"feed_capture_error": 1}
    assert report["logs"]["levels"] == {"error": 1}
    assert report["accounts"]["info"]["log_events"] == {"feed_capture_error": 1}

    # Source data contains all of these, but the tracked report must not.
    assert "Анна" not in report_text
    assert "93412345" not in report_text
    assert "Секретный текст" not in report_text
    assert "secret.example" not in report_text
    assert report["privacy"]["aggregate_only"] is True
