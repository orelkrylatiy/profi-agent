#!/usr/bin/env python3
"""Build a privacy-safe dataset for the visual ops/experiment dashboard.

The dashboard file is safe to commit to a public repository: it contains only
aggregate counters, pseudonymous account labels and capability categories. Exact
balances, order ids, client names, message text, raw errors and local paths stay
on the worker machine.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


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

    # A freshly configured account can exist before its env is visible to this
    # process, but a capability file is only created by our own worker. Use it as
    # a conservative fallback and require the sibling DB to exist.
    data_dir = root / "data"
    if data_dir.exists():
        for cap in sorted(data_dir.glob("*.capability.json")):
            stem = cap.name.removesuffix(".capability.json")
            db = data_dir / f"{stem}.db"
            if db.exists() and stem not in found:
                found[stem] = db.resolve()
    return found


def _experiment_rows(db: Path) -> list[dict]:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_prompt_experiments'"
        ).fetchone()
        if not exists:
            return []
        rows = conn.execute(
            "SELECT prompt_experiment, prompt_variant, assigned, evaluated, generated, "
            "fallbacks, sent, replied, send_rate_pct, reply_rate_pct, reply_yield_pct, "
            "avg_reply_min FROM v_prompt_experiments "
            "ORDER BY prompt_experiment, prompt_variant"
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _capability_public(db: Path) -> dict:
    raw = _read_json(db.with_suffix(".capability.json"), {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "status": str(raw.get("status") or "UNKNOWN"),
        "reason": str(raw.get("reason") or "not checked yet")[:160],
        "checked_at": int(raw.get("checked_at") or 0),
        "blocked_until": int(raw.get("blocked_until") or 0),
        "respond_mode": str(raw.get("respond_mode") or "unknown"),
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
        "feed_new_orders": int(events.get("feed_new_orders") or 0),
        "feed_orders_seen": int(events.get("feed_orders_seen") or 0),
        "candidates": int(events.get("candidates_created") or 0),
        "details_ready": int(events.get("details_ready") or 0),
        "drafts_generated": int(events.get("drafts_generated") or 0),
        "sends_started": int(events.get("sends_started") or 0),
        "responses_sent": int(events.get("responses_sent") or 0),
        "responses_unknown": int(events.get("responses_unknown") or 0),
        "responses_failed": int(cohort.get("responses_failed") or 0),
        "responses_skipped": int(cohort.get("responses_skipped") or 0),
        "client_replied": int(cohort.get("client_replied") or 0),
        "availability_incidents": int(runtime.get("availability_incidents") or 0),
    }


def _account_metrics(snapshot: dict, account: str) -> dict:
    metrics = ((snapshot.get("accounts") or {}).get(account)) or {}
    events = metrics.get("events_today") or {}
    cohort = metrics.get("cohort_first_seen_today") or {}
    runtime = metrics.get("runtime") or {}
    inventory = metrics.get("inventory_now") or {}
    return {
        "events": {
            "feed_new_orders": int(events.get("feed_new_orders") or 0),
            "candidates": int(events.get("candidates_created") or 0),
            "details_ready": int(events.get("details_ready") or 0),
            "drafts_generated": int(events.get("drafts_generated") or 0),
            "sends_started": int(events.get("sends_started") or 0),
            "responses_sent": int(events.get("responses_sent") or 0),
        },
        "cohort": {
            "responses_failed": int(cohort.get("responses_failed") or 0),
            "responses_skipped": int(cohort.get("responses_skipped") or 0),
            "client_replied": int(cohort.get("client_replied") or 0),
            "reply_yield_pct": cohort.get("reply_yield_pct"),
        },
        "runtime": {
            "worker_seen_today": bool(runtime.get("worker_seen_today")),
            "supervisor_seen_today": bool(runtime.get("supervisor_seen_today")),
            "last_seen_at": runtime.get("last_seen_at"),
            "availability_incidents": int(runtime.get("availability_incidents") or 0),
            "events": runtime.get("events") or {},
        },
        "inventory": {
            "send_status": inventory.get("send_status") or {},
            "details_errors": int(inventory.get("details_errors") or 0),
            "draft_errors": int(inventory.get("draft_errors") or 0),
        },
    }


def build(root: Path, *, days: int = 30) -> dict:
    latest = _read_json(root / "ops" / "latest.json", {})
    daily_dir = root / "ops" / "daily"
    snapshots: list[dict] = []
    if daily_dir.exists():
        for path in sorted(daily_dir.glob("*.json"))[-max(1, days) :]:
            snap = _read_json(path, {})
            if isinstance(snap, dict) and snap.get("date"):
                snapshots.append(snap)

    accounts = _discover_accounts(root)
    aliases = {name: f"account_{index + 1}" for index, name in enumerate(sorted(accounts))}

    public_accounts = []
    experiments = []
    for name, db in sorted(accounts.items()):
        public_id = aliases[name]
        public_accounts.append(
            {
                "id": public_id,
                "label": f"Аккаунт {public_id.split('_')[-1]}",
                "capability": _capability_public(db),
                "metrics": _account_metrics(latest, name),
            }
        )
        for row in _experiment_rows(db):
            row = dict(row)
            row["account_id"] = public_id
            experiments.append(row)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_date": latest.get("date"),
        "source_code_revision": latest.get("code_revision"),
        "timezone": latest.get("timezone"),
        "totals": latest.get("totals") or {},
        "accounts": public_accounts,
        "history": [_history_row(snapshot) for snapshot in snapshots],
        "experiments": experiments,
        "privacy": {
            "aggregate_only": True,
            "account_aliases_pseudonymized": True,
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
