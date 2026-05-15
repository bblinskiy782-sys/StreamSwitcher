"""
Main Window - StreamSwitcher Pro
Dark Mode Professional Broadcasting Station UI
"""
import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio_engine import AudioEngine, AudioSource, MixMode
from core.autodj import AutoDJ, AutoDJRules
from core.config import AppConfig
from core.history import HistoryEntry, HistoryLog
from core.playlist import Track, enrich_track, parse_m3u, parse_pls, write_m3u, write_pls
from core.profiles import (
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)
from core.recorder import AirRecorder
from core.remote_api import RemoteAPI
from core.scheduler import Scheduler
from core.source_manager import SourceManager
from core.streamer import IcecastStreamer
from ui.dsp_panel import DSPPanel
from ui.radio_panel import RadioPanel
from ui.scheduler_panel import SchedulerPanel
from ui.stream_panel import StreamPanel
from ui.styles import DARK_STYLESHEET
from ui.vu_meter import VUMeter
from ui.waveform_widget import WaveformWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamSwitcher Pro")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 800)
        self.setStyleSheet(DARK_STYLESHEET)

        # Window icon
        from PySide6.QtGui import QIcon
        import sys, os
        icon_path = os.path.join(
            getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)) + '/..'),
            'icon.ico'
        )
        if not os.path.exists(icon_path):
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # --- Configuration (load before constructing components) ---
        self._config_path: str | None = None
        self.config: AppConfig = AppConfig.load()

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
        self.remote_api = RemoteAPI(
            port=self.config.remote_api_port,
            api_key=self.config.remote_api_key,
        )
        self.history = HistoryLog()
        self.recorder = AirRecorder(self)
        self.autodj = AutoDJ(
            rules=AutoDJRules(
                enabled=self.config.autodj.enabled,
                shuffle=self.config.autodj.shuffle,
                avoid_repeat_minutes=self.config.autodj.avoid_repeat_minutes,
                insert_jingle_every=self.config.autodj.insert_jingle_every,
                jingle_paths=list(self.config.autodj.jingle_paths),
            ),
            history=self.history,
        )

        self._start_time = time.time()
        self._muted = False
        self._listener_count = 0
        self._current_track = ""

        # Wire engine -> source manager
        self.engine._external_audio_callback = self.source_mgr.get_audio_frame

        # Attach AutoDJ to source manager so _auto_next uses it.
        self.source_mgr._autodj = self.autodj

        # Apply crossfade settings.
        self.source_mgr.crossfade_config.duration_sec = self.config.crossfade.duration_sec
        self.source_mgr.crossfade_config.enabled = self.config.crossfade.enabled
        self.engine._stream_output_callback = self._on_engine_output

        self._build_ui()
        self._connect_signals()
        self._install_hotkeys()
        self._populate_devices()
        self._setup_remote_api()
        self._apply_loaded_config()

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

        # Log startup diagnostics so user can see what's working.
        self._log_startup_diagnostics()

    # ------------------------------------------------------------------ #
    #  UI BUILD                                                            #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        # Menu bar with profiles
        self._build_menu_bar()

        # Top bar: source selector + transport + volume
        root.addWidget(self._build_top_bar())

        # === MAIN VERTICAL SPLITTER: content | log ===
        from PySide6.QtWidgets import QScrollArea
        v_splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Top: left panel (scrollable) | tabs + mini player ---
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel wrapped in scroll area
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_panel = self._build_left_panel()
        left_scroll.setWidget(left_panel)
        left_scroll.setMinimumWidth(230)
        left_scroll.setMaximumWidth(350)

        h_splitter.addWidget(left_scroll)
        h_splitter.addWidget(self._build_tabs())
        h_splitter.setSizes([280, 960])
        h_splitter.setChildrenCollapsible(False)

        content_layout.addWidget(h_splitter, 1)
        content_layout.addWidget(self._build_mini_player())

        # Allow content to shrink freely for the vertical splitter
        content_widget.setMinimumHeight(100)

        v_splitter.addWidget(content_widget)

        # --- Bottom: log panel ---
        v_splitter.addWidget(self._build_log_panel())

        # Initial sizes: ~70% content, ~30% log. Freely resizable.
        v_splitter.setSizes([500, 200])
        v_splitter.setHandleWidth(6)

        root.addWidget(v_splitter, 1)

        # Status bar
        self._build_status_bar()

    # ------------------------------------------------------------------ #
    #  MENU BAR (Profiles)                                                 #
    # ------------------------------------------------------------------ #

    def _build_menu_bar(self) -> None:
        from PySide6.QtWidgets import QMenu, QInputDialog
        from PySide6.QtGui import QAction

        mb = self.menuBar()

        # --- File menu ---
        file_menu = mb.addMenu("Файл")
        save_act = QAction("💾 Сохранить конфиг (Ctrl+S)", self)
        save_act.triggered.connect(lambda: self._persist_config(show_status=True))
        file_menu.addAction(save_act)
        file_menu.addSeparator()
        quit_act = QAction("Выход", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # --- Profiles menu ---
        self._profiles_menu = mb.addMenu("Профили")
        self._profiles_menu.aboutToShow.connect(self._rebuild_profiles_menu)

    def _rebuild_profiles_menu(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from PySide6.QtGui import QAction

        menu = self._profiles_menu
        menu.clear()

        # Save current as profile
        save_as = QAction("💾 Сохранить как профиль…", self)
        save_as.triggered.connect(self._profile_save_as)
        menu.addAction(save_as)

        menu.addSeparator()

        # List existing profiles
        names = list_profiles(self._config_path)
        if not names:
            empty = QAction("(нет сохранённых профилей)", self)
            empty.setEnabled(False)
            menu.addAction(empty)
        else:
            for name in names:
                sub = menu.addMenu(f"📋 {name}")
                load_act = QAction("▶ Загрузить", self)
                load_act.triggered.connect(
                    lambda checked=False, n=name: self._profile_load(n)
                )
                sub.addAction(load_act)
                del_act = QAction("🗑 Удалить", self)
                del_act.triggered.connect(
                    lambda checked=False, n=name: self._profile_delete(n)
                )
                sub.addAction(del_act)

    def _profile_save_as(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Сохранить профиль", "Имя профиля:"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        # Snapshot current state first.
        self._persist_config()
        save_profile(name, self.config, self._config_path)
        self._show_status(f"Профиль «{name}» сохранён.")

    def _profile_load(self, name: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        try:
            cfg = load_profile(name, self._config_path)
        except FileNotFoundError:
            QMessageBox.warning(self, "Профиль", f"Профиль «{name}» не найден.")
            return
        self.config = cfg
        self._apply_loaded_config()
        self._show_status(f"Профиль «{name}» загружен.")

    def _profile_delete(self, name: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Удаление профиля",
            f"Удалить профиль «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_profile(name, self._config_path)
            self._show_status(f"Профиль «{name}» удалён.")

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

        # Record button
        self.btn_rec = QPushButton("⏺")
        self.btn_rec.setObjectName("btn_rec")
        self.btn_rec.setFixedSize(40, 36)
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Запись эфира")
        self.btn_rec.setStyleSheet(
            "QPushButton:checked { background: #da3633; color: white; }")
        self.btn_rec.toggled.connect(self._on_record_toggle)
        layout.addWidget(self.btn_rec)

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
        from PySide6.QtWidgets import QScrollArea
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
        tabs.addTab(self._build_channels_tab(), "🔀 Каналы")

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

        import_btn = QPushButton("📂 Импорт M3U/PLS")
        import_btn.clicked.connect(self._import_playlist)
        toolbar.addWidget(import_btn)

        export_btn = QPushButton("💾 Экспорт M3U/PLS")
        export_btn.clicked.connect(self._export_playlist)
        toolbar.addWidget(export_btn)

        clear_btn = QPushButton("🗑 Очистить")
        clear_btn.clicked.connect(self._clear_playlist)
        toolbar.addWidget(clear_btn)

        remove_btn = QPushButton("✖ Удалить трек")
        remove_btn.clicked.connect(self._remove_selected_track)
        toolbar.addWidget(remove_btn)

        move_up_btn = QPushButton("⬆")
        move_up_btn.setToolTip("Переместить вверх")
        move_up_btn.setFixedWidth(30)
        move_up_btn.clicked.connect(lambda: self._move_track(-1))
        toolbar.addWidget(move_up_btn)

        move_down_btn = QPushButton("⬇")
        move_down_btn.setToolTip("Переместить вниз")
        move_down_btn.setFixedWidth(30)
        move_down_btn.clicked.connect(lambda: self._move_track(1))
        toolbar.addWidget(move_down_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Playlist
        self.playlist_widget = QListWidget()
        self.playlist_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.playlist_widget.doubleClicked.connect(self._play_selected)
        layout.addWidget(self.playlist_widget, 1)

        # Keyboard shortcut: Delete to remove selected track
        from PySide6.QtGui import QKeySequence
        del_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.playlist_widget)
        del_shortcut.activated.connect(self._remove_selected_track)

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
        self.radio_panel = RadioPanel()
        self.radio_panel.play_requested.connect(self._play_radio_url)
        self.radio_panel.presets_changed.connect(self._on_presets_changed)
        # Populate from config.
        self.radio_panel.set_presets(self.config.radio_presets)
        if self.config.radio_url:
            self.radio_panel.set_url_text(self.config.radio_url)
        return self.radio_panel

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

    def _build_channels_tab(self) -> QWidget:
        """Multi-channel management tab — add/remove independent audio pipelines."""
        from PySide6.QtWidgets import QScrollArea, QTabWidget as QTW
        from core.channel import Channel, ChannelConfig
        from core.channel_manager import ChannelManager
        from ui.channel_widget import ChannelWidget

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить канал")
        add_btn.clicked.connect(self._add_channel)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        self._ch_count_label = QLabel("Каналов: 0")
        self._ch_count_label.setStyleSheet("color: #8b949e;")
        toolbar.addWidget(self._ch_count_label)
        layout.addLayout(toolbar)

        # Channel tabs (each channel = one sub-tab)
        self._channel_tabs = QTW()
        layout.addWidget(self._channel_tabs, 1)

        # Channel manager
        self._channel_mgr = ChannelManager(self)
        self._channel_widgets: list[ChannelWidget] = []

        # Load channels from config if any.
        if self.config.channels:
            from dataclasses import fields as dc_fields
            for ch_dict in self.config.channels:
                cfg = ChannelConfig()
                for key, val in ch_dict.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, val)
                self._create_channel_ui(cfg)

        self._update_ch_count()
        return w

    def _add_channel(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        from core.channel import ChannelConfig
        name, ok = QInputDialog.getText(
            self, "Новый канал", "Название канала:",
            text=f"Канал {self._channel_mgr.count + 1}",
        )
        if not ok or not name.strip():
            return
        cfg = ChannelConfig(name=name.strip())
        self._create_channel_ui(cfg)
        self._update_ch_count()

    def _create_channel_ui(self, cfg) -> None:
        from core.channel import ChannelConfig
        from ui.channel_widget import ChannelWidget

        ch = self._channel_mgr.add_channel(cfg)
        ch.start()
        widget = ChannelWidget(ch)
        widget.populate_devices()
        widget.remove_requested.connect(
            lambda w=widget: self._remove_channel(w))
        self._channel_widgets.append(widget)
        self._channel_tabs.addTab(widget, cfg.name)

    def _remove_channel(self, widget) -> None:
        from PySide6.QtWidgets import QMessageBox
        idx = self._channel_widgets.index(widget)
        name = self._channel_mgr.channel(idx).config.name
        reply = QMessageBox.question(
            self, "Удаление канала",
            f"Удалить канал «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._channel_mgr.remove_channel(idx)
        self._channel_widgets.pop(idx)
        self._channel_tabs.removeTab(idx)
        self._update_ch_count()

    def _update_ch_count(self) -> None:
        self._ch_count_label.setText(f"Каналов: {self._channel_mgr.count}")

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
    #  LOG PANEL                                                           #
    # ------------------------------------------------------------------ #

    def _build_log_panel(self) -> QWidget:
        from ui.log_panel import LogPanel
        self.log_panel = LogPanel()
        self.log_panel.setMinimumHeight(80)
        return self.log_panel

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

        # --- Log panel connections ---
        self.engine.source_changed.connect(
            lambda s: self.log_panel.log_info(f"Источник: {s}"))
        self.engine.error_occurred.connect(
            lambda m: self.log_panel.log_error(m))
        self.engine.silence_detected.connect(
            lambda: self.log_panel.log_warning("[silence detector]: тишина >30с"))
        self.engine.source_failed.connect(
            lambda s: self.log_panel.log_warning(f"Failover: обрыв {s}"))
        self.source_mgr.track_changed.connect(
            lambda t: self.log_panel.log_info(t))
        self.source_mgr.error_occurred.connect(
            lambda m: self.log_panel.log_error(m))
        self.streamer.connected.connect(
            lambda: self.log_panel.log_info("Вещание: подключено"))
        self.streamer.disconnected.connect(
            lambda: self.log_panel.log_warning("Вещание: отключено"))
        self.streamer.error_occurred.connect(
            lambda m: self.log_panel.log_error(f"Стример: {m}"))
        self.scheduler.event_fired.connect(
            lambda e: self.log_panel.log_info(
                f"[A] Schedule: {e.action} {e.target}"))
        self.recorder.file_rolled.connect(
            lambda p: self.log_panel.log_info(f"Запись: {p}"))

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

        # Stop the previous source to free resources (radio decoder, file reader).
        prev = self.engine.current_source
        if prev == AudioSource.INTERNET_RADIO and source != AudioSource.INTERNET_RADIO:
            # Stop radio decoder so it doesn't keep streaming in background.
            self.source_mgr.stop_radio()
        elif prev == AudioSource.MP3_FILE and source != AudioSource.MP3_FILE:
            # Stop file playback (but keep playlist intact).
            self.source_mgr.stop_file()

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

        # Update source buttons.
        self.btn_live.setChecked(source_name == "live_input")
        self.btn_mp3.setChecked(source_name == "mp3_file")
        self.btn_radio.setChecked(source_name == "internet_radio")

        # Auto-start the new source if it was triggered by failover
        # (the source manager won't have the decoder/player running yet).
        if source_name == "internet_radio" and self.source_mgr._radio_decoder is None:
            url = self.radio_panel.url_text() or self.source_mgr._radio_url
            if url:
                self.source_mgr.play_radio(url)
        elif source_name == "mp3_file" and self.source_mgr._audio_data is None:
            if self.source_mgr._playlist:
                self.source_mgr.play_file()

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

    def _on_record_toggle(self, checked: bool):
        if checked:
            from PySide6.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(
                self, "Папка для записи эфира",
                str(self.recorder.output_dir),
            )
            if not folder:
                self.btn_rec.setChecked(False)
                return
            self.recorder.configure(
                output_dir=folder,
                split_minutes=60,
                sample_rate=self.engine.sample_rate,
                channels=self.engine.channels,
            )
            self.recorder.start()
            self._show_status(f"⏺ Запись эфира: {folder}")
        else:
            self.recorder.stop()
            self._show_status("⏹ Запись остановлена")

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

    def _remove_selected_track(self):
        row = self.playlist_widget.currentRow()
        if row >= 0:
            self.source_mgr.remove_from_playlist(row)

    def _move_track(self, delta: int):
        row = self.playlist_widget.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= len(self.source_mgr._playlist):
            return
        # Swap in source manager's playlist.
        pl = self.source_mgr._playlist
        pl[row], pl[new_row] = pl[new_row], pl[row]
        # Update current index if needed.
        if self.source_mgr._current_index == row:
            self.source_mgr._current_index = new_row
        elif self.source_mgr._current_index == new_row:
            self.source_mgr._current_index = row
        # Refresh UI.
        import os
        names = [os.path.basename(p) for p in pl]
        self.source_mgr.playlist_updated.emit(names)
        self.playlist_widget.setCurrentRow(new_row)

    def _play_selected(self, index):
        row = index.row()
        if row >= 0 and row < len(self.source_mgr._playlist):
            path = self.source_mgr._playlist[row]
            self._switch_source(AudioSource.MP3_FILE)
            self.source_mgr.play_file(path)

    def _on_playlist_updated(self, names: list):
        self.playlist_widget.clear()
        paths = list(self.source_mgr._playlist)
        for i, name in enumerate(names):
            display_name = name
            if i < len(paths):
                try:
                    t = enrich_track(Track(path=paths[i]))
                    if t.artist and t.title:
                        display_name = f"{t.artist} \u2014 {t.title}"
                    elif t.title:
                        display_name = t.title
                except Exception:
                    pass
            item = QListWidgetItem(f"  {i+1}. {display_name}")
            self.playlist_widget.addItem(item)

    def _on_track_changed(self, name: str):
        self._current_track = name
        self.track_label.setText(name)
        self.mini_track_label.setText(f"🎵 {name}")
        # Push metadata to listeners (built-in server displays it via ICY).
        try:
            self.streamer.update_metadata(name)
        except Exception:
            pass
        try:
            self.history.append(
                HistoryEntry.now(
                    source=self.engine.current_source.value
                    if self.engine.current_source else "unknown",
                    track=name,
                )
            )
        except Exception:
            pass

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
        url = self.radio_panel.url_text()
        if url:
            self._switch_source(AudioSource.INTERNET_RADIO)
            self.source_mgr.play_radio(url)

    def _play_radio_url(self, url: str):
        """Slot for RadioPanel.play_requested signal."""
        if url:
            self._switch_source(AudioSource.INTERNET_RADIO)
            self.source_mgr.play_radio(url)

    def _on_presets_changed(self, presets: list):
        """Persist radio presets when the user edits the list."""
        from core.config import RadioPreset
        self.config.radio_presets = [
            RadioPreset(name=p.get("name", ""), url=p.get("url", ""))
            for p in presets
        ]

    def _on_buffering(self, is_buffering: bool):
        self.radio_panel.set_buffering(is_buffering)

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
        mode = config.get("mode", "icecast")
        self.streamer.stream_name = config.get("name", "StreamSwitcher")
        self.streamer.genre = config.get("genre", "Various")

        if mode == "builtin":
            self.streamer.configure_builtin(
                port=config["builtin_port"],
                bind_host=config.get("builtin_bind_host", "0.0.0.0"),
                bitrate=config["bitrate"],
                public=config.get("builtin_public", False),
            )
        else:
            self.streamer.set_mode("icecast")
            self.streamer.configure(
                host=config["host"],
                port=config["port"],
                mount=config["mount"],
                password=config["password"],
                bitrate=config["bitrate"],
            )
        self.streamer.start()

    def _on_stream_disconnect(self):
        # Run stop in background to avoid blocking the GUI thread
        # (stop() joins worker threads which can take seconds).
        import threading
        threading.Thread(
            target=self.streamer.stop, daemon=True
        ).start()

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
        self.remote_api.on_volume = self._remote_set_volume
        self.remote_api.get_playlist = lambda: list(self.source_mgr._playlist)
        self.remote_api.set_playlist = self.source_mgr.set_playlist
        self.remote_api.on_playlist_add = self.source_mgr.add_to_playlist
        self.remote_api.on_playlist_remove = self.source_mgr.remove_from_playlist
        self.remote_api.get_history = lambda limit: [
            {
                "timestamp": e.timestamp,
                "source": e.source,
                "track": e.track,
                "duration": e.duration,
            }
            for e in self.history.recent(limit)
        ]
        self.remote_api.start()

    def _remote_set_volume(self, value: float) -> None:
        try:
            self.engine.master_volume = float(value)
        except Exception:
            pass

    def _on_engine_output(self, audio):
        try:
            self.streamer.push_audio(audio)
        except Exception:
            pass
        try:
            self.recorder.push_audio(audio)
        except Exception:
            pass

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

    def _log_startup_diagnostics(self) -> None:
        """Log startup info to the log panel so user can see what's working."""
        from core.radio_stream import FFMPEG_EXE
        import sys, os

        self.log_panel.log_info("StreamSwitcher Pro запущен")

        # Audio devices
        devices = AudioEngine.get_devices()
        if devices:
            self.log_panel.log_info(f"Аудиоустройств найдено: {len(devices)}")
        else:
            self.log_panel.log_error(
                "Аудиоустройства не найдены — sounddevice не работает. "
                "Воспроизведение и запись недоступны."
            )

        # ffmpeg
        if FFMPEG_EXE:
            self.log_panel.log_info(f"ffmpeg: {FFMPEG_EXE}")
        else:
            self.log_panel.log_error(
                "ffmpeg не найден — интернет-радио не будет работать. "
                "Установите imageio-ffmpeg или добавьте ffmpeg в PATH."
            )

        # lameenc
        try:
            import lameenc
            self.log_panel.log_info("MP3 энкодер (lameenc): OK")
        except ImportError:
            self.log_panel.log_error(
                "lameenc не найден — вещание MP3 недоступно."
            )

    def closeEvent(self, event):
        """Clean shutdown: persist config, then stop subsystems."""
        try:
            self._persist_config()
        except Exception:
            pass
        try:
            self.recorder.stop()
        except Exception:
            pass
        self.engine.stop()
        self.source_mgr.stop()
        self.scheduler.stop()
        self.streamer.stop()
        self.remote_api.stop()
        event.accept()

    # ------------------------------------------------------------------ #
    #  PERSISTENCE / HOTKEYS                                              #
    # ------------------------------------------------------------------ #

    def _install_hotkeys(self) -> None:
        """Bind keyboard shortcuts."""
        bindings = [
            ("Space", self._toggle_play),
            ("M", lambda: self._on_mute(not self._muted)),
            ("Ctrl+N", self._on_next),
            ("Right", self._on_next),
            ("Ctrl+1", lambda: self._switch_source(AudioSource.LIVE_INPUT)),
            ("Ctrl+2", lambda: self._switch_source(AudioSource.MP3_FILE)),
            ("Ctrl+3", lambda: self._switch_source(AudioSource.INTERNET_RADIO)),
            ("Ctrl+S", lambda: self._persist_config(show_status=True)),
        ]
        for keyseq, handler in bindings:
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.activated.connect(handler)

    def _toggle_play(self) -> None:
        if self.engine._running:
            self._on_stop()
        else:
            self._on_play()

    def _apply_loaded_config(self) -> None:
        """Apply persisted state to the live components."""
        if self.config.playlist:
            self.source_mgr.set_playlist(list(self.config.playlist))
        if self.config.radio_url:
            self.source_mgr.set_radio_url(self.config.radio_url)
            self.radio_panel.set_url_text(self.config.radio_url)
        try:
            self.engine.master_volume = float(self.config.master_volume)
        except Exception:
            pass
        # Populate stream panel with persisted broadcast settings.
        try:
            self.stream_panel.apply_config(self.config.streaming)
        except Exception:
            pass

    def _persist_config(self, show_status: bool = False) -> None:
        """Snapshot live state and write to disk."""
        self.config.playlist = list(self.source_mgr._playlist)
        self.config.radio_url = self.source_mgr._radio_url or ""
        try:
            self.config.master_volume = float(self.engine.master_volume)
        except Exception:
            pass
        # Snapshot broadcast settings from the stream panel.
        try:
            for key, value in self.stream_panel.collect_config_dict().items():
                setattr(self.config.streaming, key, value)
        except Exception:
            pass
        # Snapshot multi-channel configs.
        try:
            from dataclasses import asdict
            self.config.channels = [
                asdict(ch.snapshot_config())
                for ch in self._channel_mgr.channels
            ]
        except Exception:
            pass
        self.config.save(self._config_path)
        if show_status:
            self._show_status(
                f"Config saved to {self._config_path or AppConfig.default_config_path()}"
            )

    # ------------------------------------------------------------------ #
    #  PLAYLIST IMPORT / EXPORT                                           #
    # ------------------------------------------------------------------ #

    def _import_playlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import playlist", "", "Playlists (*.m3u *.m3u8 *.pls)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            ext = os.path.splitext(path)[1].lower()
            tracks = parse_pls(content) if ext == ".pls" else parse_m3u(content)
        except Exception as exc:
            self._show_error(f"Failed to import playlist: {exc}")
            return
        for track in tracks:
            self.source_mgr.add_to_playlist(track.path)
        self._show_status(
            f"Imported {len(tracks)} tracks from {os.path.basename(path)}"
        )

    def _export_playlist(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self, "Export playlist", "playlist.m3u",
            "M3U Playlist (*.m3u);;PLS Playlist (*.pls)"
        )
        if not path:
            return
        try:
            tracks = [enrich_track(Track(path=p)) for p in self.source_mgr._playlist]
            if path.lower().endswith(".pls") or "PLS" in selected:
                payload = write_pls(tracks)
            else:
                payload = write_m3u(tracks)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except Exception as exc:
            self._show_error(f"Failed to export playlist: {exc}")
            return
        self._show_status(
            f"Exported {len(self.source_mgr._playlist)} tracks to {path}"
        )
