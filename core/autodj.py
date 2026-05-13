"""AutoDJ — rotation rules on top of the existing playlist.

The AutoDJ chooses the *next* track to play based on user-configurable
rules:

* **shuffle**: pick a random track from the pool.
* **repeat**: ``off`` / ``one`` / ``all``.
* **avoid_repeat_minutes**: skip tracks played within the window.
* **insert_jingle_every**: every N music tracks, return a jingle instead.

The class is pure logic: it consumes a list of track paths and a
:class:`core.history.HistoryLog`, and produces the next path to play.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from core.history import HistoryLog


@dataclass
class AutoDJRules:
    enabled: bool = False
    shuffle: bool = False
    repeat: str = "all"               # "off" | "one" | "all"
    avoid_repeat_minutes: int = 30
    insert_jingle_every: int = 0      # 0 => never insert jingles
    jingle_paths: list[str] = field(default_factory=list)


class AutoDJ:
    """Stateful rotation picker.

    The picker is deterministic when ``shuffle=False`` and a fresh
    ``random.Random(seed)`` is supplied; otherwise it uses the module-level
    PRNG.
    """

    def __init__(
        self,
        rules: AutoDJRules | None = None,
        history: HistoryLog | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.rules = rules or AutoDJRules()
        self.history = history or HistoryLog()
        self._rng = rng or random.Random()
        self._cursor = 0
        self._music_count_since_jingle = 0

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def next_track(self, playlist: Sequence[str]) -> str | None:
        """Return the path of the next track, or ``None`` if rotation is empty."""
        if not playlist:
            return None

        if (
            self.rules.insert_jingle_every > 0
            and self.rules.jingle_paths
            and self._music_count_since_jingle >= self.rules.insert_jingle_every
        ):
            self._music_count_since_jingle = 0
            return self._rng.choice(self.rules.jingle_paths)

        track = self._pick(playlist)
        if track is not None:
            self._music_count_since_jingle += 1
        return track

    def reset(self) -> None:
        self._cursor = 0
        self._music_count_since_jingle = 0

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _pick(self, playlist: Sequence[str]) -> str | None:
        candidates = list(playlist)
        if self.rules.avoid_repeat_minutes > 0:
            window = timedelta(minutes=self.rules.avoid_repeat_minutes)
            filtered = [
                p for p in candidates
                if not self.history.played_within(p, window)
            ]
            if filtered:
                candidates = filtered

        if self.rules.repeat == "one":
            return candidates[0] if candidates else None

        if self.rules.shuffle:
            if not candidates:
                return None
            return self._rng.choice(candidates)

        # Sequential rotation. ``_cursor`` indexes the *original* playlist
        # so positions remain stable across calls.
        if self.rules.repeat == "off" and self._cursor >= len(playlist):
            return None

        for _ in range(len(playlist) + 1):
            track = playlist[self._cursor % len(playlist)]
            self._cursor += 1
            if track in candidates:
                return track
        return None
