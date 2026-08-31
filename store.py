"""SQLite: техническая память feed_seen + бизнесовая таблица candidates.

Спека: разд. 13 (dedup/idempotency), 17 (candidates), 18 (статусы),
25 (lifecycle). Схема не «богаче» спеки без причины.
"""
from __future__ import annotations

import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_seen (
    order_id       TEXT PRIMARY KEY,
    last_update    INTEGER NOT NULL,
    first_seen_at  INTEGER NOT NULL,
    last_seen_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    order_id               TEXT PRIMARY KEY,
    first_seen_at          INTEGER NOT NULL,
    updated_at             INTEGER NOT NULL,
    source_last_update     INTEGER NOT NULL,

    title                  TEXT,
    snippet_json           TEXT,

    triage_reason          TEXT,
    priority               INTEGER,

    details_status         TEXT NOT NULL,
    details_json           TEXT,
    details_loaded_at      INTEGER,

    draft_status           TEXT NOT NULL,
    draft_text             TEXT,
    draft_generated_at     INTEGER,

    send_status            TEXT NOT NULL,
    sent_at                INTEGER,

    last_error             TEXT
);

-- плоская статистика откликов поверх той же таблицы (вторая БД не нужна)
CREATE VIEW IF NOT EXISTS v_responses AS
SELECT
    order_id,
    title,
    triage_reason                                     AS llm_summary,
    send_status,
    datetime(first_seen_at, 'unixepoch', 'localtime') AS first_seen,
    datetime(sent_at, 'unixepoch', 'localtime')       AS sent_at,
    CAST(json_extract(details_json, '$.bid_price') AS INTEGER) AS bid_price,
    json_extract(details_json, '$.competition_position')       AS position,
    length(draft_text)                                          AS text_len,
    draft_text
FROM candidates;
"""

# feed_seen: NEW / UPDATED / UNCHANGED
# candidates.details_status: pending / ready / error
# candidates.draft_status:   pending / generating / generated / error / stale
# candidates.send_status:    not_sent / sent / unknown; v1-расширение: skipped


class Store:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- feed_seen ---

    def register_feed_seen(self, order_id: str, last_update: int | None) -> str:
        """Фиксирует заказ в feed_seen и возвращает NEW / UPDATED / UNCHANGED."""
        now = int(time.time())
        lu = last_update if last_update is not None else 0
        row = self.conn.execute(
            "SELECT last_update FROM feed_seen WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO feed_seen (order_id, last_update, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?)",
                (order_id, lu, now, now),
            )
            self.conn.commit()
            return "NEW"
        if lu != row["last_update"]:
            self.conn.execute(
                "UPDATE feed_seen SET last_update = ?, last_seen_at = ? WHERE order_id = ?",
                (lu, now, order_id),
            )
            self.conn.commit()
            return "UPDATED"
        self.conn.execute(
            "UPDATE feed_seen SET last_seen_at = ? WHERE order_id = ?", (now, order_id)
        )
        self.conn.commit()
        return "UNCHANGED"

    # --- candidates ---

    def create_candidate(self, snippet, triage_reason: str | None, priority: int | None) -> None:
        now = int(time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO candidates "
            "(order_id, first_seen_at, updated_at, source_last_update, title, snippet_json, "
            " triage_reason, priority, details_status, draft_status, send_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', 'not_sent')",
            (
                snippet.id,
                now,
                now,
                snippet.last_update or 0,
                snippet.title,
                json.dumps(snippet.raw, ensure_ascii=False) if snippet.raw else None,
                triage_reason,
                priority,
            ),
        )
        self.conn.commit()

    def update_details(self, order_id: str, status: str, details_json: str | None) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE candidates SET details_status = ?, details_json = ?, details_loaded_at = ?, "
            "updated_at = ? WHERE order_id = ?",
            (status, details_json, now if status == "ready" else None, now, order_id),
        )
        self.conn.commit()

    def mark_draft_stale(self, order_id: str) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE candidates SET draft_status = 'stale', source_last_update = "
            "(SELECT last_update FROM feed_seen WHERE order_id = candidates.order_id), "
            "updated_at = ? WHERE order_id = ?",
            (now, order_id),
        )
        self.conn.commit()

    def set_send_status(self, order_id: str, status: str) -> bool:
        """Гейт отправки: sent / skipped / unknown. sent и unknown — потраченные
        отправки (unknown тоже списывает дневной лимит — P0-C)."""
        now = int(time.time())
        cur = self.conn.execute(
            "UPDATE candidates SET send_status = ?, "
            "sent_at = CASE WHEN ? IN ('sent','unknown') THEN ? ELSE sent_at END, "
            "updated_at = ? WHERE order_id = ?",
            (status, status, now, now, order_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_note(self, order_id: str, note: str) -> bool:
        """Краткое описание/резон решения от LLM (кладём в triage_reason)."""
        cur = self.conn.execute(
            "UPDATE candidates SET triage_reason = ?, updated_at = ? WHERE order_id = ?",
            (note, int(time.time()), order_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def sends_today(self) -> int:
        """Сколько платных откликов отправлено с начала суток (для DAILY_SEND_LIMIT)."""
        import datetime as _dt

        midnight = int(
            _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        row = self.conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE send_status IN ('sent','unknown') "
            "AND sent_at >= ?",
            (midnight,),
        ).fetchone()
        return int(row[0])

    def ensure_candidate(self, order_id: str, title: str | None) -> None:
        """Минимальная запись кандидата, если её ещё нет (не сбрасывает статусы)."""
        now = int(time.time())
        self.conn.execute(
            "INSERT OR IGNORE INTO candidates "
            "(order_id, first_seen_at, updated_at, source_last_update, title, "
            " details_status, draft_status, send_status) "
            "VALUES (?, ?, ?, 0, ?, 'pending', 'pending', 'not_sent')",
            (order_id, now, now, title),
        )
        self.conn.commit()

    def list_candidates(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT order_id, title, priority, triage_reason, details_status, draft_status, "
            "send_status, updated_at FROM candidates ORDER BY updated_at DESC"
        ).fetchall()

    def get_candidate(self, order_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM candidates WHERE order_id = ?", (order_id,)
        ).fetchone()
