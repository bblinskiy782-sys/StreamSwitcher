"""Pure DSP math.

These functions deliberately have **no I/O and no Qt** dependencies so they
can be unit-tested without an audio device or display.

All functions take and return ``numpy.ndarray`` with shape ``(frames,
channels)`` and dtype ``float32`` (samples are linear, in range -1..1).
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "db_to_linear",
    "linear_to_db",
    "fade_curve",
    "apply_fade",
    "crossfade",
    "apply_peaking_eq",
    "apply_compressor",
    "apply_limiter",
    "rms",
    "peak",
]


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def db_to_linear(db: float) -> float:
    """Convert dB to linear gain (``10 ** (db/20)``)."""
    return float(10.0 ** (db / 20.0))


def linear_to_db(linear: float, floor_db: float = -120.0) -> float:
    """Convert linear gain to dB. Returns ``floor_db`` for non-positive input."""
    if linear <= 0.0:
        return floor_db
    return float(20.0 * math.log10(linear))


def rms(audio: np.ndarray) -> float:
    """RMS of an audio block."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def peak(audio: np.ndarray) -> float:
    """Absolute peak of an audio block."""
    if audio.size == 0:
        return 0.0
    return float(np.max(np.abs(audio)))


# ---------------------------------------------------------------------------
# Fade / crossfade
# ---------------------------------------------------------------------------


def fade_curve(n: int, curve: str = "equal_power", direction: str = "in") -> np.ndarray:
    """Return a 1-D gain curve of length ``n``.

    Parameters
    ----------
    n
        Number of samples in the curve.
    curve
        ``"linear"``, ``"equal_power"`` (cosine), or ``"exponential"``.
    direction
        ``"in"`` (0 → 1) or ``"out"`` (1 → 0).
    """
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    if n == 1:
        return np.array([1.0 if direction == "in" else 0.0], dtype=np.float32)

    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if curve == "linear":
        gain = t
    elif curve == "equal_power":
        gain = np.sin(0.5 * np.pi * t).astype(np.float32)
    elif curve == "exponential":
        # Smooth exponential rise from ~0 to 1.
        gain = (np.expm1(3.0 * t) / np.expm1(3.0)).astype(np.float32)
    else:
        raise ValueError(f"Unknown curve type: {curve!r}")

    if direction == "out":
        gain = gain[::-1].copy()
    elif direction != "in":
        raise ValueError(f"Unknown direction: {direction!r}")

    return gain


def apply_fade(
    audio: np.ndarray,
    n: int | None = None,
    curve: str = "equal_power",
    direction: str = "in",
) -> np.ndarray:
    """Apply a fade-in or fade-out to an audio block.

    If ``n`` is ``None``, the fade spans the entire block.
    """
    if audio.size == 0:
        return audio
    frames = audio.shape[0]
    n = frames if n is None else min(n, frames)
    gain = fade_curve(n, curve=curve, direction=direction)
    out = audio.astype(np.float32, copy=True)
    if audio.ndim == 1:
        out[:n] = out[:n] * gain
    else:
        out[:n, :] = out[:n, :] * gain[:, None]
    return out


def crossfade(
    a: np.ndarray,
    b: np.ndarray,
    curve: str = "equal_power",
) -> np.ndarray:
    """Crossfade between two equal-length audio blocks ``a`` (out) and ``b`` (in).

    Returns ``a * gain_out + b * gain_in`` with appropriate curve.
    """
    if a.shape != b.shape:
        raise ValueError(f"crossfade: shape mismatch {a.shape} vs {b.shape}")
    n = a.shape[0]
    gain_in = fade_curve(n, curve=curve, direction="in")
    gain_out = fade_curve(n, curve=curve, direction="out")
    if a.ndim == 1:
        return (a * gain_out + b * gain_in).astype(np.float32)
    return (a * gain_out[:, None] + b * gain_in[:, None]).astype(np.float32)


# ---------------------------------------------------------------------------
# Peaking EQ
# ---------------------------------------------------------------------------


def apply_peaking_eq(
    audio: np.ndarray,
    sample_rate: int,
    bands: dict[int, float],
    q: float = 1.0,
) -> np.ndarray:
    """Apply a multi-band peaking EQ.

    ``bands`` maps center frequency (Hz) → gain in dB.
    Bands with |gain| < 0.05 dB or frequency above Nyquist are skipped.
    """
    if audio.size == 0 or not bands:
        return audio

    try:
        from scipy.signal import iirpeak, sosfilt, tf2sos
    except ImportError:  # pragma: no cover - scipy is required at runtime
        return audio

    result = audio.astype(np.float32, copy=True)
    nyquist = sample_rate / 2.0

    # Ensure we have a 2-D array for uniform iteration.
    expanded = result.ndim == 1
    if expanded:
        result = result[:, None]

    for freq, gain_db in bands.items():
        if abs(gain_db) < 0.05:
            continue
        if freq <= 0 or freq >= nyquist:
            continue
        w0 = freq / nyquist
        b, a = iirpeak(w0, q)
        sos = tf2sos(b, a)
        gain_linear = db_to_linear(gain_db)
        for ch in range(result.shape[1]):
            filtered = sosfilt(sos, result[:, ch])
            result[:, ch] = result[:, ch] + (filtered - result[:, ch]) * (gain_linear - 1.0)

    if expanded:
        return result[:, 0]
    return result


# ---------------------------------------------------------------------------
# Compressor / limiter
# ---------------------------------------------------------------------------


def apply_compressor(
    audio: np.ndarray,
    threshold_db: float,
    ratio: float,
    makeup_db: float = 0.0,
) -> np.ndarray:
    """Block-RMS feed-forward compressor.

    Same behaviour as the original ``AudioEngine._apply_compressor`` but
    isolated for testability.
    """
    if audio.size == 0:
        return audio
    if ratio <= 1.0:
        return audio * db_to_linear(makeup_db)

    threshold_linear = db_to_linear(threshold_db)
    makeup_linear = db_to_linear(makeup_db)

    result = audio.astype(np.float32, copy=True)
    block_rms = rms(result)
    if block_rms > threshold_linear and block_rms > 0:
        over = block_rms / threshold_linear
        gain_reduction = over ** (1.0 / ratio - 1.0)
        result = result * gain_reduction

    return (result * makeup_linear).astype(np.float32)


def apply_limiter(audio: np.ndarray, ceiling_db: float = -0.3) -> np.ndarray:
    """Simple hard-clip limiter with a configurable ceiling."""
    if audio.size == 0:
        return audio
    ceiling = db_to_linear(ceiling_db)
    return np.clip(audio, -ceiling, ceiling).astype(np.float32)
