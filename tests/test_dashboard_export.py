from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _make_experiment_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE candidates (
            prompt_experiment TEXT,
            prompt_variant TEXT,
            draft_source TEXT,
            first_reply_source TEXT,
            first_reply_text TEXT,
            send_status TEXT,
            first_client_reply_at INTEGER,
            sent_at INTEGER
        );
        CREATE VIEW v_prompt_experiments AS
        SELECT
            prompt_experiment,
            prompt_variant,
            COUNT(*) AS assigned,
            SUM(CASE WHEN draft_source='llm' THEN 1 ELSE 0 END) AS evaluated,
            SUM(CASE WHEN first_reply_source='llm' AND first_reply_text IS NOT NULL THEN 1 ELSE 0 END)
                AS generated,
            SUM(CASE WHEN first_reply_source='fallback' AND first_reply_text IS NOT NULL THEN 1 ELSE 0 END)
                AS fallbacks,
            SUM(CASE WHEN draft_source='llm' AND send_status='sent' THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN draft_source='llm' AND send_status='sent' AND first_client_reply_at IS NOT NULL THEN 1 ELSE 0 END)
                AS replied,
            50.0 AS send_rate_pct,
            50.0 AS reply_rate_pct,
            25.0 AS reply_yield_pct,
            12.0 AS avg_reply_min
        FROM candidates
        GROUP BY prompt_experiment, prompt_variant;
        """
    )
    conn.execute(
        "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("offer-v1", "A", "llm", "llm", "private reply text", "sent", 200, 100),
    )
    conn.commit()
    conn.close()


def _snapshot(date: str) -> dict:
    return {
        "schema_version": 2,
        "date": date,
        "code_revision": "abc123",
        "timezone": "Asia/Yekaterinburg",
        "accounts": {
            "info": {
                "events_today": {
                    "feed_new_orders": 10,
                    "candidates_created": 4,
                    "details_ready": 3,
                    "drafts_generated": 2,
                    "sends_started": 2,
                    "responses_sent": 1,
                },
                "cohort_first_seen_today": {
                    "responses_failed": 1,
                    "responses_skipped": 2,
                    "client_replied": 1,
                    "reply_yield_pct": 25.0,
                },
                "runtime": {
                    "worker_seen_today": True,
                    "supervisor_seen_today": False,
                    "last_seen_at": "2026-09-12T10:00:00",
                    "availability_incidents": 2,
                    "events": {"feed_capture_error": 3},
                },
                "inventory_now": {
                    "send_status": {"sent": 1, "failed": 1},
                    "details_errors": 1,
                    "draft_errors": 1,
                },
            },
            "phantom": {
                "events_today": {"feed_new_orders": 999},
            },
        },
        "totals": {
            "events_today": {
                "feed_new_orders": 10,
                "feed_orders_seen": 12,
                "candidates_created": 4,
                "details_ready": 3,
                "drafts_generated": 2,
                "sends_started": 2,
                "responses_sent": 1,
                "responses_unknown": 0,
            },
            "cohort_first_seen_today": {
                "responses_failed": 1,
                "responses_skipped": 2,
                "client_replied": 1,
            },
            "runtime": {"availability_incidents": 2},
        },
    }


def test_dashboard_export_is_pseudonymous_and_aggregate_only(tmp_path):
    root = tmp_path
    (root / "accounts").mkdir()
    (root / "ops" / "daily").mkdir(parents=True)
    (root / "accounts" / "info.env").write_text("PROFI_DB=data/info.db\n", encoding="utf-8")
    _make_experiment_db(root / "data" / "info.db")
    _make_experiment_db(root / "data" / "phantom.db")

    capability = {
        "status": "NO_BALANCE",
        "reason": "balance is below the response price",
        "checked_at": 100,
        "blocked_until": 200,
        "respond_mode": "pay",
        "balance_rub": 0,
        "to_pay_rub": 250,
    }
    (root / "data" / "info.capability.json").write_text(
        json.dumps(capability), encoding="utf-8"
    )

    snapshot = _snapshot("2026-09-12")
    (root / "ops" / "latest.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (root / "ops" / "daily" / "2026-09-12.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )

    output = root / "ops" / "dashboard.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "dashboard_export.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(output) in proc.stdout

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [account["id"] for account in payload["accounts"]] == ["account_1"]
    assert payload["accounts"][0]["label"] == "Аккаунт 1"
    assert payload["accounts"][0]["capability"]["status"] == "NO_BALANCE"
    assert payload["accounts"][0]["capability"]["balance_known"] is True
    assert "balance_rub" not in payload["accounts"][0]["capability"]
    assert "to_pay_rub" not in payload["accounts"][0]["capability"]
    assert payload["accounts"][0]["metrics"]["events"]["feed_new_orders"] == 10

    assert len(payload["experiments"]) == 1
    assert payload["experiments"][0]["account_id"] == "account_1"
    assert "private reply text" not in json.dumps(payload, ensure_ascii=False)
    assert "info" not in json.dumps(payload["accounts"], ensure_ascii=False)
    assert "phantom" not in json.dumps(payload, ensure_ascii=False)


def test_dashboard_history_uses_daily_aggregate_snapshots(tmp_path):
    root = tmp_path
    (root / "ops" / "daily").mkdir(parents=True)
    first = _snapshot("2026-09-11")
    second = _snapshot("2026-09-12")
    second["totals"]["events_today"]["responses_sent"] = 7
    (root / "ops" / "latest.json").write_text(json.dumps(second), encoding="utf-8")
    (root / "ops" / "daily" / "2026-09-11.json").write_text(
        json.dumps(first), encoding="utf-8"
    )
    (root / "ops" / "daily" / "2026-09-12.json").write_text(
        json.dumps(second), encoding="utf-8"
    )

    output = root / "ops" / "dashboard.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "dashboard_export.py"
    subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--output", str(output)],
        check=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [row["date"] for row in payload["history"]] == ["2026-09-11", "2026-09-12"]
    assert payload["history"][1]["responses_sent"] == 7
