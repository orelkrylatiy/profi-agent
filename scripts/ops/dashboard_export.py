#!/usr/bin/env python3
"""Build a privacy-safe dataset for the visual ops/experiment dashboard.

Only explicitly whitelisted aggregates leave the worker machine. Raw account
names are mapped to stable local pseudonyms; exact balances, order ids, client
names, message text, raw errors and local paths are never exported.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

BLOCKING_CAPABILITY_STATUSES = {
    "NO_BALANCE",
    "COMMISSION_UNAVAILABLE",
    "COMMISSION_DAILY_LIMIT",
    "AUTH_REQUIRED",
    "UI_UNKNOWN",
}

PUBLIC_CAPABILITY_REASONS = {
    "UNKNOWN": "возможность отклика ещё не проверена",
    "READY": "форма отклика была доступна при последней проверке",
    "NO_BALANCE": "при последней проверке не хватало баланса",
    "COMMISSION_UNAVAILABLE": "тариф «Комиссия» был недоступен при последней проверке",
    "COMMISSION_DAILY_LIMIT": "дневной лимит тарифа «Комиссия» был исчерпан",
    "AUTH_REQUIRED": "сессии Profi требовалась повторная авторизация",
    "UI_UNKNOWN": "форма отклика не распознана; нужна повторная проверка",
}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


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


def _discover_accounts(root: Path) -> dict[str, Path]:
    """Prefer explicit account envs; never treat arbitrary data/*.db as accounts."""
    found: dict[str, Path] = {}
    accounts_dir = root / "accounts"
    if accounts_dir.exists():
        for env_path in sorted(accounts_dir.glob("*.env")):
            account = env_path.stem
            env = _read_env(env_path)
            raw_db = env.get("PROFI_DB")
            db = Path(raw_db) if raw_db else root / "data" / f"{account}.db"
            if not db.is_absolute():
                db = root / db
            if db.exists():
                found[account] = db.resolve()

    # A capability file is created only by our worker. It is a conservative
    # fallback for an account whose env is temporarily invisible to collector.
    data_dir = root / "data"
    if data_dir.exists():
        for cap in sorted(data_dir.glob("*.capability.json")):
            stem = cap.name.removesuffix(".capability.json")
            db = data_dir / f"{stem}.db"
            if db.exists() and stem not in found:
                found[stem] = db.resolve()
    return found


def _alias_index(alias: object) -> int | None:
    text = str(alias or "")
    if not text.startswith("account_"):
        return None
    try:
        value = int(text.removeprefix("account_"))
    except ValueError:
        return None
    return value if value > 0 else None


def _stable_aliases(root: Path, names: list[str]) -> dict[str, str]:
    """Keep public account aliases stable without committing raw account names."""
    path = root / "data" / "dashboard_aliases.json"
    raw = _read_json(path, {})
    if not isinstance(raw, dict):
        raw = {}

    # Preserve valid aliases for removed accounts as well, so their number is not
    # silently reused if the account returns later.
    used: set[str] = set()
    cleaned: dict[str, str] = {}
    for name, alias in raw.items():
        if isinstance(name, str) and _alias_index(alias) is not None and str(alias) not in used:
            cleaned[name] = str(alias)
            used.add(str(alias))

    next_index = max((_alias_index(alias) or 0 for alias in used), default=0) + 1
    changed = cleaned != raw
    for name in sorted(names):
        if name in cleaned:
            continue
        while f"account_{next_index}" in used:
            next_index += 1
        alias = f"account_{next_index}"
        cleaned[name] = alias
        used.add(alias)
        next_index += 1
        changed = True

    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {name: cleaned[name] for name in names}


def _experiment_rows(db: Path) -> tuple[list[dict], str | None]:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return [], "experiment_db_unreadable"
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_prompt_experiments'"
        ).fetchone()
        if not exists:
            return [], "experiment_view_missing"
        rows = conn.execute(
            "SELECT prompt_experiment, prompt_variant, assigned, evaluated, generated, "
            "fallbacks, sent, replied, send_rate_pct, reply_rate_pct, reply_yield_pct, "
            "avg_reply_min FROM v_prompt_experiments "
            "ORDER BY prompt_experiment, prompt_variant"
        ).fetchall()
        return [dict(row) for row in rows], None
    except sqlite3.Error:
        return [], "experiment_query_failed"
    finally:
        conn.close()


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _capability_public(db: Path, *, now_ts: int) -> dict:
    raw = _read_json(db.with_suffix(".capability.json"), {})
    if not isinstance(raw, dict):
        raw = {}
    status = str(raw.get("status") or "UNKNOWN")
    blocked_until = _int(raw.get("blocked_until"))
    blocking_active = status in BLOCKING_CAPABILITY_STATUSES and blocked_until > now_ts
    probe_due = status in BLOCKING_CAPABILITY_STATUSES and not blocking_active
    return {
        "status": status,
        # Never export an arbitrary persisted reason: future integration errors
        # may contain DOM/client text. Public wording is status-whitelisted.
        "reason": PUBLIC_CAPABILITY_REASONS.get(status, "состояние capability зафиксировано"),
        "checked_at": _int(raw.get("checked_at")),
        "blocked_until": blocked_until,
        "respond_mode": str(raw.get("respond_mode") or "unknown"),
        "blocking_active": blocking_active,
        "probe_due": probe_due,
        # Exact balance/to-pay values intentionally stay local.
        "balance_known": raw.get("balance_rub") is not None,
        "price_known": raw.get("to_pay_rub") is not None,
    }


def _history_row(snapshot: dict) -> dict:
    totals = snapshot.get("totals") or {}
    events = totals.get("events_today") or {}
    cohort = totals.get("cohort_first_seen_today") or {}
    runtime = totals.get("runtime") or {}
    return {
        "date": snapshot.get("date"),
        "feed_new_orders": _int(events.get("feed_new_orders")),
        "feed_orders_seen": _int(events.get("feed_orders_seen")),
        "candidates": _int(events.get("candidates_created")),
        "details_ready": _int(events.get("details_ready")),
        "drafts_generated": _int(events.get("drafts_generated")),
        "sends_started": _int(events.get("sends_started")),
        "responses_sent": _int(events.get("responses_sent")),
        "responses_unknown": _int(events.get("responses_unknown")),
        "responses_failed": _int(cohort.get("responses_failed")),
        "responses_skipped": _int(cohort.get("responses_skipped")),
        "client_replied": _int(cohort.get("client_replied")),
        "availability_incidents": _int(runtime.get("availability_incidents")),
    }


def _account_metrics(snapshot: dict, account: str) -> dict:
    metrics = ((snapshot.get("accounts") or {}).get(account)) or {}
    events = metrics.get("events_today") or {}
    cohort = metrics.get("cohort_first_seen_today") or {}
    runtime = metrics.get("runtime") or {}
    inventory = metrics.get("inventory_now") or {}
    return {
        "events": {
            "feed_new_orders": _int(events.get("feed_new_orders")),
            "candidates": _int(events.get("candidates_created")),
            "details_ready": _int(events.get("details_ready")),
            "drafts_generated": _int(events.get("drafts_generated")),
            "sends_started": _int(events.get("sends_started")),
            "responses_sent": _int(events.get("responses_sent")),
            "responses_unknown": _int(events.get("responses_unknown")),
        },
        # Cohort values must stay separate from event values. The dashboard uses
        # only these fields for conversion/funnel ratios.
        "cohort": {
            "candidates": _int(cohort.get("candidates")),
            "details_ready": _int(cohort.get("details_ready")),
            "drafts_generated": _int(cohort.get("drafts_generated")),
            "responses_sent": _int(cohort.get("responses_sent")),
            "responses_unknown": _int(cohort.get("responses_unknown")),
            "responses_failed": _int(cohort.get("responses_failed")),
            "responses_skipped": _int(cohort.get("responses_skipped")),
            "client_replied": _int(cohort.get("client_replied")),
            "reply_yield_pct": cohort.get("reply_yield_pct"),
        },
        "runtime": {
            "worker_seen_today": bool(runtime.get("worker_seen_today")),
            "supervisor_seen_today": bool(runtime.get("supervisor_seen_today")),
            "last_seen_at": runtime.get("last_seen_at"),
            "availability_incidents": _int(runtime.get("availability_incidents")),
            "events": runtime.get("events") or {},
        },
        "inventory": {
            "send_status": inventory.get("send_status") or {},
            "details_errors": _int(inventory.get("details_errors")),
            "draft_errors": _int(inventory.get("draft_errors")),
        },
    }


def build(root: Path, *, days: int = 30) -> dict:
    now = datetime.now(UTC)
    now_ts = int(now.timestamp())
    warnings: list[str] = []

    raw_latest = _read_json(root / "ops" / "latest.json", {})
    latest = raw_latest if isinstance(raw_latest, dict) and raw_latest.get("schema_version") == 2 else {}
    if not latest:
        warnings.append("latest_snapshot_missing_or_not_v2")

    daily_dir = root / "ops" / "daily"
    v2_snapshots: list[dict] = []
    legacy_history_skipped = 0
    if daily_dir.exists():
        for path in sorted(daily_dir.glob("*.json")):
            snap = _read_json(path, {})
            if not isinstance(snap, dict) or not snap.get("date"):
                continue
            if snap.get("schema_version") != 2:
                legacy_history_skipped += 1
                continue
            v2_snapshots.append(snap)
    snapshots = v2_snapshots[-max(1, days) :]
    if legacy_history_skipped:
        warnings.append(f"legacy_history_skipped:{legacy_history_skipped}")

    accounts = _discover_accounts(root)
    aliases = _stable_aliases(root, list(accounts))

    public_accounts = []
    experiments = []
    latest_accounts = latest.get("accounts") or {}
    for name, db in sorted(accounts.items()):
        public_id = aliases[name]
        if name not in latest_accounts:
            warnings.append(f"{public_id}:metrics_missing_from_latest")
        public_accounts.append(
            {
                "id": public_id,
                "label": f"Аккаунт {public_id.split('_')[-1]}",
                "capability": _capability_public(db, now_ts=now_ts),
                "metrics": _account_metrics(latest, name),
            }
        )
        rows, experiment_error = _experiment_rows(db)
        if experiment_error:
            warnings.append(f"{public_id}:{experiment_error}")
        for row in rows:
            public_row = dict(row)
            public_row["account_id"] = public_id
            experiments.append(public_row)

    return {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "source_date": latest.get("date"),
        "source_generated_at": latest.get("generated_at"),
        "source_code_revision": latest.get("code_revision"),
        "timezone": latest.get("timezone"),
        "experiment_scope": "all_time_current_db",
        "accounts": public_accounts,
        "history": [_history_row(snapshot) for snapshot in snapshots],
        "experiments": experiments,
        "data_quality": {
            "warnings": sorted(set(warnings)),
            "legacy_history_skipped": legacy_history_skipped,
        },
        "privacy": {
            "aggregate_only": True,
            "account_aliases_pseudonymized": True,
            "account_alias_mapping_committed": False,
            "capability_reason_whitelisted": True,
            "balances_included": False,
            "order_ids_included": False,
            "client_names_included": False,
            "message_text_included": False,
            "raw_logs_included": False,
            "secrets_included": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build privacy-safe dashboard JSON")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    root = (args.root or Path(__file__).resolve().parents[2]).resolve()
    output = args.output or root / "ops" / "dashboard.json"
    payload = build(root, days=args.days)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
