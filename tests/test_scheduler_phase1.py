"""Phase 1 scheduler tests: weekdays + interval triggers + load_entries."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.scheduler import ScheduleEntry, Scheduler


def test_entry_mode_classification():
    assert ScheduleEntry(1, "12:00:00", "stop", repeat_daily=False).mode == "once"
    assert ScheduleEntry(1, "12:00:00", "stop", repeat_daily=True).mode == "daily"
    assert ScheduleEntry(1, "12:00:00", "stop", weekdays={0, 4}).mode == "weekly"
    assert (
        ScheduleEntry(1, "00:00:00", "stop", interval_seconds=900).mode == "interval"
    )


def test_interval_compute_next_advances_from_anchor():
    entry = ScheduleEntry(1, "00:00:00", "stop", interval_seconds=60)
    now = datetime(2025, 1, 1, 12, 0, 0)
    entry.compute_next(now)
    first = entry._next_trigger
    assert first == now + timedelta(seconds=60)

    entry.compute_next(first)
    assert entry._next_trigger == first + timedelta(seconds=60)


def test_weekly_compute_next_picks_next_allowed_weekday():
    now = datetime(2025, 1, 1, 12, 0, 0)  # Wednesday
    # Allowed only Friday (4) and Sunday (6)
    entry = ScheduleEntry(1, "08:00:00", "play_radio", weekdays={4, 6})
    entry.compute_next(now)
    assert entry._next_trigger.weekday() in (4, 6)
    assert entry._next_trigger > now


def test_scheduler_add_and_remove_with_weekdays():
    sched = Scheduler()
    entry = sched.add_entry(
        "10:00:00",
        "play_file",
        target="/tmp/x.mp3",
        weekdays={0, 1, 2},
    )
    assert entry.id == 1
    assert entry.mode == "weekly"
    sched.remove_entry(entry.id)
    assert sched.get_entries() == []


def test_scheduler_load_entries_preserves_ids():
    sched = Scheduler()
    entries = [
        ScheduleEntry(7, "12:00:00", "stop"),
        ScheduleEntry(9, "15:00:00", "play_file", target="/tmp/x.mp3"),
    ]
    sched.load_entries(entries)
    assert {e.id for e in sched.get_entries()} == {7, 9}
    new = sched.add_entry("16:00:00", "stop")
    assert new.id == 10  # max(7, 9) + 1


def test_scheduler_update_entry_changes_mode():
    sched = Scheduler()
    e = sched.add_entry("12:00:00", "stop")
    assert e.mode == "daily"
    sched.update_entry(e.id, interval_seconds=120)
    assert e.mode == "interval"
    sched.update_entry(e.id, interval_seconds=0, weekdays={0, 1})
    assert e.mode == "weekly"


def test_compute_next_default_uses_now():
    entry = ScheduleEntry(1, "00:00:01", "stop")
    entry.compute_next()
    assert entry._next_trigger is not None
    assert entry._next_trigger > datetime.now()
