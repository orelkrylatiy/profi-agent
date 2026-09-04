#!/usr/bin/env python3
"""Small local report for outreach prompt A/B/C experiments.

Uses the account DB selected by normal PROFI_* config unless --db is supplied.
No raw order descriptions or client chat text are printed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from profi import config
from profi.storage import Store


def _pct(value) -> str:
    return "-" if value is None else f"{float(value):.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Outreach prompt A/B/C analytics")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB; default PROFI_DB")
    parser.add_argument("--examples", type=int, default=2, help="sent texts to show per variant")
    args = parser.parse_args()

    db_path = args.db or config.DB_PATH
    store = Store(db_path)
    try:
        rows = store.conn.execute(
            "SELECT * FROM v_prompt_experiments ORDER BY prompt_experiment, prompt_variant"
        ).fetchall()
        if not rows:
            print(f"{db_path}: experiment data not collected yet")
            return 0

        print(f"DB: {db_path}")
        print(
            f"{'experiment':<20} {'var':<4} {'assigned':>8} {'eval':>5} {'llm':>5} "
            f"{'fallback':>8} {'sent':>5} {'reply':>5} {'send%':>7} "
            f"{'reply%':>7} {'yield%':>7} {'avg min':>8}"
        )
        for row in rows:
            avg_min = "-" if row["avg_reply_min"] is None else f"{row['avg_reply_min']:.1f}"
            print(
                f"{row['prompt_experiment']:<20} {row['prompt_variant']:<4} "
                f"{row['assigned']:>8} {row['evaluated']:>5} {row['generated']:>5} "
                f"{row['fallbacks']:>8} {row['sent']:>5} {row['replied']:>5} "
                f"{_pct(row['send_rate_pct']):>7} {_pct(row['reply_rate_pct']):>7} "
                f"{_pct(row['reply_yield_pct']):>7} {avg_min:>8}"
            )

        if args.examples > 0:
            print("\nRecent confirmed LLM sends:")
            for row in rows:
                examples = store.conn.execute(
                    "SELECT order_id, first_reply_text FROM candidates "
                    "WHERE prompt_experiment=? AND prompt_variant=? "
                    "AND first_reply_source='llm' AND send_status='sent' "
                    "ORDER BY sent_at DESC LIMIT ?",
                    (row["prompt_experiment"], row["prompt_variant"], args.examples),
                ).fetchall()
                if not examples:
                    continue
                print(f"\n{row['prompt_experiment']} / {row['prompt_variant']}:")
                for example in examples:
                    text = " ".join(str(example["first_reply_text"] or "").split())
                    print(f"  #{example['order_id']}: {text[:360]}")

        print(
            "\nPrimary acquisition metric: client replies / LLM-evaluated candidates (yield%). "
            "send% shows how often the prompt chooses send; reply% is replies / confirmed LLM sends. "
            "Fallback rows are shown separately and excluded from the LLM denominator."
        )
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
