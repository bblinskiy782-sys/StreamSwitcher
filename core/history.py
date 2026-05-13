"""Play history log.

Records what played, when, and for how long. Supports CSV export for
broadcaster reporting / Royalties.
"""

from __future__ import annotations

import csv
import io
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class HistoryEntry:
    timestamp: str            # ISO 8601 string
    source: str               # "live_input" | "mp3_file" | "internet_radio"
    track: str = ""           # track name / URL / "live"
    duration: float = 0.0     # seconds actually played
    listeners: int = 0        # snapshot at the time of the entry

    @classmethod
    def now(cls, source: str, **kwargs: object) -> HistoryEntry:
        return cls(timestamp=datetime.utcnow().isoformat(timespec="seconds"),
                   source=source, **kwargs)  # type: ignore[arg-type]


@dataclass
class HistoryLog:
    """Bounded, thread-safe history."""

    max_entries: int = 1000
    entries: list[HistoryEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def append(self, entry: HistoryEntry) -> None:
        with self._lock:
            self.entries.append(entry)
            overflow = len(self.entries) - self.max_entries
            if overflow > 0:
                del self.entries[:overflow]

    def recent(self, n: int = 50) -> list[HistoryEntry]:
        with self._lock:
            return list(self.entries[-n:])

    def get_range(self, start: datetime, end: datetime) -> list[HistoryEntry]:
        with self._lock:
            out = []
            for e in self.entries:
                try:
                    ts = datetime.fromisoformat(e.timestamp)
                except ValueError:
                    continue
                if start <= ts <= end:
                    out.append(e)
            return out

    def last_played_at(self, track: str) -> datetime | None:
        """Most recent timestamp at which ``track`` started playing, or None."""
        with self._lock:
            for e in reversed(self.entries):
                if e.track == track:
                    try:
                        return datetime.fromisoformat(e.timestamp)
                    except ValueError:
                        return None
        return None

    def played_within(self, track: str, window: timedelta) -> bool:
        """True if ``track`` was played within ``window``."""
        last = self.last_played_at(track)
        if last is None:
            return False
        return (datetime.utcnow() - last) < window

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["timestamp", "source", "track", "duration", "listeners"]
        )
        writer.writeheader()
        with self._lock:
            for e in self.entries:
                writer.writerow(asdict(e))
        return buf.getvalue()

    def export_csv(self, path: Path | str) -> Path:
        out = Path(path)
        out.write_text(self.to_csv(), encoding="utf-8")
        return out

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()
