"""Tests for AutoDJ rotation logic."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from core.autodj import AutoDJ, AutoDJRules
from core.history import HistoryEntry, HistoryLog


@pytest.fixture
def history() -> HistoryLog:
    return HistoryLog()


def _make(rules: AutoDJRules, history: HistoryLog | None = None, seed: int = 0) -> AutoDJ:
    return AutoDJ(rules=rules, history=history or HistoryLog(), rng=random.Random(seed))


def test_empty_playlist_returns_none():
    dj = _make(AutoDJRules())
    assert dj.next_track([]) is None


def test_sequential_rotation_wraps_around():
    dj = _make(AutoDJRules(repeat="all"))
    playlist = ["a.mp3", "b.mp3", "c.mp3"]
    chosen = [dj.next_track(playlist) for _ in range(6)]
    assert chosen == ["a.mp3", "b.mp3", "c.mp3", "a.mp3", "b.mp3", "c.mp3"]


def test_sequential_no_repeat_stops_at_end():
    dj = _make(AutoDJRules(repeat="off"))
    playlist = ["a.mp3", "b.mp3"]
    chosen = [dj.next_track(playlist) for _ in range(4)]
    assert chosen[:2] == ["a.mp3", "b.mp3"]
    assert chosen[2] is None
    assert chosen[3] is None


def test_shuffle_uses_rng():
    dj = _make(AutoDJRules(shuffle=True), seed=42)
    playlist = ["a.mp3", "b.mp3", "c.mp3"]
    chosen = {dj.next_track(playlist) for _ in range(30)}
    assert chosen == set(playlist)


def test_repeat_one_returns_same_track():
    dj = _make(AutoDJRules(repeat="one"))
    playlist = ["a.mp3", "b.mp3"]
    assert dj.next_track(playlist) == "a.mp3"
    assert dj.next_track(playlist) == "a.mp3"


def test_avoid_repeat_minutes_skips_recent_tracks(history: HistoryLog):
    rules = AutoDJRules(avoid_repeat_minutes=30, shuffle=True)
    history.append(
        HistoryEntry(
            timestamp=(datetime.now() - timedelta(minutes=5)).isoformat(),
            source="mp3_file",
            track="a.mp3",
        )
    )
    dj = _make(rules, history=history, seed=1)
    playlist = ["a.mp3", "b.mp3", "c.mp3"]
    picks = {dj.next_track(playlist) for _ in range(20)}
    assert "a.mp3" not in picks
    assert picks <= {"b.mp3", "c.mp3"}


def test_avoid_repeat_falls_back_when_no_candidates(history: HistoryLog):
    rules = AutoDJRules(avoid_repeat_minutes=30, shuffle=True)
    for path in ("a.mp3", "b.mp3"):
        history.append(
            HistoryEntry(
                timestamp=(datetime.now() - timedelta(minutes=1)).isoformat(),
                source="mp3_file",
                track=path,
            )
        )
    dj = _make(rules, history=history, seed=2)
    picked = dj.next_track(["a.mp3", "b.mp3"])
    assert picked in ("a.mp3", "b.mp3")


def test_jingle_insertion_every_n_tracks():
    rules = AutoDJRules(insert_jingle_every=3, jingle_paths=["jingle.mp3"])
    dj = _make(rules)
    playlist = ["a.mp3", "b.mp3", "c.mp3", "d.mp3"]
    seq = [dj.next_track(playlist) for _ in range(7)]
    # After 3 music tracks the jingle must appear.
    assert seq[3] == "jingle.mp3"
    assert seq[0] != "jingle.mp3"


def test_reset_restarts_cursor():
    dj = _make(AutoDJRules(repeat="all"))
    playlist = ["a", "b", "c"]
    dj.next_track(playlist)
    dj.next_track(playlist)
    dj.reset()
    assert dj.next_track(playlist) == "a"
