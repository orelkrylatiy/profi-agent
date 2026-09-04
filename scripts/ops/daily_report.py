#!/usr/bin/env python3
"""Build one privacy-safe daily snapshot from local SQLite databases and canonical logs.

Schema v2 deliberately separates three different questions:
- events_today: transitions that happened inside the requested business day;
- inventory_now: current database state, regardless of when rows were created;
- cohort_first_seen_today: eventual outcome of candidates first seen that day.

Only aggregate counters are persisted. Raw log lines, order ids, client names,
chat text, URLs, headers and secrets are never copied into ``ops/``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Yekaterinburg"
INCIDENT_GAP_S = 5 * 60

LOG_EVENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "feed_auth_cooldown": re.compile(r"\bFEED_AUTH_COOLDOWN\b", re.IGNORECASE),
    "feed_ambiguous": re.compile(r"\bFEED_AMBIGUOUS\b", re.IGNORECASE),
    "feed_capture_error": re.compile(r"\bFEED_CAPTURE_ERROR\b", re.IGNORECASE),
    "browser_offline": re.compile(r"\bBROWSER_OFFLINE\b", re.IGNORECASE),
    "auth_required": re.compile(r"\bAUTH_REQUIRED\b", re.IGNORECASE),
    "order_open_fail": re.compile(
        r"\bOPEN_FAIL\b|открытие #[^ ]+ не удалось|не смог открыть #",
        re.IGNORECASE,
    ),
    "llm_limit": re.compile(r"\bLLM_LIMIT\b|LLM на лимите", re.IGNORECASE),
    "commission_exhausted": re.compile(
        r"COMMISSION_EXHAUSTED|комиссия на сегодня исчерпана",
        re.IGNORECASE,
    ),
    "send_fail": re.compile(
        r"\bsend_status=(?:fail|failed)\b|\bSEND_FAILED\b",
        re.IGNORECASE,
    ),
    "send_unknown": re.compile(r"\bsend_status=unknown\b", re.IGNORECASE),
    "database_locked": re.compile(r"database is locked", re.IGNORECASE),
    "traceback": re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
    "tab_hygiene": re.compile(r"гигиена вкладок", re.IGNORECASE),
    "cdp_reconnect": re.compile(r"переподключ", re.IGNORECASE),
    "browser_exit": re.compile(
        r"Chrome завершился|Chromium.*(?:killed|crash|terminated)",
        re.IGNORECASE,
    ),
    "supervisor_start": re.compile(r"\bSUPERVISOR_START\b", re.IGNORECASE),
    "supervisor_duplicate": re.compile(r"\bSUPERVISOR_DUPLICATE\b", re.IGNORECASE),
    "supervisor_error": re.compile(r"\bSUPERVISOR_ERROR\b", re.IGNORECASE),
    "worker_start": re.compile(r"\bWORKER_START\b", re.IGNORECASE),
    "worker_flap_backoff": re.compile(r"\bWORKER_FLAP_BACKOFF\b", re.IGNORECASE),
    "cdp_port_conflict": re.compile(r"\bCDP_PORT_CONFLICT\b", re.IGNORECASE),
    "profile_in_use_no_cdp": re.compile(r"\bPROFILE_IN_USE_NO_CDP\b", re.IGNORECASE),
    "cdp_unhealthy": re.compile(r"\bCDP_UNHEALTHY\b", re.IGNORECASE),
    "browser_start": re.compile(r"\bBROWSER_START\b", re.IGNORECASE),
    "browser_ready": re.compile(r"\bBROWSER_READY\b", re.IGNORECASE),
    "browser_recycle": re.compile(r"\bBROWSER_RECYCLE\b", re.IGNORECASE),
    "browser_start_timeout": re.compile(r"\bBROWSER_START_TIMEOUT\b", re.IGNORECASE),
    "browser_exit_early": re.compile(r"\bBROWSER_EXIT_EARLY\b", re.IGNORECASE),
    "autopilot_start": re.compile(r"\bAUTOPILOT_START\b", re.IGNORECASE),
    "autopilot_stop": re.compile(r"\bAUTOPILOT_STOP\b", re.IGNORECASE),
}

EVENT_GROUP_BY_NAME = {
    **{
        name: "errors"
        for name in (
            "feed_auth_cooldown",
            "feed_ambiguous",
            "feed_capture_error",
            "browser_offline",
            "auth_required",
            "order_open_fail",
            "send_fail",
            "send_unknown",
            "database_locked",
            "traceback",
            "supervisor_error",
            "cdp_port_conflict",
            "profile_in_use_no_cdp",
            "cdp_unhealthy",
            "browser_start_timeout",
            "browser_exit_early",
        )
    },
    **{
        name: "recovery"
        for name in (
            "cdp_reconnect",
            "browser_exit",
            "browser_start",
            "browser_ready",
            "browser_recycle",
            "worker_start",
            "worker_flap_backoff",
        )
    },
    **{
        name: "operational"
        for name in (
            "tab_hygiene",
            "supervisor_start",
            "supervisor_duplicate",
            "autopilot_start",
            "autopilot_stop",
        )
    },
    "llm_limit": "external_limits",
    "commission_exhausted": "external_limits",
}

AVAILABILITY_EVENT_NAMES = {
    "feed_auth_cooldown",
    "feed_ambiguous",
    "feed_capture_error",
    "browser_offline",
    "auth_required",
    "supervisor_error",
    "cdp_port_conflict",
    "profile_in_use_no_cdp",
    "cdp_unhealthy",
    "browser_start_timeout",
    "browser_exit_early",
}

LINE_TS_RE = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
)
LEVEL_RE = re.compile(r"\b(?P<level>CRITICAL|ERROR|WARNING)\b")
CANONICAL_LOG_RE = re.compile(
    r"^(?P<source>worker|browser|autopilot|supervisor)"
    r"(?:-(?P<account>[A-Za-z0-9_.-]+))?\.log$"
)
DIAGNOSTIC_LOG_RE = re.compile(r"^console(?:-[A-Za-z0-9_.-]+)?\.log$")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _resolve_date(spec: str, tz: tzinfo) -> date:
    today = datetime.now(tz).date()
    if spec == "today":
        return today
    if spec == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(spec)


def _window_epoch(target: date, tz: tzinfo) -> tuple[int, int]:
    start = datetime.combine(target, time.min, tzinfo=tz)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def _git_revision(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None


def _discover_databases(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    used_paths: set[Path] = set()

    accounts_dir = root / "accounts"
    if accounts_dir.exists():
        for env_path in sorted(accounts_dir.glob("*.env")):
            account = env_path.stem
            env = _read_env(env_path)
            raw_db = env.get("PROFI_DB")
            db_path = Path(raw_db) if raw_db else root / "data" / f"{account}.db"
            if not db_path.is_absolute():
                db_path = root / db_path
            db_path = db_path.resolve()
            if db_path.exists():
                found[account] = db_path
                used_paths.add(db_path)

    data_dir = root / "data"
    if data_dir.exists():
        for db_path in sorted(data_dir.glob("*.db")):
            resolved = db_path.resolve()
            if resolved in used_paths:
                continue
            key = db_path.stem
            suffix = 2
            while key in found:
                key = f"{db_path.stem}-{suffix}"
                suffix += 1
            found[key] = resolved
            used_paths.add(resolved)
    return found


def _empty_runtime() -> dict:
    return {
        "canonical_log_files": 0,
        "last_seen_at": None,
        "worker_seen_today": False,
        "supervisor_seen_today": False,
        "sources_seen_today": [],
        "events": {},
        "event_groups": {},
        "availability_incidents": 0,
    }


def _empty_metrics() -> dict:
    return {
        "events_today": {
            "feed_new_orders": 0,
            "feed_orders_seen": 0,
            "candidates_created": 0,
            "details_ready": 0,
            "drafts_generated": 0,
            "sends_started": 0,
            "responses_sent": 0,
            "responses_unknown": 0,
            "recorded_paid_rub": 0,
            "missing_payment_records": 0,
            "draft_sources": {},
            "response_modes": {},
            "chat_replies": 0,
            "needs_human": 0,
            "chat_send_failed": 0,
            "injection_guard": 0,
        },
        "inventory_now": {
            "send_status": {},
            "details_errors": 0,
            "draft_errors": 0,
        },
        "cohort_first_seen_today": {
            "candidates": 0,
            "details_ready": 0,
            "drafts_generated": 0,
            "responses_sent": 0,
            "responses_unknown": 0,
            "responses_failed": 0,
            "responses_skipped": 0,
            "client_replied": 0,
            "reply_yield_pct": None,
        },
        "latency_sec": {
            "first_seen_to_details": {"count": 0, "p50": None, "p90": None},
            "first_seen_to_draft": {"count": 0, "p50": None, "p90": None},
            "first_seen_to_sent": {"count": 0, "p50": None, "p90": None},
        },
        "runtime": _empty_runtime(),
        "db_read_error": False,
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _groups(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, int]:
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return {}
    return {str(row[0] if row[0] is not None else "unknown"): int(row[1]) for row in rows}


def _normalize_send_groups(groups: dict[str, int]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for status, count in groups.items():
        result["failed" if status == "fail" else status] += int(count)
    return dict(sorted(result.items()))


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return int(ordered[index])


def _latency_stats(
    conn: sqlite3.Connection,
    start_ts: int,
    end_ts: int,
    end_column: str,
    extra_where: str = "",
) -> dict[str, int | None]:
    try:
        rows = conn.execute(
            f"SELECT {end_column} - first_seen_at FROM candidates "
            f"WHERE first_seen_at>=? AND first_seen_at<? AND {end_column} IS NOT NULL "
            f"AND {end_column}>=first_seen_at {extra_where}",
            (start_ts, end_ts),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    values = [int(row[0]) for row in rows if row[0] is not None]
    return {
        "count": len(values),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    }


def _db_metrics(path: Path, start_ts: int, end_ts: int) -> dict:
    metrics = _empty_metrics()
    events = metrics["events_today"]
    inventory = metrics["inventory_now"]
    cohort = metrics["cohort_first_seen_today"]
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        metrics["db_read_error"] = True
        return metrics

    try:
        if _table_exists(conn, "feed_seen"):
            events["feed_new_orders"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM feed_seen WHERE first_seen_at>=? AND first_seen_at<?",
                (start_ts, end_ts),
            )
            events["feed_orders_seen"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM feed_seen WHERE last_seen_at>=? AND last_seen_at<?",
                (start_ts, end_ts),
            )

        if _table_exists(conn, "candidates"):
            events["candidates_created"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<?",
                (start_ts, end_ts),
            )
            if _column_exists(conn, "candidates", "details_loaded_at"):
                events["details_ready"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE details_loaded_at>=? "
                    "AND details_loaded_at<?",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "draft_generated_at"):
                events["drafts_generated"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE draft_generated_at>=? "
                    "AND draft_generated_at<?",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "send_started_at"):
                events["sends_started"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE send_started_at>=? "
                    "AND send_started_at<?",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "draft_source"):
                events["draft_sources"] = _groups(
                    conn,
                    "SELECT COALESCE(draft_source, 'unknown'), COUNT(*) FROM candidates "
                    "WHERE draft_generated_at>=? AND draft_generated_at<? "
                    "GROUP BY COALESCE(draft_source, 'unknown')",
                    (start_ts, end_ts),
                )

            inventory["send_status"] = _normalize_send_groups(
                _groups(
                    conn,
                    "SELECT send_status, COUNT(*) FROM candidates GROUP BY send_status",
                )
            )
            inventory["details_errors"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE details_status='error'",
            )
            inventory["draft_errors"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE draft_status='error'",
            )

            events["responses_sent"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE send_status='sent' "
                "AND sent_at>=? AND sent_at<?",
                (start_ts, end_ts),
            )
            events["responses_unknown"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE send_status='unknown' "
                "AND sent_at>=? AND sent_at<?",
                (start_ts, end_ts),
            )
            if _column_exists(conn, "candidates", "paid_rub"):
                events["recorded_paid_rub"] = _scalar(
                    conn,
                    "SELECT COALESCE(SUM(paid_rub), 0) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? AND sent_at<?",
                    (start_ts, end_ts),
                )
                events["missing_payment_records"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? "
                    "AND sent_at<? AND paid_rub IS NULL",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "respond_mode"):
                events["response_modes"] = _groups(
                    conn,
                    "SELECT COALESCE(respond_mode, 'unknown'), COUNT(*) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? AND sent_at<? "
                    "GROUP BY COALESCE(respond_mode, 'unknown')",
                    (start_ts, end_ts),
                )

            cohort_params = (start_ts, end_ts)
            cohort["candidates"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<?",
                cohort_params,
            )
            cohort["details_ready"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND details_loaded_at IS NOT NULL",
                cohort_params,
            )
            cohort["drafts_generated"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND draft_generated_at IS NOT NULL",
                cohort_params,
            )
            cohort["responses_sent"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND send_status='sent'",
                cohort_params,
            )
            cohort["responses_unknown"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND send_status='unknown'",
                cohort_params,
            )
            cohort["responses_failed"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND send_status IN ('failed','fail')",
                cohort_params,
            )
            cohort["responses_skipped"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                "AND send_status='skipped'",
                cohort_params,
            )
            if _column_exists(conn, "candidates", "first_client_reply_at"):
                cohort["client_replied"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<? "
                    "AND first_client_reply_at IS NOT NULL",
                    cohort_params,
                )
            if cohort["candidates"]:
                cohort["reply_yield_pct"] = round(
                    100.0 * cohort["client_replied"] / cohort["candidates"],
                    1,
                )

            metrics["latency_sec"]["first_seen_to_details"] = _latency_stats(
                conn, start_ts, end_ts, "details_loaded_at"
            )
            metrics["latency_sec"]["first_seen_to_draft"] = _latency_stats(
                conn, start_ts, end_ts, "draft_generated_at"
            )
            metrics["latency_sec"]["first_seen_to_sent"] = _latency_stats(
                conn,
                start_ts,
                end_ts,
                "sent_at",
                "AND send_status='sent'",
            )

        if _table_exists(conn, "chat_log"):
            params = (start_ts, end_ts)
            events["chat_replies"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='tutor' "
                "AND created_at>=? AND created_at<?",
                params,
            )
            events["needs_human"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='system' "
                "AND text LIKE 'NEEDS_HUMAN:%' AND created_at>=? AND created_at<?",
                params,
            )
            events["chat_send_failed"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='system' "
                "AND text LIKE 'SEND_FAILED:%' AND created_at>=? AND created_at<?",
                params,
            )
            events["injection_guard"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='system' "
                "AND text LIKE 'INJECTION_GUARD:%' AND created_at>=? AND created_at<?",
                params,
            )
    except sqlite3.Error:
        metrics["db_read_error"] = True
    finally:
        conn.close()
    return metrics


def _event_groups(events: dict[str, int] | Counter[str]) -> dict[str, int]:
    groups: Counter[str] = Counter()
    for name, count in events.items():
        group = EVENT_GROUP_BY_NAME.get(name, "other")
        groups[group] += int(count)
    return dict(sorted(groups.items()))


def _incident_count(timestamps: list[datetime]) -> int:
    if not timestamps:
        return 0
    ordered = sorted(timestamps)
    incidents = 1
    previous = ordered[0]
    for current in ordered[1:]:
        if (current - previous).total_seconds() > INCIDENT_GAP_S:
            incidents += 1
        previous = current
    return incidents


def _scan_logs(root: Path, target: date) -> dict:
    log_dir = root / "logs"
    target_s = target.isoformat()
    levels: Counter[str] = Counter()
    events: Counter[str] = Counter()
    by_account: dict[str, Counter[str]] = defaultdict(Counter)
    sources_by_account: dict[str, set[str]] = defaultdict(set)
    files_by_account: Counter[str] = Counter()
    last_seen_by_account: dict[str, datetime] = {}
    incident_times: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    files_scanned = 0
    ignored_diagnostic_files = 0
    ignored_other_log_files = 0
    lines_for_day = 0

    if not log_dir.exists():
        return {
            "files_scanned": 0,
            "ignored_diagnostic_files": 0,
            "ignored_other_log_files": 0,
            "lines_for_day": 0,
            "levels": {},
            "events": {},
            "event_groups": {},
            "availability_incidents": 0,
            "runtime_by_account": {},
        }

    for path in sorted(log_dir.rglob("*.log")):
        match = CANONICAL_LOG_RE.match(path.name)
        if match is None:
            if DIAGNOSTIC_LOG_RE.match(path.name):
                ignored_diagnostic_files += 1
            else:
                ignored_other_log_files += 1
            continue

        files_scanned += 1
        source = match.group("source")
        account = match.group("account") or "global"
        files_by_account[account] += 1
        current_date: str | None = None
        current_ts: datetime | None = None
        try:
            handle = path.open("r", encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                ts_match = LINE_TS_RE.match(line)
                if ts_match:
                    raw_ts = ts_match.group("ts").replace(" ", "T")
                    try:
                        current_ts = datetime.fromisoformat(raw_ts)
                        current_date = current_ts.date().isoformat()
                    except ValueError:
                        current_ts = None
                        current_date = None
                if current_date != target_s:
                    continue

                lines_for_day += 1
                sources_by_account[account].add(source)
                if current_ts is not None:
                    previous = last_seen_by_account.get(account)
                    if previous is None or current_ts > previous:
                        last_seen_by_account[account] = current_ts

                level_match = LEVEL_RE.search(line)
                if level_match:
                    levels[level_match.group("level").lower()] += 1
                for name, pattern in LOG_EVENT_PATTERNS.items():
                    if not pattern.search(line):
                        continue
                    events[name] += 1
                    by_account[account][name] += 1
                    if name in AVAILABILITY_EVENT_NAMES and current_ts is not None:
                        incident_times[(account, name)].append(current_ts)

    incidents_by_account: Counter[str] = Counter()
    for (account, _name), timestamps in incident_times.items():
        incidents_by_account[account] += _incident_count(timestamps)

    runtime_by_account = {}
    for account in sorted(set(files_by_account) | set(by_account) | set(sources_by_account)):
        account_events = dict(sorted(by_account[account].items()))
        sources = sorted(sources_by_account[account])
        last_seen = last_seen_by_account.get(account)
        runtime_by_account[account] = {
            "canonical_log_files": int(files_by_account[account]),
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "worker_seen_today": "worker" in sources,
            "supervisor_seen_today": "supervisor" in sources,
            "sources_seen_today": sources,
            "events": account_events,
            "event_groups": _event_groups(account_events),
            "availability_incidents": int(incidents_by_account[account]),
        }

    return {
        "files_scanned": files_scanned,
        "ignored_diagnostic_files": ignored_diagnostic_files,
        "ignored_other_log_files": ignored_other_log_files,
        "lines_for_day": lines_for_day,
        "levels": dict(sorted(levels.items())),
        "events": dict(sorted(events.items())),
        "event_groups": _event_groups(events),
        "availability_incidents": int(sum(incidents_by_account.values())),
        "runtime_by_account": runtime_by_account,
    }


def _merge_counter_dict(target: Counter[str], values: dict[str, int]) -> None:
    for key, value in values.items():
        target[key] += int(value)


def _merge_totals(accounts: dict[str, dict], logs: dict) -> dict:
    event_numbers: Counter[str] = Counter()
    draft_sources: Counter[str] = Counter()
    response_modes: Counter[str] = Counter()
    inventory_status: Counter[str] = Counter()
    cohort_numbers: Counter[str] = Counter()
    details_errors = 0
    draft_errors = 0
    db_read_errors = 0

    for metrics in accounts.values():
        events = metrics["events_today"]
        for key, value in events.items():
            if key == "draft_sources":
                _merge_counter_dict(draft_sources, value)
            elif key == "response_modes":
                _merge_counter_dict(response_modes, value)
            else:
                event_numbers[key] += int(value)

        inventory = metrics["inventory_now"]
        _merge_counter_dict(inventory_status, inventory["send_status"])
        details_errors += int(inventory["details_errors"])
        draft_errors += int(inventory["draft_errors"])

        cohort = metrics["cohort_first_seen_today"]
        for key, value in cohort.items():
            if key != "reply_yield_pct" and value is not None:
                cohort_numbers[key] += int(value)
        db_read_errors += int(bool(metrics["db_read_error"]))

    cohort_total = dict(sorted(cohort_numbers.items()))
    candidates = cohort_total.get("candidates", 0)
    replied = cohort_total.get("client_replied", 0)
    cohort_total["reply_yield_pct"] = round(100.0 * replied / candidates, 1) if candidates else None

    events_total = dict(sorted(event_numbers.items()))
    events_total["draft_sources"] = dict(sorted(draft_sources.items()))
    events_total["response_modes"] = dict(sorted(response_modes.items()))

    return {
        "events_today": events_total,
        "inventory_now": {
            "send_status": dict(sorted(inventory_status.items())),
            "details_errors": details_errors,
            "draft_errors": draft_errors,
        },
        "cohort_first_seen_today": cohort_total,
        "runtime": {
            "event_groups": logs.get("event_groups", {}),
            "availability_incidents": int(logs.get("availability_incidents", 0)),
        },
        "db_read_errors": db_read_errors,
    }


def build_report(root: Path, target: date, tz: tzinfo) -> dict:
    start_ts, end_ts = _window_epoch(target, tz)
    databases = _discover_databases(root)
    accounts = {account: _db_metrics(path, start_ts, end_ts) for account, path in databases.items()}
    logs = _scan_logs(root, target)

    runtime_by_account = logs.pop("runtime_by_account", {})
    for account, runtime in runtime_by_account.items():
        if account == "global":
            continue
        accounts.setdefault(account, _empty_metrics())
        accounts[account]["runtime"] = runtime

    return {
        "schema_version": 2,
        "date": target.isoformat(),
        "timezone": getattr(tz, "key", str(tz)),
        "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
        "code_revision": _git_revision(root),
        "privacy": {
            "aggregate_only": True,
            "raw_log_lines_included": False,
            "order_ids_included": False,
            "client_names_included": False,
            "chat_text_included": False,
            "urls_included": False,
            "secrets_included": False,
        },
        "totals": _merge_totals(accounts, logs),
        "accounts": accounts,
        "logs": logs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build privacy-safe daily Profi ops snapshot")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: auto-detected)",
    )
    parser.add_argument("--date", default="today", help="today, yesterday or YYYY-MM-DD")
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"IANA timezone (default: {DEFAULT_TIMEZONE})",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        tz: tzinfo = ZoneInfo(args.timezone)
    except Exception:
        if args.timezone == "Asia/Yekaterinburg":
            tz = timezone(timedelta(hours=5), name="Asia/Yekaterinburg")
        else:
            raise
    target = _resolve_date(args.date, tz)
    report = build_report(root, target, tz)

    daily_dir = root / "ops" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    report_path = daily_dir / f"{target.isoformat()}.json"
    latest_path = root / "ops" / "latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    report_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    print(report_path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
