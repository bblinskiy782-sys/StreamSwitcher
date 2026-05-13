"""
Waveform Widget - mini-player waveform visualization.
Shows the waveform of the loaded MP3 file with playback position.
"""
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QBrush


class WaveformWidget(QWidget):
    """
    Displays audio waveform with playback cursor.
    Click to seek.
    """
    seek_requested = Signal(float)  # 0.0 - 1.0 position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._waveform: np.ndarray = np.array([])
        self._position = 0.0   # 0.0 - 1.0
        self._duration = 0.0

    def set_waveform(self, data: np.ndarray):
        """Set waveform data (array of peak values 0..1)."""
        self._waveform = np.asarray(data, dtype=np.float32)
        self.update()

    def set_position(self, position: float, duration: float):
        """Update playback position."""
        if duration > 0:
            self._position = position / duration
        else:
            self._position = 0.0
        self._duration = duration
        self.update()

    def clear(self):
        self._waveform = np.array([])
        self._position = 0.0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and len(self._waveform) > 0:
            frac = event.position().x() / self.width()
            self.seek_requested.emit(max(0.0, min(1.0, frac)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        mid = h // 2

        # Background
        painter.fillRect(0, 0, w, h, QColor("#0d1117"))

        if len(self._waveform) == 0:
            # Empty state
            painter.setPen(QPen(QColor("#21262d"), 1))
            painter.drawLine(0, mid, w, mid)
            painter.setPen(QPen(QColor("#484f58"), 1))
            painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter,
                             "No waveform loaded")
            painter.end()
            return

        # Resample waveform to widget width
        n = len(self._waveform)
        indices = np.linspace(0, n - 1, w).astype(int)
        samples = self._waveform[indices]

        cursor_x = int(self._position * w)

        # Draw waveform bars
        for x in range(w):
            amp = float(samples[x])
            bar_h = max(1, int(amp * (h // 2 - 2)))

            if x < cursor_x:
                # Played portion - bright
                color = QColor("#1f6feb")
            else:
                # Unplayed - dim
                color = QColor("#21262d")

            painter.setPen(QPen(color, 1))
            painter.drawLine(x, mid - bar_h, x, mid + bar_h)

        # Cursor line
        painter.setPen(QPen(QColor("#58a6ff"), 2))
        painter.drawLine(cursor_x, 0, cursor_x, h)

        # Border
        painter.setPen(QPen(QColor("#21262d"), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        painter.end()
