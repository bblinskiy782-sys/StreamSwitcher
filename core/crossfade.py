"""Crossfade state + helpers used by the source manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from core.dsp import crossfade as dsp_crossfade
from core.dsp import fade_curve

CurveKind = Literal["linear", "equal_power", "exponential"]


@dataclass
class CrossfadeConfig:
    """User-configurable crossfade settings."""

    duration_sec: float = 0.0  # 0 disables crossfade
    curve: CurveKind = "equal_power"
    enabled: bool = True

    def frames_for(self, sample_rate: int) -> int:
        """Number of audio frames the crossfade should span."""
        if not self.enabled or self.duration_sec <= 0:
            return 0
        return max(0, int(self.duration_sec * sample_rate))


def crossfade_blocks(
    out_block: np.ndarray,
    in_block: np.ndarray,
    curve: CurveKind = "equal_power",
) -> np.ndarray:
    """Crossfade two equal-length blocks (out → in)."""
    return dsp_crossfade(out_block, in_block, curve=curve)


def gain_sum_check(curve: CurveKind, n: int = 1024) -> float:
    """Maximum deviation from 1.0 of |fade_in|^2 + |fade_out|^2.

    For ``equal_power`` curves this should be ~0; for ``linear`` and
    ``exponential`` it is non-zero. Useful for diagnostics / tests.
    """
    fi = fade_curve(n, curve=curve, direction="in")
    fo = fade_curve(n, curve=curve, direction="out")
    return float(np.max(np.abs(fi**2 + fo**2 - 1.0)))
