"""Tests for pure DSP math in :mod:`core.dsp`."""

from __future__ import annotations

import numpy as np
import pytest

from core import dsp

# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_db_round_trip():
    for db in (-60.0, -12.0, -6.0, 0.0, 6.0, 12.0):
        assert dsp.linear_to_db(dsp.db_to_linear(db)) == pytest.approx(db, abs=1e-6)


def test_db_floor():
    assert dsp.linear_to_db(0.0) == -120.0
    assert dsp.linear_to_db(-0.1) == -120.0


def test_rms_silent(silent_block):
    assert dsp.rms(silent_block) == 0.0


def test_rms_sine(sine_block):
    # A sine at amplitude 0.5 has RMS ≈ 0.5/sqrt(2). The fixture only
    # covers ~10 periods so allow a small tolerance for windowing error.
    expected = 0.5 / np.sqrt(2.0)
    assert dsp.rms(sine_block) == pytest.approx(expected, rel=5e-3)


def test_peak(loud_block):
    assert dsp.peak(loud_block) == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Fade
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("curve", ["linear", "equal_power", "exponential"])
def test_fade_in_endpoints(curve):
    g = dsp.fade_curve(256, curve=curve, direction="in")
    assert g.shape == (256,)
    assert g[0] == pytest.approx(0.0, abs=1e-3)
    assert g[-1] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("curve", ["linear", "equal_power", "exponential"])
def test_fade_out_endpoints(curve):
    g = dsp.fade_curve(256, curve=curve, direction="out")
    assert g[0] == pytest.approx(1.0, abs=1e-3)
    assert g[-1] == pytest.approx(0.0, abs=1e-3)


def test_fade_curve_invalid_curve():
    with pytest.raises(ValueError):
        dsp.fade_curve(100, curve="bogus")


def test_fade_curve_invalid_direction():
    with pytest.raises(ValueError):
        dsp.fade_curve(100, direction="sideways")


def test_fade_curve_zero_length():
    g = dsp.fade_curve(0)
    assert g.shape == (0,)


def test_fade_curve_monotonic_linear():
    g = dsp.fade_curve(1024, curve="linear", direction="in")
    assert np.all(np.diff(g) >= 0)


def test_apply_fade_in(sine_block):
    out = dsp.apply_fade(sine_block, curve="linear", direction="in")
    # First sample silenced, last sample preserved.
    assert np.abs(out[0]).max() == 0.0
    assert np.abs(out[-1]).max() == pytest.approx(np.abs(sine_block[-1]).max(), rel=1e-3)


def test_apply_fade_partial(sine_block):
    # Fade only over the first 128 frames; the rest should be untouched.
    out = dsp.apply_fade(sine_block, n=128, direction="in", curve="linear")
    np.testing.assert_array_equal(out[128:], sine_block[128:])


# ---------------------------------------------------------------------------
# Crossfade
# ---------------------------------------------------------------------------


def test_crossfade_endpoints(silent_block):
    ones = np.ones_like(silent_block)
    out = dsp.crossfade(ones, silent_block, curve="linear")
    # At start: 1 (only a). At end: 0 (only b which is silent).
    assert np.abs(out[0]).max() == pytest.approx(1.0, abs=1e-3)
    assert np.abs(out[-1]).max() == pytest.approx(0.0, abs=1e-3)


def test_crossfade_shape_mismatch():
    a = np.zeros((100, 2), dtype=np.float32)
    b = np.zeros((50, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        dsp.crossfade(a, b)


def test_crossfade_equal_power_constant_power():
    """Sum of squared gains should stay close to 1 across the crossfade."""
    a = np.ones((1024, 1), dtype=np.float32)
    b = np.ones((1024, 1), dtype=np.float32)
    out = dsp.crossfade(a, b, curve="equal_power")
    # Since both signals are 1.0, the output should be ~ sin(theta) + cos(theta)
    # which is ~1.414 at the midpoint and 1.0 at the edges — the *squared sum*
    # of gains is constant at 1.0.
    g_in = dsp.fade_curve(1024, curve="equal_power", direction="in")
    g_out = dsp.fade_curve(1024, curve="equal_power", direction="out")
    np.testing.assert_allclose(g_in**2 + g_out**2, np.ones(1024), atol=1e-6)
    # And the output equals the explicit mix.
    expected = (a[:, 0] * g_out) + (b[:, 0] * g_in)
    np.testing.assert_allclose(out[:, 0], expected, atol=1e-6)


# ---------------------------------------------------------------------------
# Compressor / limiter
# ---------------------------------------------------------------------------


def test_compressor_below_threshold(silent_block):
    # Silence below threshold: only makeup gain is applied (here +0).
    out = dsp.apply_compressor(silent_block, threshold_db=-18.0, ratio=4.0)
    np.testing.assert_array_equal(out, silent_block)


def test_compressor_reduces_loud_block(loud_block):
    out = dsp.apply_compressor(
        loud_block, threshold_db=-12.0, ratio=4.0, makeup_db=0.0
    )
    assert dsp.peak(out) < dsp.peak(loud_block)


def test_compressor_ratio_1_passes_through(sine_block):
    out = dsp.apply_compressor(sine_block, threshold_db=-30.0, ratio=1.0, makeup_db=0.0)
    np.testing.assert_allclose(out, sine_block, atol=1e-6)


def test_limiter_clips_to_ceiling(loud_block):
    out = dsp.apply_limiter(loud_block, ceiling_db=-6.0)
    ceiling = dsp.db_to_linear(-6.0)
    assert dsp.peak(out) <= ceiling + 1e-6


def test_limiter_does_not_amplify(silent_block):
    out = dsp.apply_limiter(silent_block, ceiling_db=-0.3)
    np.testing.assert_array_equal(out, silent_block)


# ---------------------------------------------------------------------------
# EQ
# ---------------------------------------------------------------------------


def test_eq_zero_bands_passthrough(sine_block):
    out = dsp.apply_peaking_eq(sine_block, 44100, bands={1000: 0.0, 4000: 0.0})
    np.testing.assert_allclose(out, sine_block, atol=1e-6)


def test_eq_above_nyquist_ignored(sine_block):
    out = dsp.apply_peaking_eq(sine_block, 44100, bands={50000: 6.0})
    np.testing.assert_allclose(out, sine_block, atol=1e-6)


def test_eq_changes_signal(sine_block):
    boosted = dsp.apply_peaking_eq(sine_block, 44100, bands={440: 6.0}, q=1.0)
    # Boosting the fundamental of the sine should change the signal noticeably.
    assert not np.allclose(boosted, sine_block, atol=1e-3)
