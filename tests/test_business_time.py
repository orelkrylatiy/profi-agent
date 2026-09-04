from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from profi import config
from profi.storage import Store
from profi.utils.workhours import business_now, business_timezone, in_work_hours


def _candidate(store: Store, order_id: str) -> None:
    store.create_candidate(
        SimpleNamespace(id=order_id, last_update=1, title="test", raw={"id": order_id}),
        None,
        None,
    )


def test_yekaterinburg_timezone_has_offline_fixed_offset_fallback(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE_NAME", "Asia/Yekaterinburg")
    tz = business_timezone()
    sample = datetime(2026, 9, 4, 12, 0, tzinfo=tz)
    assert sample.utcoffset().total_seconds() == 5 * 3600


def test_in_work_hours_uses_business_timezone_when_now_is_aware(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE_NAME", "Asia/Yekaterinburg")
    monkeypatch.setattr(config, "WORK_HOURS", (8, 23))
    # 03:30 UTC = 08:30 in Yekaterinburg.
    assert in_work_hours(datetime(2026, 9, 4, 3, 30, tzinfo=timezone.utc)) is True
    # 17:59 UTC = 22:59 local, still inside; 18:00 UTC = 23:00 local, outside.
    assert in_work_hours(datetime(2026, 9, 4, 17, 59, tzinfo=timezone.utc)) is True
    assert in_work_hours(datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)) is False


def test_business_now_converts_aware_timestamp(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE_NAME", "Asia/Yekaterinburg")
    local = business_now(datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc))
    assert (local.hour, local.day) == (1, 5)


def test_sends_today_uses_business_midnight_not_machine_timezone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE_NAME", "Asia/Yekaterinburg")
    store = Store(tmp_path / "time.db")
    try:
        _candidate(store, "before")
        _candidate(store, "inside")
        store.set_send_status("before", "sent")
        store.set_send_status("inside", "sent")

        # Business day 2026-09-05 starts at 2026-09-04 19:00 UTC.
        before = int(datetime(2026, 9, 4, 18, 59, tzinfo=timezone.utc).timestamp())
        inside = int(datetime(2026, 9, 4, 19, 1, tzinfo=timezone.utc).timestamp())
        store.conn.execute("UPDATE candidates SET sent_at=? WHERE order_id='before'", (before,))
        store.conn.execute("UPDATE candidates SET sent_at=? WHERE order_id='inside'", (inside,))
        store.conn.commit()

        now = datetime(2026, 9, 5, 10, 0, tzinfo=business_timezone())
        assert store.sends_today(now=now) == 1
    finally:
        store.close()
