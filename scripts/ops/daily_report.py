#!/usr/bin/env python3
"""Build one privacy-safe daily snapshot from local SQLite databases and logs.

Only aggregate counters are persisted. Raw log lines, order ids, client names,
chat text, URLs, headers and secrets are never copied into ``ops/``.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Yekaterinburg"

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
    "send_fail": re.compile(r"\bsend_status=fail\b|\bSEND_FAILED\b", re.IGNORECASE),
    "send_unknown": re.compile(r"\bsend_status=unknown\b", re.IGNORECASE),
    "database_locked": re.compile(r"database is locked", re.IGNORECASE),
    "traceback": re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
    "tab_hygiene": re.compile(r"гигиена вкладок", re.IGNORECASE),
    "cdp_reconnect": re.compile(r"переподключ", re.IGNORECASE),
    "browser_exit": re.compile(
        r"Chrome завершился|Chromium.*(?:killed|crash|terminated)",
        re.IGNORECASE,
    ),
}

LINE_DATE_RE = re.compile(r"^\[?(?P<date>\d{4}-\d{2}-\d{2})[ T]")
LEVEL_RE = re.compile(r"\b(?P<level>CRITICAL|ERROR|WARNING)\b")
ACCOUNT_LOG_RE = re.compile(
    r"^(?:worker|browser|autopilot)-(?P<account>[A-Za-z0-9_.-]+)\.log$"
)


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


def _resolve_date(spec: str, tz: ZoneInfo) -> date:
    today = datetime.now(tz).date()
    if spec == "today":
        return today
    if spec == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(spec)


def _window_epoch(target: date, tz: ZoneInfo) -> tuple[int, int]:
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


def _empty_metrics() -> dict:
    return {
        "feed": {"new_orders": 0, "orders_seen": 0},
        "candidates": {
            "created": 0,
            "details_ready": 0,
            "drafts_generated": 0,
            "current_send_status": {},
            "current_details_errors": 0,
            "current_draft_errors": 0,
        },
        "responses": {
            "sent": 0,
            "unknown": 0,
            "recorded_paid_rub": 0,
            "missing_payment_records": 0,
            "modes": {},
        },
        "chat": {
            "tutor_replies": 0,
            "needs_human": 0,
            "send_failed": 0,
            "injection_guard": 0,
        },
        "log_events": {},
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
    return {
        str(row[0] if row[0] is not None else "unknown"): int(row[1])
        for row in rows
    }


def _db_metrics(path: Path, start_ts: int, end_ts: int) -> dict:
    metrics = _empty_metrics()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        metrics["db_read_error"] = True
        return metrics

    try:
        if _table_exists(conn, "feed_seen"):
            metrics["feed"]["new_orders"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM feed_seen WHERE first_seen_at>=? AND first_seen_at<?",
                (start_ts, end_ts),
            )
            metrics["feed"]["orders_seen"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM feed_seen WHERE last_seen_at>=? AND last_seen_at<?",
                (start_ts, end_ts),
            )

        if _table_exists(conn, "candidates"):
            metrics["candidates"]["created"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE first_seen_at>=? AND first_seen_at<?",
                (start_ts, end_ts),
            )
            if _column_exists(conn, "candidates", "details_loaded_at"):
                metrics["candidates"]["details_ready"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE details_status='ready' "
                    "AND details_loaded_at>=? AND details_loaded_at<?",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "draft_generated_at"):
                metrics["candidates"]["drafts_generated"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates WHERE draft_generated_at>=? "
                    "AND draft_generated_at<?",
                    (start_ts, end_ts),
                )

            metrics["candidates"]["current_send_status"] = _groups(
                conn,
                "SELECT send_status, COUNT(*) FROM candidates GROUP BY send_status",
            )
            metrics["candidates"]["current_details_errors"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE details_status='error'",
            )
            metrics["candidates"]["current_draft_errors"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE draft_status='error'",
            )
            metrics["responses"]["sent"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE send_status='sent' "
                "AND sent_at>=? AND sent_at<?",
                (start_ts, end_ts),
            )
            metrics["responses"]["unknown"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM candidates WHERE send_status='unknown' "
                "AND sent_at>=? AND sent_at<?",
                (start_ts, end_ts),
            )

            if _column_exists(conn, "candidates", "paid_rub"):
                metrics["responses"]["recorded_paid_rub"] = _scalar(
                    conn,
                    "SELECT COALESCE(SUM(paid_rub), 0) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? AND sent_at<?",
                    (start_ts, end_ts),
                )
                metrics["responses"]["missing_payment_records"] = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? "
                    "AND sent_at<? AND paid_rub IS NULL",
                    (start_ts, end_ts),
                )
            if _column_exists(conn, "candidates", "respond_mode"):
                metrics["responses"]["modes"] = _groups(
                    conn,
                    "SELECT COALESCE(respond_mode, 'unknown'), COUNT(*) FROM candidates "
                    "WHERE send_status IN ('sent','unknown') AND sent_at>=? AND sent_at<? "
                    "GROUP BY COALESCE(respond_mode, 'unknown')",
                    (start_ts, end_ts),
                )

        if _table_exists(conn, "chat_log"):
            params = (start_ts, end_ts)
            metrics["chat"]["tutor_replies"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='tutor' "
                "AND created_at>=? AND created_at<?",
                params,
            )
            metrics["chat"]["needs_human"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='system' "
                "AND text LIKE 'NEEDS_HUMAN:%' AND created_at>=? AND created_at<?",
                params,
            )
            metrics["chat"]["send_failed"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM chat_log WHERE sender='system' "
                "AND text LIKE 'SEND_FAILED:%' AND created_at>=? AND created_at<?",
                params,
            )
            metrics["chat"]["injection_guard"] = _scalar(
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


def _log_account(path: Path) -> str:
    match = ACCOUNT_LOG_RE.match(path.name)
    return match.group("account") if match else "global"


def _scan_logs(root: Path, target: date) -> dict:
    log_dir = root / "logs"
    target_s = target.isoformat()
    levels: Counter[str] = Counter()
    events: Counter[str] = Counter()
    by_account: dict[str, Counter[str]] = defaultdict(Counter)
    files_scanned = 0
    lines_for_day = 0

    if not log_dir.exists():
        return {
            "files_scanned": 0,
            "lines_for_day": 0,
            "levels": {},
            "events": {},
            "events_by_account": {},
        }

    for path in sorted(log_dir.rglob("*.log")):
        files_scanned += 1
        current_date: str | None = None
        account = _log_account(path)
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                match = LINE_DATE_RE.match(line)
                if match:
                    current_date = match.group("date")
                if current_date != target_s:
                    continue
                lines_for_day += 1
                level_match = LEVEL_RE.search(line)
                if level_match:
                    levels[level_match.group("level").lower()] += 1
                for name, pattern in LOG_EVENT_PATTERNS.items():
                    if pattern.search(line):
                        events[name] += 1
                        by_account[account][name] += 1

    return {
        "files_scanned": files_scanned,
        "lines_for_day": lines_for_day,
        "levels": dict(sorted(levels.items())),
        "events": dict(sorted(events.items())),
        "events_by_account": {
            account: dict(sorted(counter.items()))
            for account, counter in sorted(by_account.items())
        },
    }


def _merge_totals(accounts: dict[str, dict], logs: dict) -> dict:
    totals = {
        "new_orders": 0,
        "candidates_created": 0,
        "responses_sent": 0,
        "responses_unknown": 0,
        "recorded_paid_rub": 0,
        "chat_replies": 0,
        "needs_human": 0,
        "technical_error_events": 0,
    }
    for metrics in accounts.values():
        totals["new_orders"] += metrics["feed"]["new_orders"]
        totals["candidates_created"] += metrics["candidates"]["created"]
        totals["responses_sent"] += metrics["responses"]["sent"]
        totals["responses_unknown"] += metrics["responses"]["unknown"]
        totals["recorded_paid_rub"] += metrics["responses"]["recorded_paid_rub"]
        totals["chat_replies"] += metrics["chat"]["tutor_replies"]
        totals["needs_human"] += metrics["chat"]["needs_human"]
    totals["technical_error_events"] = sum(logs.get("events", {}).values())
    return totals


def build_report(root: Path, target: date, tz: ZoneInfo) -> dict:
    start_ts, end_ts = _window_epoch(target, tz)
    databases = _discover_databases(root)
    accounts = {
        account: _db_metrics(path, start_ts, end_ts)
        for account, path in databases.items()
    }
    logs = _scan_logs(root, target)

    per_account_log_events = logs.pop("events_by_account", {})
    for account, counters in per_account_log_events.items():
        if account == "global":
            continue
        accounts.setdefault(account, _empty_metrics())
        accounts[account]["log_events"] = counters

    return {
        "schema_version": 1,
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
    parser = argparse.ArgumentParser(
        description="Build privacy-safe daily Profi ops snapshot"
    )
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
        tz = ZoneInfo(args.timezone)
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
