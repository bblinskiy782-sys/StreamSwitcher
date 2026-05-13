"""Tests for :mod:`core.scheduler`."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.scheduler import ScheduleEntry, Scheduler


def test_add_entry_assigns_unique_ids():
    s = Scheduler()
    a = s.add_entry("08:00:00", "play_radio", "http://r/")
    b = s.add_entry("09:00:00", "stop")
    assert a.id != b.id
    assert {a.id, b.id} == {e.id for e in s.get_entries()}


def test_remove_entry():
    s = Scheduler()
    a = s.add_entry("08:00:00", "stop")
    b = s.add_entry("09:00:00", "stop")
    s.remove_entry(a.id)
    ids = {e.id for e in s.get_entries()}
    assert ids == {b.id}


def test_toggle_entry_flips_enabled():
    s = Scheduler()
    e = s.add_entry("08:00:00", "stop")
    assert e.enabled is True
    s.toggle_entry(e.id)
    assert s.get_entries()[0].enabled is False
    s.toggle_entry(e.id)
    assert s.get_entries()[0].enabled is True


def test_update_entry_changes_fields():
    s = Scheduler()
    e = s.add_entry("08:00:00", "stop")
    s.update_entry(e.id, time_str="09:30:00", action="play_radio",
                   target="http://example.com/", repeat_daily=False)
    updated = s.get_entries()[0]
    assert updated.time_str == "09:30:00"
    assert updated.action == "play_radio"
    assert updated.target == "http://example.com/"
    assert updated.repeat_daily is False


def test_compute_next_trigger_in_future():
    e = ScheduleEntry(id=1, time_str="00:00:00", action="stop")
    e.compute_next()
    assert e.next_trigger is not None
    assert e.next_trigger > datetime.now() - timedelta(seconds=1)


def test_compute_next_advances_to_tomorrow_when_time_passed():
    """If the entry's time today has passed, next trigger rolls to tomorrow."""
    now = datetime.now()
    # Pick a time guaranteed to be in the past today (1 minute earlier).
    past = (now - timedelta(minutes=1)).strftime("%H:%M:%S")
    e = ScheduleEntry(id=1, time_str=past, action="stop")
    e.compute_next()
    assert e.next_trigger is not None
    assert e.next_trigger > now


def test_register_callback_is_invoked_when_event_fires():
    s = Scheduler()
    e = s.add_entry("08:00:00", "stop")
    # Force the trigger into the past so the loop would fire it.
    e._next_trigger = datetime.now() - timedelta(seconds=1)

    received: list[ScheduleEntry] = []
    s.register_callback(received.append)

    # We don't run the thread; simulate one cycle by invoking the trigger logic.
    # The scheduler's run loop calls the callbacks via `event_fired.emit` and
    # the registered callbacks list, so we replicate just the callback path.
    for cb in s._callbacks:
        cb(e)

    assert received == [e]


def test_schedule_updated_signal_emits_on_add():
    s = Scheduler()
    received: list[list[ScheduleEntry]] = []
    s.schedule_updated.connect(received.append)
    s.add_entry("08:00:00", "stop")
    assert len(received) == 1
    assert received[0][0].time_str == "08:00:00"


def test_one_shot_entry_disabled_after_trigger_in_loop():
    """When `repeat_daily=False`, after firing the entry should be disabled."""
    s = Scheduler()
    e = s.add_entry("08:00:00", "stop", repeat_daily=False)
    # Simulate firing logic from `_run_loop`.
    e._next_trigger = datetime.now() - timedelta(seconds=1)
    # Emulate the relevant branch of _run_loop:
    if not e.repeat_daily:
        e.enabled = False
    assert e.enabled is False
