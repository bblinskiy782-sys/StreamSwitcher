"""
Main Window - StreamSwitcher Pro
Dark Mode Professional Broadcasting Station UI
"""
import time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QSlider, QComboBox,
    QTabWidget, QSplitter, QListWidget, QListWidgetItem,
    QFileDialog, QStatusBar, QFrame, QSpinBox, QLineEdit,
    QMessageBox, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor, QIcon

from ui.styles import DARK_STYLESHEET
from ui.vu_meter import VUMeter
from ui.waveform_widget import WaveformWidget
from ui.dsp_panel import DSPPanel
from ui.scheduler_panel import SchedulerPanel
from ui.stream_panel import StreamPanel
from core.audio_engine import AudioEngine, AudioSource, MixMode
from core.source_manager import SourceManager
from core.scheduler import Scheduler
from core.streamer import IcecastStreamer
from core.remote_api import RemoteAPI


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamSwitcher Pro")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 800)
        self.setStyleSheet(DARK_STYLESHEET)

        # --- Core objects ---
        self.engine = AudioEngine(self)
        self.source_mgr = SourceManager(
            sample_rate=self.engine.sample_rate,
            channels=self.engine.channels,
            blocksize=self.engine.blocksize,
            parent=self,
        )
        self.scheduler = Scheduler(self)
        self.streamer = IcecastStreamer(self)
        self.remote_api = RemoteAPI(port=8080)

        self._start_time = time.time()
        self._muted = False
        self._listener_count = 0
        self._current_track = ""

        # Wire engine -> source manager
        self.engine._external_audio_callback = self.source_mgr.get_audio_frame
        self.engine._stream_output_callback = self.streamer.push_audio

        self._build_ui()
        self._connect_signals()
        self._populate_devices()
        self._setup_remote_api()

        # Uptime timer
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.start(1000)

        # Start scheduler
        self.scheduler.start()

        # Start engine
        self.engine.start()

        # Failover check timer
        self._failover_timer = QTimer(self)
        self._failover_timer.timeout.connect(self.engine.check_failover)
        self._failover_timer.start(2000)

        self._show_status("StreamSwitcher запущен. Remote API: http://localhost:8080")

    # ------------------------------------------------------------------ #
    #  UI BUILD                                                            #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        # Top bar: source selector + transport + volume
        root.addWidget(self._build_top_bar())

        # Main splitter: left panel | tabs
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_tabs())
        splitter.setSizes([320, 960])
        root.addWidget(splitter, 1)

        # Waveform mini-player
        root.addWidget(self._build_mini_player())

        # Status bar
        self._build_status_bar()

    # ------------------------------------------------------------------ #
    #  TOP BAR                                                             #
    # ------------------------------------------------------------------ #

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        bar.setStyleSheet("QFrame { background: #161b22; border-radius: 8px; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # App title
        title = QLabel("🎙 StreamSwitcher Pro")
        title.setStyleSheet("color: #58a6ff; font-size: 13pt; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(20)

        # Source buttons
        src_label = QLabel("Источник:")
        src_label.setStyleSheet("color: #8b949e;")
        layout.addWidget(src_label)

        self.btn_live = QPushButton("🎤 Живой вход")
        self.btn_live.setObjectName("btn_live")
        self.btn_live.setCheckable(True)
        self.btn_live.setChecked(True)
        self.btn_live.setMinimumWidth(120)
        self.btn_live.clicked.connect(lambda: self._switch_source(AudioSource.LIVE_INPUT))
        layout.addWidget(self.btn_live)

        self.btn_mp3 = QPushButton("🎵 MP3 файл")
        self.btn_mp3.setObjectName("btn_mp3")
        self.btn_mp3.setCheckable(True)
        self.btn_mp3.setMinimumWidth(110)
        self.btn_mp3.clicked.connect(lambda: self._switch_source(AudioSource.MP3_FILE))
        layout.addWidget(self.btn_mp3)

        self.btn_radio = QPushButton("📻 Радио")
        self.btn_radio.setObjectName("btn_radio")
        self.btn_radio.setCheckable(True)
        self.btn_radio.setMinimumWidth(100)
        self.btn_radio.clicked.connect(lambda: self._switch_source(AudioSource.INTERNET_RADIO))
        layout.addWidget(self.btn_radio)

        layout.addSpacing(20)

        # Transport
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("btn_play")
        self.btn_play.setFixedSize(40, 36)
        self.btn_play.setToolTip("Play")
        self.btn_play.clicked.connect(self._on_play)
        layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setFixedSize(40, 36)
        self.btn_stop.setToolTip("Stop")
        self.btn_stop.clicked.connect(self._on_stop)
        layout.addWidget(self.btn_stop)

        self.btn_next = QPushButton("⏭")
        self.btn_next.setObjectName("btn_next")
        self.btn_next.setFixedSize(40, 36)
        self.btn_next.setToolTip("Next track")
        self.btn_next.clicked.connect(self._on_next)
        layout.addWidget(self.btn_next)

        self.btn_mute = QPushButton("🔇")
        self.btn_mute.setObjectName("btn_mute")
        self.btn_mute.setFixedSize(40, 36)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setToolTip("Mute")
        self.btn_mute.toggled.connect(self._on_mute)
        layout.addWidget(self.btn_mute)

        layout.addSpacing(8)

        # Dual mode toggle
        self.btn_dual = QPushButton("🔀 Dual Mix")
        self.btn_dual.setCheckable(True)
        self.btn_dual.setToolTip("Микс двух источников одновременно")
        self.btn_dual.toggled.connect(self._on_dual_toggle)
        layout.addWidget(self.btn_dual)

        layout.addSpacing(12)

        # Volume
        vol_label = QLabel("🔊")
        layout.addWidget(vol_label)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.setToolTip("Громкость")
        self.vol_slider.valueChanged.connect(
            lambda v: self.engine.set_volume(v / 100.0)
        )
        layout.addWidget(self.vol_slider)
        self.vol_pct_label = QLabel("80%")
        self.vol_pct_label.setStyleSheet("color: #58a6ff; min-width: 36px;")
        self.vol_slider.valueChanged.connect(
            lambda v: self.vol_pct_label.setText(f"{v}%")
        )
        layout.addWidget(self.vol_pct_label)

        layout.addStretch()

        # Remote API indicator
        self.remote_label = QLabel("🌐 :8080")
        self.remote_label.setStyleSheet("color: #3fb950; font-size: 8pt;")
        self.remote_label.setToolTip("Remote API активен на порту 8080")
        layout.addWidget(self.remote_label)

        return bar

    # ------------------------------------------------------------------ #
    #  LEFT PANEL: Audio Matrix + VU Meters                               #
    # ------------------------------------------------------------------ #

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(8)

        # Audio Matrix
        matrix_group = QGroupBox("Audio Matrix")
        matrix_layout = QVBoxLayout(matrix_group)
        matrix_layout.setSpacing(8)

        # Input device
        matrix_layout.addWidget(QLabel("Вход (Input):"))
        self.input_combo = QComboBox()
        self.input_combo.setToolTip("Выберите входное аудиоустройство")
        self.input_combo.currentIndexChanged.connect(self._on_input_device_changed)
        matrix_layout.addWidget(self.input_combo)

        # Output device
        matrix_layout.addWidget(QLabel("Выход (Output):"))
        self.output_combo = QComboBox()
        self.output_combo.setToolTip("Выберите выходное аудиоустройство")
        self.output_combo.currentIndexChanged.connect(self._on_output_device_changed)
        matrix_layout.addWidget(self.output_combo)

        # Sample rate
        sr_row = QHBoxLayout()
        sr_row.addWidget(QLabel("Sample Rate:"))
        self.sr_combo = QComboBox()
        for sr in [44100, 48000, 88200, 96000]:
            self.sr_combo.addItem(f"{sr} Hz", sr)
        self.sr_combo.currentIndexChanged.connect(self._on_samplerate_changed)
        sr_row.addWidget(self.sr_combo)
        matrix_layout.addLayout(sr_row)

        # Refresh devices button
        refresh_btn = QPushButton("🔄 Обновить устройства")
        refresh_btn.clicked.connect(self._populate_devices)
        matrix_layout.addWidget(refresh_btn)

        layout.addWidget(matrix_group)

        # VU Meters
        vu_group = QGroupBox("Уровни (VU Meters)")
        vu_layout = QVBoxLayout(vu_group)

        vu_row = QHBoxLayout()
        vu_row.setSpacing(4)

        # Input VU
        in_col = QVBoxLayout()
        in_col.addWidget(QLabel("IN"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.vu_input = VUMeter()
        in_col.addWidget(self.vu_input)
        vu_row.addLayout(in_col)

        # Output VU
        out_col = QVBoxLayout()
        out_col.addWidget(QLabel("OUT"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.vu_output = VUMeter()
        out_col.addWidget(self.vu_output)
        vu_row.addLayout(out_col)

        vu_layout.addLayout(vu_row)

        # Clip indicator
        self.clip_label = QLabel("")
        self.clip_label.setObjectName("label_clip")
        self.clip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vu_layout.addWidget(self.clip_label)

        layout.addWidget(vu_group)

        # Current source info
        info_group = QGroupBox("Текущий эфир")
        info_layout = QVBoxLayout(info_group)

        self.source_name_label = QLabel("Живой вход")
        self.source_name_label.setObjectName("label_source_name")
        self.source_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.source_name_label)

        self.track_label = QLabel("—")
        self.track_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_label.setStyleSheet("color: #8b949e; font-size: 8pt;")
        self.track_label.setWordWrap(True)
        info_layout.addWidget(self.track_label)

        # Silence detector status
        self.silence_label = QLabel("")
        self.silence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.silence_label.setStyleSheet("color: #d29922; font-size: 8pt;")
        info_layout.addWidget(self.silence_label)

        # Failover status
        self.failover_label = QLabel("")
        self.failover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.failover_label.setStyleSheet("color: #f85149; font-size: 8pt;")
        info_layout.addWidget(self.failover_label)

        layout.addWidget(info_group)

        # Dual Mix controls
        dual_group = QGroupBox("Dual Mix (два источника)")
        dual_layout = QVBoxLayout(dual_group)

        dual_layout.addWidget(QLabel("Громкость Live:"))
        self.live_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.live_vol_slider.setRange(0, 100)
        self.live_vol_slider.setValue(100)
        self.live_vol_slider.valueChanged.connect(
            lambda v: self.engine.set_live_volume(v / 100.0)
        )
        dual_layout.addWidget(self.live_vol_slider)

        dual_layout.addWidget(QLabel("Громкость Secondary:"))
        self.sec_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.sec_vol_slider.setRange(0, 100)
        self.sec_vol_slider.setValue(60)
        self.sec_vol_slider.valueChanged.connect(
            lambda v: self.engine.set_secondary_volume(v / 100.0)
        )
        dual_layout.addWidget(self.sec_vol_slider)

        sec_src_row = QHBoxLayout()
        sec_src_row.addWidget(QLabel("2-й источник:"))
        self.sec_source_combo = QComboBox()
        self.sec_source_combo.addItem("🎵 MP3", AudioSource.MP3_FILE.value)
        self.sec_source_combo.addItem("📻 Радио", AudioSource.INTERNET_RADIO.value)
        self.sec_source_combo.currentIndexChanged.connect(self._on_secondary_changed)
        sec_src_row.addWidget(self.sec_source_combo)
        dual_layout.addLayout(sec_src_row)

        # Failover toggle
        self.failover_check = QCheckBox("Auto-Failover при обрыве")
        self.failover_check.setChecked(True)
        self.failover_check.toggled.connect(self.engine.set_failover_enabled)
        dual_layout.addWidget(self.failover_check)

        layout.addWidget(dual_group)
        layout.addStretch()

        return panel

    # ------------------------------------------------------------------ #
    #  TABS                                                                #
    # ------------------------------------------------------------------ #

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()

        tabs.addTab(self._build_playlist_tab(), "🎵 Плейлист")
        tabs.addTab(self._build_radio_tab(), "📻 Радио")
        tabs.addTab(self._build_scheduler_tab(), "⏰ Расписание")
        tabs.addTab(self._build_dsp_tab(), "🎛 DSP")
        tabs.addTab(self._build_stream_tab(), "📡 Стриминг")

        return tabs

    def _build_playlist_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить файлы")
        add_btn.clicked.connect(self._add_files)
        toolbar.addWidget(add_btn)

        add_url_btn = QPushButton("🌐 Добавить URL")
        add_url_btn.clicked.connect(self._add_url)
        toolbar.addWidget(add_url_btn)

        add_smb_btn = QPushButton("🗂 SMB/NFS путь")
        add_smb_btn.clicked.connect(self._add_smb)
        toolbar.addWidget(add_smb_btn)

        clear_btn = QPushButton("🗑 Очистить")
        clear_btn.clicked.connect(self._clear_playlist)
        toolbar.addWidget(clear_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Playlist
        self.playlist_widget = QListWidget()
        self.playlist_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.playlist_widget.doubleClicked.connect(self._play_selected)
        layout.addWidget(self.playlist_widget, 1)

        # Position slider
        pos_row = QHBoxLayout()
        self.pos_label = QLabel("0:00")
        self.pos_label.setStyleSheet("color: #58a6ff; min-width: 40px;")
        pos_row.addWidget(self.pos_label)

        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.sliderMoved.connect(self._on_seek)
        pos_row.addWidget(self.pos_slider, 1)

        self.dur_label = QLabel("0:00")
        self.dur_label.setStyleSheet("color: #8b949e; min-width: 40px;")
        pos_row.addWidget(self.dur_label)
        layout.addLayout(pos_row)

        return w

    def _build_radio_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        url_group = QGroupBox("URL интернет-радио")
        url_layout = QVBoxLayout(url_group)

        url_row = QHBoxLayout()
        self.radio_url_edit = QLineEdit()
        self.radio_url_edit.setPlaceholderText(
            "http://stream.example.com:8000/stream"
        )
        url_row.addWidget(self.radio_url_edit, 1)
        play_radio_btn = QPushButton("▶ Слушать")
        play_radio_btn.setObjectName("btn_play")
        play_radio_btn.clicked.connect(self._play_radio)
        url_row.addWidget(play_radio_btn)
        url_layout.addLayout(url_row)

        # Presets
        presets_label = QLabel("Пресеты:")
        url_layout.addWidget(presets_label)
        self.presets_list = QListWidget()
        self.presets_list.setMaximumHeight(120)
        presets = [
            ("Радио Рекорд", "http://air.radiorecord.ru:805/rr_320"),
            ("Europa Plus", "http://europaplus.hostingradio.ru:8052/europaplus128.mp3"),
            ("DI.FM Trance", "http://prem2.di.fm:80/trance"),
            ("SomaFM Groove", "http://ice1.somafm.com/groovesalad-128-mp3"),
        ]
        for name, url in presets:
            item = QListWidgetItem(f"📻 {name}")
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.presets_list.addItem(item)
        self.presets_list.doubleClicked.connect(self._load_preset)
        url_layout.addWidget(self.presets_list)

        layout.addWidget(url_group)

        # Buffering indicator
        self.buffer_label = QLabel("")
        self.buffer_label.setStyleSheet("color: #d29922;")
        self.buffer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.buffer_label)

        layout.addStretch()
        return w

    def _build_scheduler_tab(self) -> QWidget:
        self.scheduler_panel = SchedulerPanel()
        self.scheduler_panel.entry_added.connect(self._on_schedule_add)
        self.scheduler_panel.entry_removed.connect(self.scheduler.remove_entry)
        self.scheduler_panel.entry_toggled.connect(self.scheduler.toggle_entry)
        self.scheduler_panel.entry_edited.connect(self._on_schedule_edit)
        return self.scheduler_panel

    def _build_dsp_tab(self) -> QWidget:
        self.dsp_panel = DSPPanel()
        self.dsp_panel.eq_changed.connect(self.engine.set_eq_band)
        self.dsp_panel.eq_enabled_changed.connect(
            lambda v: setattr(self.engine, "eq_enabled", v)
        )
        self.dsp_panel.compressor_changed.connect(self.engine.set_compressor)
        self.dsp_panel.compressor_enabled_changed.connect(
            lambda v: setattr(self.engine, "compressor_enabled", v)
        )
        return self.dsp_panel

    def _build_stream_tab(self) -> QWidget:
        self.stream_panel = StreamPanel()
        self.stream_panel.connect_requested.connect(self._on_stream_connect)
        self.stream_panel.disconnect_requested.connect(self._on_stream_disconnect)
        return self.stream_panel

    # ------------------------------------------------------------------ #
    #  MINI PLAYER                                                         #
    # ------------------------------------------------------------------ #

    def _build_mini_player(self) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("QFrame { background: #161b22; border-radius: 6px; }")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.mini_track_label = QLabel("Нет трека")
        self.mini_track_label.setStyleSheet("color: #58a6ff; min-width: 200px;")
        layout.addWidget(self.mini_track_label)

        self.waveform = WaveformWidget()
        self.waveform.seek_requested.connect(self._on_waveform_seek)
        layout.addWidget(self.waveform, 1)

        return frame

    # ------------------------------------------------------------------ #
    #  STATUS BAR                                                          #
    # ------------------------------------------------------------------ #

    def _build_status_bar(self):
        sb = self.statusBar()

        self.status_source = QLabel("Источник: Живой вход")
        self.status_source.setStyleSheet("color: #3fb950;")
        sb.addWidget(self.status_source)

        sb.addWidget(self._make_separator())

        self.status_uptime = QLabel("Аптайм: 00:00:00")
        self.status_uptime.setObjectName("label_uptime")
        sb.addWidget(self.status_uptime)

        sb.addWidget(self._make_separator())

        self.status_listeners = QLabel("Слушателей: 0")
        self.status_listeners.setObjectName("label_listeners")
        sb.addWidget(self.status_listeners)

        sb.addWidget(self._make_separator())

        self.status_stream = QLabel("● Офлайн")
        self.status_stream.setStyleSheet("color: #f85149;")
        sb.addWidget(self.status_stream)

        sb.addPermanentWidget(QLabel("StreamSwitcher Pro v1.0"))

    def _make_separator(self) -> QLabel:
        sep = QLabel("  |  ")
        sep.setStyleSheet("color: #30363d;")
        return sep

    # ------------------------------------------------------------------ #
    #  SIGNALS                                                             #
    # ------------------------------------------------------------------ #

    def _connect_signals(self):
        # Engine signals
        self.engine.level_updated.connect(self.vu_output.set_levels)
        self.engine.source_changed.connect(self._on_source_changed)
        self.engine.error_occurred.connect(self._show_error)
        self.engine.silence_detected.connect(self._on_silence_detected)
        self.engine.clip_detected.connect(self._on_clip)
        self.engine.source_failed.connect(self._on_source_failed)

        # Source manager signals
        self.source_mgr.track_changed.connect(self._on_track_changed)
        self.source_mgr.position_updated.connect(self._on_position_updated)
        self.source_mgr.duration_updated.connect(self._on_duration_updated)
        self.source_mgr.waveform_ready.connect(self.waveform.set_waveform)
        self.source_mgr.playlist_updated.connect(self._on_playlist_updated)
        self.source_mgr.error_occurred.connect(self._show_error)
        self.source_mgr.buffering.connect(self._on_buffering)

        # Scheduler signals
        self.scheduler.event_fired.connect(self._on_schedule_event)
        self.scheduler.schedule_updated.connect(self.scheduler_panel.update_entries)

        # Streamer signals
        self.streamer.connected.connect(lambda: self._on_stream_status(True))
        self.streamer.disconnected.connect(lambda: self._on_stream_status(False))
        self.streamer.listener_count_updated.connect(self._on_listeners_updated)
        self.streamer.error_occurred.connect(self._show_error)
        self.streamer.bytes_sent_updated.connect(self.stream_panel.update_bytes_sent)

    # ------------------------------------------------------------------ #
    #  DEVICE MANAGEMENT                                                   #
    # ------------------------------------------------------------------ #

    def _populate_devices(self):
        devices = AudioEngine.get_devices()
        self.input_combo.blockSignals(True)
        self.output_combo.blockSignals(True)
        self.input_combo.clear()
        self.output_combo.clear()

        for dev in devices:
            label = f"[{dev['hostapi']}] {dev['name']}"
            if dev["max_input_channels"] > 0:
                self.input_combo.addItem(label, dev["index"])
            if dev["max_output_channels"] > 0:
                self.output_combo.addItem(label, dev["index"])

        self.input_combo.blockSignals(False)
        self.output_combo.blockSignals(False)

    def _on_input_device_changed(self, idx):
        if idx < 0:
            return
        dev_index = self.input_combo.currentData()
        if dev_index is not None:
            self.engine.set_input_device(dev_index)

    def _on_output_device_changed(self, idx):
        if idx < 0:
            return
        dev_index = self.output_combo.currentData()
        if dev_index is not None:
            self.engine.set_output_device(dev_index)

    def _on_samplerate_changed(self, idx):
        sr = self.sr_combo.currentData()
        if sr:
            self.engine.sample_rate = sr
            self.source_mgr.sample_rate = sr
            self.engine.restart()

    # ------------------------------------------------------------------ #
    #  SOURCE SWITCHING                                                    #
    # ------------------------------------------------------------------ #

    def _switch_source(self, source: AudioSource):
        self.btn_live.setChecked(source == AudioSource.LIVE_INPUT)
        self.btn_mp3.setChecked(source == AudioSource.MP3_FILE)
        self.btn_radio.setChecked(source == AudioSource.INTERNET_RADIO)
        self.engine.switch_source(source)

    def _on_source_changed(self, source_name: str):
        labels = {
            "live_input": "Живой вход",
            "mp3_file": "MP3 файл",
            "internet_radio": "Интернет-радио",
        }
        display = labels.get(source_name, source_name)
        self.source_name_label.setText(display)
        self.status_source.setText(f"Источник: {display}")
        self.silence_label.setText("")

    # ------------------------------------------------------------------ #
    #  TRANSPORT CONTROLS                                                  #
    # ------------------------------------------------------------------ #

    def _on_play(self):
        src = self.engine.current_source
        if src == AudioSource.MP3_FILE:
            self.source_mgr.play_file()
        elif src == AudioSource.INTERNET_RADIO:
            self._play_radio()
        else:
            self.engine.start()

    def _on_stop(self):
        self.source_mgr.stop()

    def _on_next(self):
        self.source_mgr.next_track()

    def _on_mute(self, checked: bool):
        self._muted = checked
        self.engine.set_mute(checked)

    # ------------------------------------------------------------------ #
    #  PLAYLIST                                                            #
    # ------------------------------------------------------------------ #

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Добавить аудиофайлы", "",
            "Audio (*.mp3 *.wav *.flac *.ogg *.aac *.wma);;All (*)"
        )
        if paths:
            for p in paths:
                self.source_mgr.add_to_playlist(p)

    def _add_url(self):
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self, "Добавить URL",
            "HTTP/FTP ссылка на аудиофайл:"
        )
        if ok and url.strip():
            self.source_mgr.add_to_playlist(url.strip())

    def _add_smb(self):
        from PySide6.QtWidgets import QInputDialog
        path, ok = QInputDialog.getText(
            self, "SMB/NFS путь",
            "UNC путь (\\\\server\\share\\file.mp3):"
        )
        if ok and path.strip():
            self.source_mgr.add_to_playlist(path.strip())

    def _clear_playlist(self):
        self.source_mgr.clear_playlist()

    def _play_selected(self, index):
        row = index.row()
        if row >= 0 and row < len(self.source_mgr._playlist):
            path = self.source_mgr._playlist[row]
            self._switch_source(AudioSource.MP3_FILE)
            self.source_mgr.play_file(path)

    def _on_playlist_updated(self, names: list):
        self.playlist_widget.clear()
        for i, name in enumerate(names):
            item = QListWidgetItem(f"  {i+1}. {name}")
            self.playlist_widget.addItem(item)

    def _on_track_changed(self, name: str):
        self._current_track = name
        self.track_label.setText(name)
        self.mini_track_label.setText(f"🎵 {name}")

    def _on_position_updated(self, pos: float):
        if self.source_mgr.duration > 0:
            pct = int((pos / self.source_mgr.duration) * 1000)
            self.pos_slider.blockSignals(True)
            self.pos_slider.setValue(pct)
            self.pos_slider.blockSignals(False)
        m, s = divmod(int(pos), 60)
        self.pos_label.setText(f"{m}:{s:02d}")
        self.waveform.set_position(pos, self.source_mgr.duration)

    def _on_duration_updated(self, dur: float):
        m, s = divmod(int(dur), 60)
        self.dur_label.setText(f"{m}:{s:02d}")

    def _on_seek(self, value: int):
        if self.source_mgr.duration > 0:
            pos = (value / 1000.0) * self.source_mgr.duration
            self.source_mgr.seek(pos)

    def _on_waveform_seek(self, frac: float):
        if self.source_mgr.duration > 0:
            self.source_mgr.seek(frac * self.source_mgr.duration)

    # ------------------------------------------------------------------ #
    #  RADIO                                                               #
    # ------------------------------------------------------------------ #

    def _play_radio(self):
        url = self.radio_url_edit.text().strip()
        if url:
            self._switch_source(AudioSource.INTERNET_RADIO)
            self.source_mgr.play_radio(url)

    def _load_preset(self, index):
        item = self.presets_list.item(index.row())
        if item:
            url = item.data(Qt.ItemDataRole.UserRole)
            self.radio_url_edit.setText(url)
            self._play_radio()

    def _on_buffering(self, is_buffering: bool):
        if is_buffering:
            self.buffer_label.setText("⏳ Буферизация...")
        else:
            self.buffer_label.setText("")

    # ------------------------------------------------------------------ #
    #  SCHEDULER                                                           #
    # ------------------------------------------------------------------ #

    def _on_schedule_add(self, time_str, action, target, repeat):
        self.scheduler.add_entry(time_str, action, target, repeat)

    def _on_schedule_edit(self, entry_id, time_str, action, target, repeat):
        self.scheduler.update_entry(entry_id, time_str, action, target, repeat)

    def _on_schedule_event(self, entry):
        """Handle a scheduled event firing."""
        self.scheduler_panel.highlight_fired(entry.id)
        if entry.action == "play_file":
            self._switch_source(AudioSource.MP3_FILE)
            self.source_mgr.play_file(entry.target)
        elif entry.action == "play_radio":
            self._switch_source(AudioSource.INTERNET_RADIO)
            self.source_mgr.play_radio(entry.target)
        elif entry.action == "switch_live":
            self._switch_source(AudioSource.LIVE_INPUT)
        elif entry.action == "stop":
            self.source_mgr.stop()
        self._show_status(f"Расписание: {entry.action} @ {entry.time_str}")

    # ------------------------------------------------------------------ #
    #  STREAMING                                                           #
    # ------------------------------------------------------------------ #

    def _on_stream_connect(self, config: dict):
        self.streamer.configure(
            host=config["host"],
            port=config["port"],
            mount=config["mount"],
            password=config["password"],
            bitrate=config["bitrate"],
        )
        self.streamer.stream_name = config.get("name", "StreamSwitcher")
        self.streamer.genre = config.get("genre", "Various")
        self.streamer.start()

    def _on_stream_disconnect(self):
        self.streamer.stop()

    def _on_stream_status(self, connected: bool):
        self.stream_panel.set_connected(connected)
        if connected:
            self.status_stream.setText("● Вещание")
            self.status_stream.setStyleSheet("color: #3fb950;")
        else:
            self.status_stream.setText("● Офлайн")
            self.status_stream.setStyleSheet("color: #f85149;")

    def _on_listeners_updated(self, count: int):
        self._listener_count = count
        self.status_listeners.setText(f"Слушателей: {count}")
        self.stream_panel.update_listeners(count)

    # ------------------------------------------------------------------ #
    #  SILENCE DETECTOR                                                    #
    # ------------------------------------------------------------------ #

    def _on_silence_detected(self):
        self.silence_label.setText("⚠ Тишина >30с! Запуск резервного плейлиста...")
        self._show_status("Silence detected! Switching to backup playlist...")
        # Auto-switch to MP3 if playlist available
        if self.source_mgr._playlist:
            self._switch_source(AudioSource.MP3_FILE)
            self.source_mgr.play_file()

    # ------------------------------------------------------------------ #
    #  FAILOVER                                                            #
    # ------------------------------------------------------------------ #

    def _on_source_failed(self, failed_source: str):
        self.failover_label.setText(f"⚠ Обрыв: {failed_source}! Переключение...")
        self._show_status(f"Auto-Failover: {failed_source} не отвечает, переключение...")
        QTimer.singleShot(5000, lambda: self.failover_label.setText(""))

    # ------------------------------------------------------------------ #
    #  DUAL MODE                                                           #
    # ------------------------------------------------------------------ #

    def _on_dual_toggle(self, checked: bool):
        if checked:
            self.engine.set_mix_mode(MixMode.DUAL)
            self._show_status("Dual Mix: Live + Secondary одновременно")
        else:
            self.engine.set_mix_mode(MixMode.SINGLE)
            self._show_status("Single Mode: один источник")

    def _on_secondary_changed(self, idx):
        val = self.sec_source_combo.currentData()
        mapping = {
            "mp3_file": AudioSource.MP3_FILE,
            "internet_radio": AudioSource.INTERNET_RADIO,
        }
        src = mapping.get(val)
        if src:
            self.engine.set_secondary_source(src)

    # ------------------------------------------------------------------ #
    #  CLIP INDICATOR                                                      #
    # ------------------------------------------------------------------ #

    def _on_clip(self):
        self.clip_label.setText("⚠ CLIP!")
        QTimer.singleShot(1500, lambda: self.clip_label.setText(""))

    # ------------------------------------------------------------------ #
    #  REMOTE API                                                          #
    # ------------------------------------------------------------------ #

    def _setup_remote_api(self):
        self.remote_api.on_play = self._on_play
        self.remote_api.on_stop = self._on_stop
        self.remote_api.on_next = self._on_next
        self.remote_api.on_mute = lambda: self._on_mute(not self._muted)
        self.remote_api.on_source_switch = self._remote_switch_source
        self.remote_api.get_status = self._get_remote_status
        self.remote_api.start()

    def _remote_switch_source(self, source_str: str):
        mapping = {
            "live_input": AudioSource.LIVE_INPUT,
            "mp3_file": AudioSource.MP3_FILE,
            "internet_radio": AudioSource.INTERNET_RADIO,
        }
        src = mapping.get(source_str)
        if src:
            self._switch_source(src)

    def _get_remote_status(self) -> dict:
        elapsed = int(time.time() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        return {
            "source": self.engine.current_source.value,
            "uptime": f"{h:02d}:{m:02d}:{s:02d}",
            "listeners": self._listener_count,
            "track": self._current_track,
            "streaming": self.streamer.is_connected,
            "muted": self._muted,
        }

    # ------------------------------------------------------------------ #
    #  UTILITIES                                                            #
    # ------------------------------------------------------------------ #

    def _update_uptime(self):
        elapsed = int(time.time() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        self.status_uptime.setText(f"Аптайм: {h:02d}:{m:02d}:{s:02d}")

    def _show_status(self, msg: str):
        self.statusBar().showMessage(msg, 5000)

    def _show_error(self, msg: str):
        self.statusBar().showMessage(f"⚠ {msg}", 8000)

    def closeEvent(self, event):
        """Clean shutdown."""
        self.engine.stop()
        self.source_mgr.stop()
        self.scheduler.stop()
        self.streamer.stop()
        self.remote_api.stop()
        event.accept()
