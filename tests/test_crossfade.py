"""Tests for :mod:`core.crossfade`."""

from __future__ import annotations

import numpy as np
import pytest

from core import crossfade


def test_default_config_disabled_when_zero_duration():
    cfg = crossfade.CrossfadeConfig(duration_sec=0.0)
    assert cfg.frames_for(44100) == 0


def test_frames_for_typical():
    cfg = crossfade.CrossfadeConfig(duration_sec=3.0)
    assert cfg.frames_for(44100) == 44100 * 3


def test_frames_disabled_when_flag_off():
    cfg = crossfade.CrossfadeConfig(duration_sec=2.0, enabled=False)
    assert cfg.frames_for(44100) == 0


def test_equal_power_constant_power_invariant():
    deviation = crossfade.gain_sum_check("equal_power", n=1024)
    assert deviation == pytest.approx(0.0, abs=1e-6)


def test_linear_is_not_constant_power():
    # Linear crossfade has a 3 dB dip — definitely non-zero deviation.
    deviation = crossfade.gain_sum_check("linear", n=1024)
    assert deviation > 0.1


def test_crossfade_blocks_basic():
    a = np.ones((512, 2), dtype=np.float32)
    b = np.zeros((512, 2), dtype=np.float32)
    out = crossfade.crossfade_blocks(a, b, curve="linear")
    assert out.shape == (512, 2)
    assert out[0].max() == pytest.approx(1.0, abs=1e-3)
    assert out[-1].max() == pytest.approx(0.0, abs=1e-3)
