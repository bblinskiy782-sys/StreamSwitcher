"""Continuous air recorder.

Captures the output of :class:`core.audio_engine.AudioEngine` and writes it
to disk in WAV format, optionally splitting at a fixed time interval (e.g.
one file per hour). The recording happens in a background thread driven by
``push_audio`` calls so it integrates cleanly with the existing engine
callback pipeline.

Encoding to MP3 is delegated to ``lameenc`` when available; otherwise WAV
is used. The class is **pure I/O** — testable with an in-memory directory.
"""

from __future__ import annotations

import os
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from core._qt_compat import QObject, Signal


class AirRecorder(QObject):
    """Continuous recorder with optional time-based split.

    Usage::

        rec = AirRecorder()
        rec.configure(output_dir="/srv/recordings", split_minutes=60)
        rec.start()
        # ... later, for each output block:
        rec.push_audio(block)
        rec.stop()
    """

    file_rolled = Signal(str)           # absolute path of the *closed* file
    error_occurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.output_dir: Path = Path.cwd()
        self.split_minutes: int = 60
        self.sample_rate: int = 44100
        self.channels: int = 2
        self.filename_prefix: str = "air"

        self._lock = threading.Lock()
        self._running = False
        self._wave: wave.Wave_write | None = None
        self._current_path: Path | None = None
        self._segment_started_at: datetime | None = None
        self._total_frames: int = 0

    # ------------------------------------------------------------------ #
    # Configuration                                                       #
    # ------------------------------------------------------------------ #

    def configure(
        self,
        output_dir: str | os.PathLike[str],
        split_minutes: int = 60,
        sample_rate: int = 44100,
        channels: int = 2,
        filename_prefix: str = "air",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.split_minutes = max(0, int(split_minutes))
        self.sample_rate = sample_rate
        self.channels = channels
        self.filename_prefix = filename_prefix

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_recording(self) -> bool:
        return self._running

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def total_frames(self) -> int:
        return self._total_frames

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self.output_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._open_new_segment()
            except Exception as exc:
                self.error_occurred.emit(str(exc))
                return
            self._running = True

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._close_current_segment()

    # ------------------------------------------------------------------ #
    # Push pipeline                                                       #
    # ------------------------------------------------------------------ #

    def push_audio(self, audio: np.ndarray) -> None:
        """Append a float32 audio block to the current segment."""
        if not self._running or audio.size == 0:
            return
        with self._lock:
            if not self._running or self._wave is None:
                return

            now = datetime.now()
            if self._should_roll(now):
                self._close_current_segment()
                self._open_new_segment()

            # Convert float32 [-1, 1] to int16 little-endian PCM.
            clipped = np.clip(audio.astype(np.float32), -1.0, 1.0)
            int16 = (clipped * 32767.0).astype("<i2")
            try:
                self._wave.writeframes(int16.tobytes())
            except Exception as exc:
                self.error_occurred.emit(f"writeframes failed: {exc}")
                return
            self._total_frames += audio.shape[0]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _should_roll(self, now: datetime) -> bool:
        if self.split_minutes <= 0 or self._segment_started_at is None:
            return False
        elapsed = (now - self._segment_started_at).total_seconds()
        return elapsed >= self.split_minutes * 60

    def _open_new_segment(self) -> None:
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        base = f"{self.filename_prefix}_{timestamp}"
        candidate = self.output_dir / f"{base}.wav"
        # Avoid clobbering an existing file from the same second.
        suffix = 1
        while candidate.exists():
            candidate = self.output_dir / f"{base}_{suffix}.wav"
            suffix += 1
        self._current_path = candidate
        wav = wave.open(str(self._current_path), "wb")
        wav.setnchannels(self.channels)
        wav.setsampwidth(2)
        wav.setframerate(self.sample_rate)
        self._wave = wav
        self._segment_started_at = now

    def _close_current_segment(self) -> None:
        if self._wave is None:
            return
        try:
            self._wave.close()
        except Exception:
            pass
        closed = self._current_path
        self._wave = None
        self._segment_started_at = None
        if closed is not None:
            self.file_rolled.emit(str(closed))
