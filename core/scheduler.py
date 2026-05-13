"""
Scheduler - time-based source switching and file insertion.
"""
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, List
from dataclasses import dataclass, field
from PySide6.QtCore import QObject, Signal


@dataclass
class ScheduleEntry:
    id: int
    time_str: str          # "HH:MM:SS"
    action: str            # "play_file", "play_radio", "switch_live", "stop"
    target: str = ""       # file path or radio URL
    repeat_daily: bool = True
    enabled: bool = True
    _next_trigger: Optional[datetime] = field(default=None, repr=False)

    def compute_next(self):
        now = datetime.now()
        h, m, s = map(int, self.time_str.split(":"))
        candidate = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        self._next_trigger = candidate

    @property
    def next_trigger(self) -> Optional[datetime]:
        return self._next_trigger


class Scheduler(QObject):
    """
    Fires scheduled events at exact HH:MM:SS times.
    Supports daily repeat and one-shot entries.
    """
    event_fired = Signal(object)      # ScheduleEntry
    schedule_updated = Signal(list)   # list of entries

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[ScheduleEntry] = []
        self._next_id = 1
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable] = []

    def add_entry(self, time_str: str, action: str,
                  target: str = "", repeat_daily: bool = True) -> ScheduleEntry:
        entry = ScheduleEntry(
            id=self._next_id,
            time_str=time_str,
            action=action,
            target=target,
            repeat_daily=repeat_daily,
        )
        entry.compute_next()
        self._next_id += 1
        self._entries.append(entry)
        self.schedule_updated.emit(self._entries.copy())
        return entry

    def remove_entry(self, entry_id: int):
        self._entries = [e for e in self._entries if e.id != entry_id]
        self.schedule_updated.emit(self._entries.copy())

    def update_entry(self, entry_id: int, time_str: str = None,
                     action: str = None, target: str = None,
                     repeat_daily: bool = None):
        """Edit an existing schedule entry."""
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
                e.compute_next()
                break
        self.schedule_updated.emit(self._entries.copy())

    def toggle_entry(self, entry_id: int):
        for e in self._entries:
            if e.id == entry_id:
                e.enabled = not e.enabled
        self.schedule_updated.emit(self._entries.copy())

    def get_entries(self) -> List[ScheduleEntry]:
        return self._entries.copy()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
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
                    if entry.repeat_daily:
                        entry.compute_next()
                    else:
                        entry.enabled = False
            time.sleep(0.5)

    def register_callback(self, cb: Callable):
        self._callbacks.append(cb)
