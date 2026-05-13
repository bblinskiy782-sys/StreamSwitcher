"""
DSP Panel - Equalizer and Compressor controls.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class EQBandWidget(QWidget):
    """Single EQ band: vertical slider + frequency label."""
    value_changed = Signal(int, float)  # freq, gain_db

    def __init__(self, freq: int, parent=None):
        super().__init__(parent)
        self.freq = freq
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # dB label
        self.db_label = QLabel("0 dB")
        self.db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.db_label.setStyleSheet("color: #58a6ff; font-size: 8pt;")

        # Slider
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(-120, 120)  # -12.0 to +12.0 dB (x10)
        self.slider.setValue(0)
        self.slider.setMinimumHeight(80)
        self.slider.valueChanged.connect(self._on_change)

        # Freq label
        freq_str = f"{freq}Hz" if freq < 1000 else f"{freq//1000}kHz"
        freq_label = QLabel(freq_str)
        freq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        freq_label.setStyleSheet("color: #8b949e; font-size: 8pt;")

        layout.addWidget(self.db_label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(freq_label)

    def _on_change(self, value: int):
        gain_db = value / 10.0
        self.db_label.setText(f"{gain_db:+.1f}")
        self.value_changed.emit(self.freq, gain_db)

    def set_value(self, gain_db: float):
        self.slider.setValue(int(gain_db * 10))


class DSPPanel(QWidget):
    """
    DSP controls: 5-band EQ + Compressor/Limiter.
    """
    eq_changed = Signal(int, float)          # freq, gain_db
    eq_enabled_changed = Signal(bool)
    compressor_changed = Signal(float, float, float)  # threshold, ratio, makeup
    compressor_enabled_changed = Signal(bool)

    EQ_BANDS = [60, 250, 1000, 4000, 12000]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- EQ ----
        eq_group = QGroupBox("Эквалайзер (5-полосный)")
        eq_layout = QVBoxLayout(eq_group)

        self.eq_enable = QCheckBox("Включить EQ")
        self.eq_enable.toggled.connect(self.eq_enabled_changed)
        eq_layout.addWidget(self.eq_enable)

        bands_layout = QHBoxLayout()
        self._eq_bands: dict[int, EQBandWidget] = {}
        for freq in self.EQ_BANDS:
            band = EQBandWidget(freq)
            band.value_changed.connect(self.eq_changed)
            self._eq_bands[freq] = band
            bands_layout.addWidget(band)
        eq_layout.addLayout(bands_layout)
        layout.addWidget(eq_group)

        # ---- Compressor ----
        comp_group = QGroupBox("Компрессор / Лимитер")
        comp_layout = QGridLayout(comp_group)
        comp_layout.setSpacing(8)

        self.comp_enable = QCheckBox("Включить компрессор")
        self.comp_enable.toggled.connect(self.compressor_enabled_changed)
        comp_layout.addWidget(self.comp_enable, 0, 0, 1, 4)

        # Threshold
        comp_layout.addWidget(QLabel("Порог (dBFS):"), 1, 0)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-60.0, 0.0)
        self.threshold_spin.setValue(-18.0)
        self.threshold_spin.setSuffix(" dB")
        self.threshold_spin.setSingleStep(1.0)
        self.threshold_spin.valueChanged.connect(self._on_comp_change)
        comp_layout.addWidget(self.threshold_spin, 1, 1)

        # Ratio
        comp_layout.addWidget(QLabel("Соотношение:"), 1, 2)
        self.ratio_spin = QDoubleSpinBox()
        self.ratio_spin.setRange(1.0, 20.0)
        self.ratio_spin.setValue(4.0)
        self.ratio_spin.setSuffix(":1")
        self.ratio_spin.setSingleStep(0.5)
        self.ratio_spin.valueChanged.connect(self._on_comp_change)
        comp_layout.addWidget(self.ratio_spin, 1, 3)

        # Makeup gain
        comp_layout.addWidget(QLabel("Усиление (dB):"), 2, 0)
        self.makeup_spin = QDoubleSpinBox()
        self.makeup_spin.setRange(0.0, 24.0)
        self.makeup_spin.setValue(6.0)
        self.makeup_spin.setSuffix(" dB")
        self.makeup_spin.setSingleStep(1.0)
        self.makeup_spin.valueChanged.connect(self._on_comp_change)
        comp_layout.addWidget(self.makeup_spin, 2, 1)

        layout.addWidget(comp_group)

    def _on_comp_change(self):
        self.compressor_changed.emit(
            self.threshold_spin.value(),
            self.ratio_spin.value(),
            self.makeup_spin.value(),
        )
