from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _ts(day: str, hour: int, minute: int = 0) -> int:
    dt = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(
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
            draft_source TEXT,
            draft_generated_at INTEGER,
            send_status TEXT NOT NULL,
            send_started_at INTEGER,
            sent_at INTEGER,
            first_client_reply_at INTEGER,
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
        ("old-order", old, current),
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "(?, ?, 'ready', ?, 'generated', 'llm', ?, 'sent', ?, ?, ?, 300, 'pay')",
        (
            "93412345",
            current,
            _ts("2026-09-03", 12, 1),
            _ts("2026-09-03", 12, 2),
            _ts("2026-09-03", 12, 3),
            _ts("2026-09-03", 12, 4),
            _ts("2026-09-03", 12, 20),
        ),
    )
    # Created yesterday, but progressed and sent today. It belongs to today's
    # event counters, not to the first-seen-today cohort denominator.
    conn.execute(
        "INSERT INTO candidates VALUES "
        "(?, ?, 'ready', ?, 'generated', 'fallback', ?, 'sent', ?, ?, NULL, 200, 'pay')",
        (
            "old-order",
            old,
            _ts("2026-09-03", 12, 5),
            _ts("2026-09-03", 12, 6),
            _ts("2026-09-03", 12, 7),
            _ts("2026-09-03", 12, 8),
        ),
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


def _run_report(tmp_path: Path) -> tuple[dict, str]:
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
    return json.loads(report_text), report_text


def test_daily_report_v2_separates_events_inventory_and_cohort(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    _make_db(tmp_path / "data" / "info.db")

    report, _ = _run_report(tmp_path)
    info = report["accounts"]["info"]

    assert report["schema_version"] == 2
    assert info["events_today"]["feed_new_orders"] == 1
    assert info["events_today"]["feed_orders_seen"] == 2
    assert info["events_today"]["candidates_created"] == 1
    assert info["events_today"]["details_ready"] == 2
    assert info["events_today"]["drafts_generated"] == 2
    assert info["events_today"]["responses_sent"] == 2
    assert info["events_today"]["recorded_paid_rub"] == 500
    assert info["events_today"]["draft_sources"] == {"fallback": 1, "llm": 1}
    assert info["events_today"]["response_modes"] == {"pay": 2}

    assert info["inventory_now"]["send_status"] == {"sent": 2}
    assert info["inventory_now"]["details_errors"] == 0
    assert info["inventory_now"]["draft_errors"] == 0

    cohort = info["cohort_first_seen_today"]
    assert cohort["candidates"] == 1
    assert cohort["details_ready"] == 1
    assert cohort["drafts_generated"] == 1
    assert cohort["responses_sent"] == 1
    assert cohort["client_replied"] == 1
    assert cohort["reply_yield_pct"] == 100.0

    assert info["latency_sec"]["first_seen_to_details"] == {"count": 1, "p50": 60, "p90": 60}
    assert info["latency_sec"]["first_seen_to_draft"] == {"count": 1, "p50": 120, "p90": 120}
    assert info["latency_sec"]["first_seen_to_sent"] == {"count": 1, "p50": 240, "p90": 240}

    assert report["totals"]["events_today"]["responses_sent"] == 2
    assert report["totals"]["inventory_now"]["send_status"] == {"sent": 2}


def test_daily_report_uses_canonical_logs_and_attributes_supervisor(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    _make_db(tmp_path / "data" / "info.db")

    (tmp_path / "logs" / "worker-info.log").write_text(
        "2026-09-03 13:00:00 ERROR profi.main: FEED_CAPTURE_ERROR client=Анна "
        "order=93412345 url=https://secret.example/x\n"
        "2026-09-02 13:00:00 ERROR profi.main: OPEN_FAIL old-order\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "supervisor-info.log").write_text(
        "2026-09-03 13:01:00 SUPERVISOR_START account=info\n"
        "2026-09-03 13:02:00 WORKER_START account=info\n"
        "2026-09-03 13:03:00 CDP_PORT_CONFLICT port=9223\n"
        "2026-09-03 13:04:00 CDP_PORT_CONFLICT port=9223\n"
        "2026-09-03 13:15:00 CDP_PORT_CONFLICT port=9223\n"
        "2026-09-03 13:16:00 BROWSER_START port=9223\n"
        "2026-09-03 13:17:00 BROWSER_READY pid=1 port=9223\n",
        encoding="utf-8",
    )
    # Console mirrors Python stderr. It must stay diagnostic-only or the same
    # FEED_CAPTURE_ERROR would be counted twice.
    (tmp_path / "logs" / "console-info.log").write_text(
        "2026-09-03 13:00:00 ERROR profi.main: FEED_CAPTURE_ERROR client=Анна "
        "order=93412345 url=https://secret.example/x\n"
        "2026-09-03 13:10:00 Traceback (most recent call last):\n",
        encoding="utf-8",
    )

    report, _ = _run_report(tmp_path)
    runtime = report["accounts"]["info"]["runtime"]

    assert report["logs"]["files_scanned"] == 2
    assert report["logs"]["ignored_diagnostic_files"] == 1
    assert report["logs"]["events"]["feed_capture_error"] == 1
    assert report["logs"]["events"]["cdp_port_conflict"] == 3
    assert "traceback" not in report["logs"]["events"]

    assert runtime["worker_seen_today"] is True
    assert runtime["supervisor_seen_today"] is True
    assert runtime["canonical_log_files"] == 2
    assert runtime["last_seen_at"] == "2026-09-03T13:17:00"
    assert runtime["events"]["worker_start"] == 1
    assert runtime["events"]["browser_start"] == 1
    assert runtime["events"]["browser_ready"] == 1
    assert runtime["events"]["cdp_port_conflict"] == 3
    # 13:03 + 13:04 are one outage; 13:15 is a second one. Together with the
    # independent feed capture outage this makes three availability incidents.
    assert runtime["availability_incidents"] == 3
    assert runtime["event_groups"]["errors"] == 4
    assert runtime["event_groups"]["recovery"] == 3


def test_daily_report_is_aggregate_only(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    _make_db(tmp_path / "data" / "info.db")
    (tmp_path / "logs" / "worker-info.log").write_text(
        "2026-09-03 13:00:00 ERROR profi.main: FEED_CAPTURE_ERROR client=Анна "
        "order=93412345 url=https://secret.example/x\n",
        encoding="utf-8",
    )

    report, report_text = _run_report(tmp_path)

    assert "Анна" not in report_text
    assert "93412345" not in report_text
    assert "Секретный текст" not in report_text
    assert "secret.example" not in report_text
    assert report["privacy"]["aggregate_only"] is True
