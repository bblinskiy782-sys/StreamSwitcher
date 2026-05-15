"""
VU Meter widget - stereo level indicator with clip detection.
"""
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class VUMeter(QWidget):
    """
    Stereo VU meter with peak hold and clip indicator.
    Displays dBFS scale from -60 to 0.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(60, 120)
        self.setMaximumWidth(80)

        self._level_l = 0.0
        self._level_r = 0.0
        self._peak_l = 0.0
        self._peak_r = 0.0
        self._clip_l = False
        self._clip_r = False

        # Peak hold timer
        self._peak_timer = QTimer(self)
        self._peak_timer.timeout.connect(self._decay_peaks)
        self._peak_timer.start(50)

        # Clip reset timer
        self._clip_timer = QTimer(self)
        self._clip_timer.timeout.connect(self._reset_clips)
        self._clip_timer.start(2000)

    def set_levels(self, left: float, right: float):
        """Set RMS levels (0.0 - 1.0 linear)."""
        self._level_l = max(0.0, min(1.0, left))
        self._level_r = max(0.0, min(1.0, right))

        if self._level_l > self._peak_l:
            self._peak_l = self._level_l
        if self._level_r > self._peak_r:
            self._peak_r = self._level_r

        if self._level_l >= 0.99:
            self._clip_l = True
        if self._level_r >= 0.99:
            self._clip_r = True

        self.update()

    def _decay_peaks(self):
        self._peak_l = max(0.0, self._peak_l - 0.02)
        self._peak_r = max(0.0, self._peak_r - 0.02)
        self.update()

    def _reset_clips(self):
        self._clip_l = False
        self._clip_r = False
        self.update()

    @staticmethod
    def _linear_to_db(linear: float) -> float:
        if linear <= 0.0:
            return -60.0
        return max(-60.0, 20.0 * math.log10(linear))

    @staticmethod
    def _db_to_fraction(db: float) -> float:
        """Map dBFS (-60..0) to 0..1 for display."""
        return max(0.0, min(1.0, (db + 60.0) / 60.0))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = (w - 12) // 2  # two bars + gap
        gap = 4
        margin_top = 16
        meter_h = h - margin_top - 4

        for ch in range(2):
            x = 4 + ch * (bar_w + gap)
            level = self._level_l if ch == 0 else self._level_r
            peak = self._peak_l if ch == 0 else self._peak_r
            clip = self._clip_l if ch == 0 else self._clip_r

            # Background
            painter.fillRect(x, margin_top, bar_w, meter_h,
                             QColor("#161b22"))

            # Level bar gradient
            db = self._linear_to_db(level)
            frac = self._db_to_fraction(db)
            bar_h = int(meter_h * frac)
            bar_y = margin_top + meter_h - bar_h

            if bar_h > 0:
                grad = QLinearGradient(x, bar_y + bar_h, x, bar_y)
                grad.setColorAt(0.0, QColor("#2ea043"))   # green (low)
                grad.setColorAt(0.7, QColor("#d29922"))   # yellow (mid)
                grad.setColorAt(0.9, QColor("#f85149"))   # red (high)
                painter.fillRect(x, bar_y, bar_w, bar_h, grad)

            # Peak hold line
            peak_db = self._linear_to_db(peak)
            peak_frac = self._db_to_fraction(peak_db)
            peak_y = margin_top + int(meter_h * (1.0 - peak_frac))
            painter.setPen(QPen(QColor("#58a6ff"), 1))
            painter.drawLine(x, peak_y, x + bar_w - 1, peak_y)

            # Clip indicator
            clip_color = QColor("#f85149") if clip else QColor("#3a1a1a")
            painter.fillRect(x, 2, bar_w, margin_top - 4, clip_color)
            painter.setPen(QPen(QColor("#f85149") if clip else QColor("#484f58"), 1))
            painter.drawRect(x, 2, bar_w - 1, margin_top - 5)

            # Channel label
            painter.setPen(QPen(QColor("#8b949e"), 1))
            label = "L" if ch == 0 else "R"
            painter.drawText(x, 2, bar_w, margin_top - 4,
                             Qt.AlignmentFlag.AlignCenter, label)

        # Scale marks
        painter.setPen(QPen(QColor("#484f58"), 1))
        for db_mark in [0, -6, -12, -18, -30, -48]:
            frac = self._db_to_fraction(db_mark)
            y = margin_top + int(meter_h * (1.0 - frac))
            painter.drawLine(w - 8, y, w - 4, y)

        painter.end()
