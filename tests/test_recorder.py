"""Tests for the Air Recorder."""

from __future__ import annotations

import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.recorder import AirRecorder


@pytest.fixture
def tmp_output(tmp_path):
    return tmp_path / "rec"


def _silence_block(frames: int = 1024) -> np.ndarray:
    return np.zeros((frames, 2), dtype=np.float32)


def _tone_block(frames: int = 1024, amp: float = 0.5) -> np.ndarray:
    return np.full((frames, 2), amp, dtype=np.float32)


def test_recorder_writes_wav(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0, sample_rate=44100)
    rec.start()
    rec.push_audio(_tone_block(2048))
    rec.stop()

    files = list(tmp_output.glob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0]), "rb") as f:
        assert f.getnchannels() == 2
        assert f.getsampwidth() == 2
        assert f.getframerate() == 44100
        assert f.getnframes() == 2048


def test_recorder_push_before_start_is_noop(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0)
    rec.push_audio(_tone_block())
    assert not list(tmp_output.glob("*.wav"))


def test_recorder_clips_out_of_range_samples(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0)
    rec.start()
    rec.push_audio(np.array([[2.0, -2.0], [0.5, -0.5]], dtype=np.float32))
    rec.stop()

    files = list(tmp_output.glob("*.wav"))
    with wave.open(str(files[0]), "rb") as f:
        frames = f.readframes(2)
    pcm = np.frombuffer(frames, dtype="<i2").reshape(-1, 2)
    # +1.0 -> 32767, -1.0 -> -32767 (since we multiply by 32767 and clip first)
    assert pcm[0, 0] == 32767
    assert pcm[0, 1] == -32767


def test_recorder_split_rolls_file(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=60)
    rec.start()
    rec.push_audio(_tone_block(512))

    # Force the recorder to think one hour has passed.
    rec._segment_started_at = datetime.now() - timedelta(minutes=70)
    rec.push_audio(_tone_block(512))
    rec.stop()

    files = sorted(tmp_output.glob("*.wav"))
    assert len(files) >= 2


def test_recorder_split_disabled(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0)
    rec.start()
    rec._segment_started_at = datetime.now() - timedelta(days=1)
    rec.push_audio(_tone_block(512))
    rec.stop()
    assert len(list(tmp_output.glob("*.wav"))) == 1


def test_recorder_total_frames_counter(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0)
    rec.start()
    rec.push_audio(_tone_block(1000))
    rec.push_audio(_tone_block(2000))
    assert rec.total_frames == 3000
    rec.stop()


def test_recorder_idempotent_start_stop(tmp_output: Path):
    rec = AirRecorder()
    rec.configure(output_dir=tmp_output, split_minutes=0)
    rec.start()
    rec.start()  # no-op
    rec.stop()
    rec.stop()  # no-op
    assert not rec.is_recording
