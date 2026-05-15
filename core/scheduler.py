"""Scheduler — time-based source switching and file insertion.

Supports three repeat modes:

* **daily** (default): the entry triggers once a day at ``time_str``.
* **weekly**: triggers on selected days of the week (``weekdays`` set).
* **interval**: triggers every ``interval_seconds`` after start.
* **one-shot**: triggers once at ``time_str``, then disables itself.

All time arithmetic uses the local ``datetime.now()`` for backwards
compatibility with the original implementation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core._qt_compat import QObject, Signal

WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class ScheduleEntry:
    id: int
    time_str: str          # "HH:MM:SS"
    action: str            # "play_file", "play_radio", "switch_live", "stop"
    target: str = ""       # file path or radio URL
    repeat_daily: bool = True
    enabled: bool = True
    # Phase 1 additions:
    weekdays: set[int] = field(default_factory=set)   # 0=Mon..6=Sun; empty => no restriction
    interval_seconds: int = 0                          # >0 => interval mode
    _next_trigger: datetime | None = field(default=None, repr=False)

    @property
    def mode(self) -> str:
        if self.interval_seconds > 0:
            return "interval"
        if self.weekdays:
            return "weekly"
        if self.repeat_daily:
            return "daily"
        return "once"

    def compute_next(self, now: datetime | None = None) -> None:
        """Compute the next trigger time based on the entry's repeat mode."""
        now = now or datetime.now()

        if self.interval_seconds > 0:
            base = self._next_trigger or now
            self._next_trigger = base + timedelta(seconds=self.interval_seconds)
            # If we are catching up after a long pause, snap forward.
            while self._next_trigger <= now:
                self._next_trigger += timedelta(seconds=self.interval_seconds)
            return

        h, m, s = map(int, self.time_str.split(":"))
        candidate = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)

        if self.weekdays:
            # Advance day-by-day until we land on an allowed weekday.
            for _ in range(8):
                if candidate.weekday() in self.weekdays:
                    break
                candidate += timedelta(days=1)
        self._next_trigger = candidate

    @property
    def next_trigger(self) -> datetime | None:
        return self._next_trigger


class Scheduler(QObject):
    """Fires scheduled events at exact HH:MM:SS times."""

    event_fired = Signal(object)      # ScheduleEntry
    schedule_updated = Signal(list)   # list of entries

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[ScheduleEntry] = []
        self._next_id = 1
        self._running = False
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable] = []

    def add_entry(
        self,
        time_str: str,
        action: str,
        target: str = "",
        repeat_daily: bool = True,
        weekdays: set[int] | None = None,
        interval_seconds: int = 0,
    ) -> ScheduleEntry:
        entry = ScheduleEntry(
            id=self._next_id,
            time_str=time_str,
            action=action,
            target=target,
            repeat_daily=repeat_daily,
            weekdays=set(weekdays or ()),
            interval_seconds=interval_seconds,
        )
        entry.compute_next()
        self._next_id += 1
        self._entries.append(entry)
        self.schedule_updated.emit(self._entries.copy())
        return entry

    def remove_entry(self, entry_id: int) -> None:
        self._entries = [e for e in self._entries if e.id != entry_id]
        self.schedule_updated.emit(self._entries.copy())

    def update_entry(
        self,
        entry_id: int,
        time_str: str | None = None,
        action: str | None = None,
        target: str | None = None,
        repeat_daily: bool | None = None,
        weekdays: set[int] | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        for e in self._entries:
            if e.id == entry_id:
                if time_str is not None:
                    e.time_str = time_str
                if action is not None:
                    e.action = action
                if target is not None:
                    e.target = target
                if repeat_daily is not None:
                    e.repeat_daily = repeat_daily
                if weekdays is not None:
                    e.weekdays = set(weekdays)
                if interval_seconds is not None:
                    e.interval_seconds = max(0, int(interval_seconds))
                e.compute_next()
                break
        self.schedule_updated.emit(self._entries.copy())

    def toggle_entry(self, entry_id: int) -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.enabled = not e.enabled
        self.schedule_updated.emit(self._entries.copy())

    def get_entries(self) -> list[ScheduleEntry]:
        return self._entries.copy()

    def load_entries(self, entries: list[ScheduleEntry]) -> None:
        """Replace the schedule with the provided entries.

        Used by :class:`core.config.AppConfig` to restore persisted schedules.
        Existing IDs are preserved but the next-id counter advances past the
        max seen value to avoid collisions on subsequent ``add_entry`` calls.
        """
        self._entries = list(entries)
        if self._entries:
            self._next_id = max(e.id for e in self._entries) + 1
        for e in self._entries:
            if e._next_trigger is None:
                e.compute_next()
        self.schedule_updated.emit(self._entries.copy())

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run_loop(self) -> None:
        while self._running:
            now = datetime.now()
            for entry in self._entries:
                if not entry.enabled:
                    continue
                if entry._next_trigger and now >= entry._next_trigger:
                    self.event_fired.emit(entry)
                    for cb in self._callbacks:
                        try:
                            cb(entry)
                        except Exception:
                            pass
                    if entry.mode in ("daily", "weekly", "interval"):
                        entry.compute_next(now)
                    else:
                        entry.enabled = False
            time.sleep(0.5)

    def register_callback(self, cb: Callable) -> None:
        self._callbacks.append(cb)
