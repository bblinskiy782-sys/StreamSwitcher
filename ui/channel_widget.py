"""Channel widget — compact UI for one independent audio channel.

Each channel shows:
* Source selector (Live / MP3 / Radio)
* Input / Output device combos
* VU meter
* Volume slider
* Stream on/off + listener count
* Current track label

Multiple of these are stacked in a QTabWidget in the main window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.audio_engine import AudioEngine, AudioSource
from core.channel import Channel, ChannelConfig
from ui.vu_meter import VUMeter


class ChannelWidget(QWidget):
    """Compact control surface for one :class:`Channel`."""

    remove_requested = Signal()   # user wants to delete this channel

    def __init__(self, channel: Channel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.channel = channel
        self._streaming = False
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # --- Devices ---
        dev_group = QGroupBox("Устройства")
        dev_layout = QVBoxLayout(dev_group)

        dev_layout.addWidget(QLabel("Вход (основной):"))
        self.input_combo = QComboBox()
        dev_layout.addWidget(self.input_combo)

        dev_layout.addWidget(QLabel("Выход (основной):"))
        self.output_combo = QComboBox()
        dev_layout.addWidget(self.output_combo)

        dev_layout.addWidget(QLabel("Монитор / PFL (наушники):"))
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItem("— Не используется —", None)
        dev_layout.addWidget(self.monitor_combo)

        dev_layout.addWidget(QLabel("AUX 1:"))
        self.aux1_combo = QComboBox()
        self.aux1_combo.addItem("— Не используется —", None)
        dev_layout.addWidget(self.aux1_combo)

        dev_layout.addWidget(QLabel("AUX 2:"))
        self.aux2_combo = QComboBox()
        self.aux2_combo.addItem("— Не используется —", None)
        dev_layout.addWidget(self.aux2_combo)

        root.addWidget(dev_group)

        # --- Source ---
        src_group = QGroupBox("Источник")
        src_layout = QHBoxLayout(src_group)

        self.btn_live = QPushButton("🎤 Live")
        self.btn_live.setCheckable(True)
        self.btn_live.setChecked(True)
        self.btn_live.clicked.connect(
            lambda: self._switch_source(AudioSource.LIVE_INPUT))
        src_layout.addWidget(self.btn_live)

        self.btn_mp3 = QPushButton("🎵 MP3")
        self.btn_mp3.setCheckable(True)
        self.btn_mp3.clicked.connect(
            lambda: self._switch_source(AudioSource.MP3_FILE))
        src_layout.addWidget(self.btn_mp3)

        self.btn_radio = QPushButton("📻 Radio")
        self.btn_radio.setCheckable(True)
        self.btn_radio.clicked.connect(
            lambda: self._switch_source(AudioSource.INTERNET_RADIO))
        src_layout.addWidget(self.btn_radio)

        root.addWidget(src_group)

        # --- Track / URL ---
        self.track_label = QLabel("—")
        self.track_label.setStyleSheet("color: #58a6ff; font-size: 9pt;")
        self.track_label.setWordWrap(True)
        root.addWidget(self.track_label)

        # --- VU + Volume ---
        vu_row = QHBoxLayout()
        self.vu = VUMeter()
        self.vu.setFixedWidth(30)
        vu_row.addWidget(self.vu)

        vol_col = QVBoxLayout()
        vol_col.addWidget(QLabel("🔊"))
        self.vol_slider = QSlider(Qt.Orientation.Vertical)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.valueChanged.connect(
            lambda v: self.channel.engine.set_volume(v / 100.0))
        vol_col.addWidget(self.vol_slider)
        self.vol_label = QLabel("80%")
        self.vol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vol_slider.valueChanged.connect(
            lambda v: self.vol_label.setText(f"{v}%"))
        vol_col.addWidget(self.vol_label)
        vu_row.addLayout(vol_col)
        root.addLayout(vu_row)

        # --- Streaming ---
        stream_group = QGroupBox("Вещание")
        stream_layout = QVBoxLayout(stream_group)

        self.stream_status = QLabel("● Офлайн")
        self.stream_status.setStyleSheet("color: #f85149; font-weight: bold;")
        stream_layout.addWidget(self.stream_status)

        self.listeners_label = QLabel("Слушателей: 0")
        self.listeners_label.setStyleSheet("color: #a371f7;")
        stream_layout.addWidget(self.listeners_label)

        self.stream_btn = QPushButton("🔴 Начать")
        self.stream_btn.clicked.connect(self._toggle_stream)
        stream_layout.addWidget(self.stream_btn)

        root.addWidget(stream_group)

        # --- Remove button ---
        self.remove_btn = QPushButton("✖ Удалить канал")
        self.remove_btn.setStyleSheet("color: #f85149;")
        self.remove_btn.clicked.connect(self.remove_requested.emit)
        root.addWidget(self.remove_btn)

        root.addStretch()

    # ------------------------------------------------------------------ #
    #  Signals                                                             #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        self.channel.level_updated.connect(self.vu.set_levels)
        self.channel.source_changed.connect(self._on_source_changed)
        self.channel.track_changed.connect(
            lambda t: self.track_label.setText(t or "—"))
        self.channel.stream_connected.connect(
            lambda: self._set_stream_status(True))
        self.channel.stream_disconnected.connect(
            lambda: self._set_stream_status(False))
        self.channel.listener_count_updated.connect(
            lambda c: self.listeners_label.setText(f"Слушателей: {c}"))
        self.channel.error_occurred.connect(
            lambda m: self.track_label.setText(f"⚠ {m}"))

        self.input_combo.currentIndexChanged.connect(self._on_input_changed)
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        self.aux1_combo.currentIndexChanged.connect(self._on_aux1_changed)
        self.aux2_combo.currentIndexChanged.connect(self._on_aux2_changed)

    # ------------------------------------------------------------------ #
    #  Device population                                                   #
    # ------------------------------------------------------------------ #

    def populate_devices(self) -> None:
        devices = AudioEngine.get_devices()
        self.input_combo.blockSignals(True)
        self.output_combo.blockSignals(True)
        self.monitor_combo.blockSignals(True)
        self.aux1_combo.blockSignals(True)
        self.aux2_combo.blockSignals(True)

        self.input_combo.clear()
        self.output_combo.clear()
        # Keep the "not used" placeholder for optional outputs.
        self.monitor_combo.clear()
        self.monitor_combo.addItem("— Не используется —", None)
        self.aux1_combo.clear()
        self.aux1_combo.addItem("— Не используется —", None)
        self.aux2_combo.clear()
        self.aux2_combo.addItem("— Не используется —", None)

        for dev in devices:
            label = f"[{dev['hostapi']}] {dev['name']}"
            if dev["max_input_channels"] > 0:
                self.input_combo.addItem(label, dev["index"])
            if dev["max_output_channels"] > 0:
                self.output_combo.addItem(label, dev["index"])
                self.monitor_combo.addItem(label, dev["index"])
                self.aux1_combo.addItem(label, dev["index"])
                self.aux2_combo.addItem(label, dev["index"])

        self.input_combo.blockSignals(False)
        self.output_combo.blockSignals(False)
        self.monitor_combo.blockSignals(False)
        self.aux1_combo.blockSignals(False)
        self.aux2_combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  Actions                                                             #
    # ------------------------------------------------------------------ #

    def _switch_source(self, source: AudioSource) -> None:
        self.btn_live.setChecked(source == AudioSource.LIVE_INPUT)
        self.btn_mp3.setChecked(source == AudioSource.MP3_FILE)
        self.btn_radio.setChecked(source == AudioSource.INTERNET_RADIO)
        self.channel.switch_source(source)

    def _on_source_changed(self, name: str) -> None:
        labels = {
            "live_input": "🎤 Live",
            "mp3_file": "🎵 MP3",
            "internet_radio": "📻 Radio",
        }
        self.track_label.setText(labels.get(name, name))

    def _on_input_changed(self, idx: int) -> None:
        if idx < 0:
            return
        dev_index = self.input_combo.currentData()
        if dev_index is not None:
            self.channel.engine.set_input_device(dev_index)

    def _on_output_changed(self, idx: int) -> None:
        if idx < 0:
            return
        dev_index = self.output_combo.currentData()
        if dev_index is not None:
            self.channel.engine.set_output_device(dev_index)
            from core.audio_router import BusType
            self.channel.router.set_bus_device(BusType.MAIN, dev_index)

    def _on_monitor_changed(self, idx: int) -> None:
        from core.audio_router import BusConfig, BusType
        dev_index = self.monitor_combo.currentData()
        if dev_index is None:
            self.channel.router.set_bus_enabled(BusType.MONITOR, False)
            self.channel.config.monitor_enabled = False
        else:
            self.channel.config.monitor_device = dev_index
            self.channel.config.monitor_enabled = True
            self.channel.router.add_bus(BusConfig(
                bus_type=BusType.MONITOR,
                device_index=dev_index,
                enabled=True,
                volume=self.channel.config.monitor_volume,
                label="Monitor (PFL)",
            ))
            self.channel.router.get_bus(BusType.MONITOR).start()

    def _on_aux1_changed(self, idx: int) -> None:
        from core.audio_router import BusConfig, BusType
        dev_index = self.aux1_combo.currentData()
        if dev_index is None:
            self.channel.router.set_bus_enabled(BusType.AUX1, False)
            self.channel.config.aux1_enabled = False
        else:
            self.channel.config.aux1_device = dev_index
            self.channel.config.aux1_enabled = True
            self.channel.router.add_bus(BusConfig(
                bus_type=BusType.AUX1,
                device_index=dev_index,
                enabled=True,
                volume=self.channel.config.aux1_volume,
                label="AUX 1",
            ))
            self.channel.router.get_bus(BusType.AUX1).start()

    def _on_aux2_changed(self, idx: int) -> None:
        from core.audio_router import BusConfig, BusType
        dev_index = self.aux2_combo.currentData()
        if dev_index is None:
            self.channel.router.set_bus_enabled(BusType.AUX2, False)
            self.channel.config.aux2_enabled = False
        else:
            self.channel.config.aux2_device = dev_index
            self.channel.config.aux2_enabled = True
            self.channel.router.add_bus(BusConfig(
                bus_type=BusType.AUX2,
                device_index=dev_index,
                enabled=True,
                volume=self.channel.config.aux2_volume,
                label="AUX 2",
            ))
            self.channel.router.get_bus(BusType.AUX2).start()

    def _toggle_stream(self) -> None:
        if self._streaming:
            self.channel.stop_streaming()
        else:
            self.channel.start_streaming()

    def _set_stream_status(self, connected: bool) -> None:
        self._streaming = connected
        if connected:
            self.stream_status.setText("● Вещание")
            self.stream_status.setStyleSheet("color: #3fb950; font-weight: bold;")
            self.stream_btn.setText("⏹ Остановить")
        else:
            self.stream_status.setText("● Офлайн")
            self.stream_status.setStyleSheet("color: #f85149; font-weight: bold;")
            self.stream_btn.setText("🔴 Начать")
