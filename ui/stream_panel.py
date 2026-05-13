"""
Stream Panel - Icecast/Shoutcast streaming configuration and control.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QSpinBox,
    QFormLayout, QCheckBox
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor


class StreamPanel(QWidget):
    """
    Configuration and control for Icecast/Shoutcast streaming.
    """
    connect_requested = Signal(dict)    # config dict
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- Server config ----
        config_group = QGroupBox("Настройки сервера (Icecast/Shoutcast)")
        form = QFormLayout(config_group)
        form.setSpacing(8)

        self.host_edit = QLineEdit("localhost")
        self.host_edit.setPlaceholderText("hostname или IP")
        form.addRow("Хост:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8000)
        form.addRow("Порт:", self.port_spin)

        self.mount_edit = QLineEdit("/stream")
        self.mount_edit.setPlaceholderText("/mountpoint")
        form.addRow("Маунт:", self.mount_edit)

        self.password_edit = QLineEdit("hackme")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.password_edit)

        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(32, 320)
        self.bitrate_spin.setValue(128)
        self.bitrate_spin.setSuffix(" kbps")
        form.addRow("Битрейт:", self.bitrate_spin)

        self.name_edit = QLineEdit("StreamSwitcher")
        form.addRow("Название:", self.name_edit)

        self.genre_edit = QLineEdit("Various")
        form.addRow("Жанр:", self.genre_edit)

        layout.addWidget(config_group)

        # ---- Status & control ----
        status_group = QGroupBox("Статус стрима")
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

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("🔴 Начать вещание")
        self.connect_btn.setObjectName("btn_play")
        self.connect_btn.clicked.connect(self._on_connect_click)
        btn_row.addWidget(self.connect_btn)
        btn_row.addStretch()
        status_layout.addLayout(btn_row)

        layout.addWidget(status_group)
        layout.addStretch()

    def _on_connect_click(self):
        if self._connected:
            self.disconnect_requested.emit()
        else:
            config = {
                "host": self.host_edit.text().strip(),
                "port": self.port_spin.value(),
                "mount": self.mount_edit.text().strip(),
                "password": self.password_edit.text(),
                "bitrate": self.bitrate_spin.value(),
                "name": self.name_edit.text().strip(),
                "genre": self.genre_edit.text().strip(),
            }
            self.connect_requested.emit(config)

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
