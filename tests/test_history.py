"""Tests for :mod:`core.history`."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.history import HistoryEntry, HistoryLog


def test_append_and_recent():
    log = HistoryLog()
    log.append(HistoryEntry.now(source="live_input"))
    log.append(HistoryEntry.now(source="mp3_file", track="A.mp3"))
    log.append(HistoryEntry.now(source="mp3_file", track="B.mp3"))
    recent = log.recent(2)
    assert [e.track for e in recent] == ["A.mp3", "B.mp3"]


def test_max_entries_enforced():
    log = HistoryLog(max_entries=3)
    for i in range(10):
        log.append(HistoryEntry.now(source="mp3_file", track=f"t{i}"))
    assert len(log.entries) == 3
    # The oldest entries are discarded.
    assert [e.track for e in log.entries] == ["t7", "t8", "t9"]


def test_get_range_filters_by_timestamp():
    log = HistoryLog()
    base = datetime(2026, 1, 1, 12, 0, 0)
    for i in range(5):
        log.append(
            HistoryEntry(
                timestamp=(base + timedelta(hours=i)).isoformat(timespec="seconds"),
                source="mp3_file",
                track=f"t{i}",
            )
        )
    out = log.get_range(base + timedelta(hours=1), base + timedelta(hours=3))
    assert [e.track for e in out] == ["t1", "t2", "t3"]


def test_played_within_recent():
    log = HistoryLog()
    log.append(HistoryEntry.now(source="mp3_file", track="loop.mp3"))
    assert log.played_within("loop.mp3", timedelta(minutes=5)) is True


def test_played_within_old_record():
    log = HistoryLog()
    very_old = datetime(2000, 1, 1).isoformat(timespec="seconds")
    log.append(HistoryEntry(timestamp=very_old, source="mp3_file", track="old.mp3"))
    assert log.played_within("old.mp3", timedelta(seconds=5)) is False


def test_csv_export(tmp_path):
    log = HistoryLog()
    log.append(HistoryEntry.now(source="mp3_file", track="x.mp3", duration=42.5))
    csv_text = log.to_csv()
    assert "timestamp" in csv_text.splitlines()[0]
    assert "x.mp3" in csv_text
    target = log.export_csv(tmp_path / "history.csv")
    assert target.exists()
    assert "x.mp3" in target.read_text(encoding="utf-8")


def test_clear_resets_log():
    log = HistoryLog()
    log.append(HistoryEntry.now(source="mp3_file", track="x"))
    log.clear()
    assert log.entries == []
