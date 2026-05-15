"""Stream Panel — broadcast configuration and control.

Supports two broadcast modes, like RadioBoss does:

* ``Встроенный сервер`` — slušateli connect directly to us on
  ``http://<ip>:<port>/``, no external server required.
* ``Icecast/SHOUTcast`` — push to an external Icecast 2 / Shoutcast server
  (``host`` / ``port`` / ``mount`` / ``password``).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


MODE_BUILTIN = "builtin"
MODE_ICECAST = "icecast"


class StreamPanel(QWidget):
    """Configuration and control for broadcasting."""

    connect_requested = Signal(dict)    # config dict
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- Mode selector ----
        mode_group = QGroupBox("Тип сервера")
        mode_form = QFormLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Встроенный сервер (прямое подключение)",
                                MODE_BUILTIN)
        self.mode_combo.addItem("Icecast / SHOUTcast (внешний сервер)",
                                MODE_ICECAST)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_form.addRow("Режим:", self.mode_combo)
        layout.addWidget(mode_group)

        # ---- Stacked config panes ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_builtin_pane())     # index 0
        self.stack.addWidget(self._build_icecast_pane())     # index 1
        layout.addWidget(self.stack)

        # ---- Station info (shared) ----
        info_group = QGroupBox("Информация о станции")
        info_form = QFormLayout(info_group)
        self.name_edit = QLineEdit("StreamSwitcher")
        info_form.addRow("Название:", self.name_edit)
        self.genre_edit = QLineEdit("Various")
        info_form.addRow("Жанр:", self.genre_edit)
        layout.addWidget(info_group)

        # ---- Status & control ----
        status_group = QGroupBox("Статус вещания")
        status_layout = QVBoxLayout(status_group)

        info_row = QHBoxLayout()
        self.status_label = QLabel("● Отключено")
        self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
        info_row.addWidget(self.status_label)
        info_row.addStretch()

        self.listeners_label = QLabel("Слушателей: 0")
        self.listeners_label.setStyleSheet("color: #a371f7;")
        info_row.addWidget(self.listeners_label)

        self.bytes_label = QLabel("Отправлено: 0 MB")
        self.bytes_label.setStyleSheet("color: #8b949e;")
        info_row.addWidget(self.bytes_label)

        status_layout.addLayout(info_row)

        # Contextual URL hint (built-in mode only).
        self.url_hint = QLabel("")
        self.url_hint.setStyleSheet("color: #58a6ff; font-size: 8pt;")
        self.url_hint.setWordWrap(True)
        status_layout.addWidget(self.url_hint)

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("🔴 Начать вещание")
        self.connect_btn.setObjectName("btn_play")
        self.connect_btn.clicked.connect(self._on_connect_click)
        btn_row.addWidget(self.connect_btn)
        btn_row.addStretch()
        status_layout.addLayout(btn_row)

        layout.addWidget(status_group)
        layout.addStretch()

        self._on_mode_changed(0)

    def _build_builtin_pane(self) -> QWidget:
        pane = QGroupBox("Настройки встроенного сервера")
        form = QFormLayout(pane)

        self.builtin_bind_edit = QLineEdit("0.0.0.0")
        self.builtin_bind_edit.setPlaceholderText(
            "0.0.0.0 — слушать на всех интерфейсах"
        )
        form.addRow("Bind:", self.builtin_bind_edit)

        self.builtin_port_spin = QSpinBox()
        self.builtin_port_spin.setRange(1, 65535)
        self.builtin_port_spin.setValue(8000)
        form.addRow("Порт:", self.builtin_port_spin)

        self.builtin_bitrate_spin = QSpinBox()
        self.builtin_bitrate_spin.setRange(32, 320)
        self.builtin_bitrate_spin.setValue(128)
        self.builtin_bitrate_spin.setSuffix(" kbps")
        form.addRow("Битрейт:", self.builtin_bitrate_spin)

        self.builtin_public_check = QCheckBox(
            "Публичная (icy-pub=1)"
        )
        form.addRow("", self.builtin_public_check)
        return pane

    def _build_icecast_pane(self) -> QWidget:
        pane = QGroupBox("Настройки Icecast / SHOUTcast")
        form = QFormLayout(pane)

        self.host_edit = QLineEdit("localhost")
        self.host_edit.setPlaceholderText("hostname или IP")
        form.addRow("Хост:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8000)
        form.addRow("Порт:", self.port_spin)

        self.mount_edit = QLineEdit("/stream")
        self.mount_edit.setPlaceholderText("/mountpoint")
        form.addRow("Mount:", self.mount_edit)

        self.password_edit = QLineEdit("hackme")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.password_edit)

        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(32, 320)
        self.bitrate_spin.setValue(128)
        self.bitrate_spin.setSuffix(" kbps")
        form.addRow("Битрейт:", self.bitrate_spin)
        return pane

    # ------------------------------------------------------------------ #
    #  Events                                                              #
    # ------------------------------------------------------------------ #

    def _on_mode_changed(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self._update_url_hint()

    def _update_url_hint(self) -> None:
        if self._current_mode() == MODE_BUILTIN:
            port = self.builtin_port_spin.value()
            bind = self.builtin_bind_edit.text().strip() or "0.0.0.0"
            host_hint = "<IP-адрес компьютера>" if bind == "0.0.0.0" else bind
            self.url_hint.setText(
                f"Слушатели подключаются на http://{host_hint}:{port}/"
            )
        else:
            self.url_hint.setText("")

    def _current_mode(self) -> str:
        return self.mode_combo.currentData() or MODE_BUILTIN

    def _on_connect_click(self):
        if self._connected:
            self.disconnect_requested.emit()
            return
        mode = self._current_mode()
        config: dict = {
            "mode": mode,
            "name": self.name_edit.text().strip() or "StreamSwitcher",
            "genre": self.genre_edit.text().strip() or "Various",
        }
        if mode == MODE_BUILTIN:
            config.update({
                "builtin_port": self.builtin_port_spin.value(),
                "builtin_bind_host": self.builtin_bind_edit.text().strip() or "0.0.0.0",
                "bitrate": self.builtin_bitrate_spin.value(),
                "builtin_public": self.builtin_public_check.isChecked(),
            })
        else:
            config.update({
                "host": self.host_edit.text().strip(),
                "port": self.port_spin.value(),
                "mount": self.mount_edit.text().strip(),
                "password": self.password_edit.text(),
                "bitrate": self.bitrate_spin.value(),
            })
        self.connect_requested.emit(config)

    # ------------------------------------------------------------------ #
    #  External state updates                                              #
    # ------------------------------------------------------------------ #

    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self.status_label.setText("● Вещание")
            self.status_label.setStyleSheet("color: #3fb950; font-weight: bold;")
            self.connect_btn.setText("⏹ Остановить вещание")
        else:
            self.status_label.setText("● Отключено")
            self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
            self.connect_btn.setText("🔴 Начать вещание")

    def update_listeners(self, count: int):
        self.listeners_label.setText(f"Слушателей: {count}")

    def update_bytes_sent(self, total_bytes: int):
        mb = total_bytes / (1024 * 1024)
        self.bytes_label.setText(f"Отправлено: {mb:.1f} MB")

    # ------------------------------------------------------------------ #
    #  Config load / save                                                  #
    # ------------------------------------------------------------------ #

    def apply_config(self, cfg) -> None:
        """Populate UI from :class:`core.config.StreamingConfig`."""
        mode = getattr(cfg, "mode", MODE_ICECAST) or MODE_ICECAST
        mode_index = 0 if mode == MODE_BUILTIN else 1
        self.mode_combo.setCurrentIndex(mode_index)

        self.name_edit.setText(getattr(cfg, "stream_name", "StreamSwitcher"))
        self.genre_edit.setText(getattr(cfg, "genre", "Various"))

        self.builtin_bind_edit.setText(getattr(cfg, "builtin_bind_host", "0.0.0.0"))
        self.builtin_port_spin.setValue(getattr(cfg, "builtin_port", 8000))
        self.builtin_bitrate_spin.setValue(getattr(cfg, "bitrate", 128))
        self.builtin_public_check.setChecked(bool(getattr(cfg, "builtin_public", False)))

        self.host_edit.setText(getattr(cfg, "host", "localhost"))
        self.port_spin.setValue(getattr(cfg, "port", 8000))
        self.mount_edit.setText(getattr(cfg, "mount", "/stream"))
        self.password_edit.setText(getattr(cfg, "password", ""))
        self.bitrate_spin.setValue(getattr(cfg, "bitrate", 128))
        self._update_url_hint()

    def collect_config_dict(self) -> dict:
        """Return a dict suitable for updating ``StreamingConfig``."""
        mode = self._current_mode()
        return {
            "mode": mode,
            "host": self.host_edit.text().strip(),
            "port": self.port_spin.value(),
            "mount": self.mount_edit.text().strip(),
            "password": self.password_edit.text(),
            "builtin_port": self.builtin_port_spin.value(),
            "builtin_bind_host": self.builtin_bind_edit.text().strip() or "0.0.0.0",
            "builtin_public": self.builtin_public_check.isChecked(),
            "bitrate": (
                self.builtin_bitrate_spin.value() if mode == MODE_BUILTIN
                else self.bitrate_spin.value()
            ),
            "stream_name": self.name_edit.text().strip() or "StreamSwitcher",
            "genre": self.genre_edit.text().strip() or "Various",
        }
