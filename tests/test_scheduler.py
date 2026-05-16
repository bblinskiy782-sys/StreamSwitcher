import pytest
from datetime import datetime, timedelta
from core.scheduler import Scheduler, ScheduleEntry
from PySide6.QtCore import QCoreApplication

@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app

@pytest.fixture
def scheduler(qapp):
    return Scheduler()

def test_add_entry(scheduler):
    entry = scheduler.add_entry("12:00:00", "play_file", "test.mp3")
    assert entry.id == 1
    assert entry.time_str == "12:00:00"
    assert entry.action == "play_file"
    assert entry.target == "test.mp3"
    assert entry.enabled is True

    entries = scheduler.get_entries()
    assert len(entries) == 1

def test_compute_next():
    # If time is in the past today, it should schedule for tomorrow
    now = datetime.now()
    past_time = now - timedelta(hours=1)
    time_str = past_time.strftime("%H:%M:%S")

    entry = ScheduleEntry(1, time_str, "stop")
    entry.compute_next()

    assert entry.next_trigger > now
    assert entry.next_trigger.date() == (now + timedelta(days=1)).date()

def test_remove_entry(scheduler):
    scheduler.add_entry("10:00:00", "stop")
    scheduler.add_entry("11:00:00", "play_radio")

    entries = scheduler.get_entries()
    assert len(entries) == 2

    scheduler.remove_entry(entries[0].id)
    assert len(scheduler.get_entries()) == 1
    assert scheduler.get_entries()[0].action == "play_radio"

def test_toggle_entry(scheduler):
    entry = scheduler.add_entry("10:00:00", "stop")
    assert entry.enabled is True

    scheduler.toggle_entry(entry.id)
    entries = scheduler.get_entries()
    assert entries[0].enabled is False
