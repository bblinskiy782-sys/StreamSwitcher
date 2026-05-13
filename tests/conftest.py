"""Pytest fixtures shared by the StreamSwitcher test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure the repository root is importable so `import core...` works whether
# pytest is invoked from the repo root or via `pytest tests/`.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def silent_block() -> np.ndarray:
    """1024-frame stereo silence block."""
    return np.zeros((1024, 2), dtype=np.float32)


@pytest.fixture
def sine_block() -> np.ndarray:
    """1024-frame stereo 440 Hz sine at -6 dBFS."""
    sr = 44100
    frames = 1024
    freq = 440.0
    amp = 0.5  # -6 dBFS
    t = np.arange(frames) / sr
    sig = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.column_stack([sig, sig])


@pytest.fixture
def loud_block() -> np.ndarray:
    """A near-clipping block to exercise compressor / limiter."""
    return np.full((1024, 2), 0.95, dtype=np.float32)


@pytest.fixture
def tmp_config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"
