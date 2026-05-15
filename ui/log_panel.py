"""Log panel — event log table like RadioBoss.

Shows timestamped events: track changes, schedule actions, silence detection,
errors (highlighted in red), failover, streaming status, etc.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LogLevel:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# Colors matching RadioBoss style.
_COLORS = {
    LogLevel.INFO: None,                    # default text color
    LogLevel.WARNING: QColor("#d29922"),     # amber
    LogLevel.ERROR: QColor("#f85149"),       # red
}

MAX_LOG_ENTRIES = 2000


class LogPanel(QWidget):
    """Scrollable event log table with Time / Title / Date columns."""

    COLUMNS = ("Время", "Событие", "Дата")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        self.clear_btn = QPushButton("🗑 Очистить лог")
        self.clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(self.clear_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background: #0d1117; alternate-background-color: #161b22; "
            "color: #c9d1d9; gridline-color: #21262d; }"
            "QHeaderView::section { background: #161b22; color: #8b949e; "
            "border: 1px solid #21262d; padding: 4px; }"
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @Slot(str)
    @Slot(str, str)
    def log(self, message: str, level: str = LogLevel.INFO) -> None:
        """Append a log entry. Thread-safe via Qt signal if needed."""
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%d.%m.%Y")

        # Cap entries.
        if self.table.rowCount() >= MAX_LOG_ENTRIES:
            self.table.removeRow(0)

        row = self.table.rowCount()
        self.table.insertRow(row)

        color = _COLORS.get(level)
        brush = QBrush(color) if color else None

        for col, text in enumerate((time_str, message, date_str)):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if brush:
                item.setForeground(brush)
            self.table.setItem(row, col, item)

        # Auto-scroll to bottom.
        self.table.scrollToBottom()

    def log_info(self, message: str) -> None:
        self.log(message, LogLevel.INFO)

    def log_warning(self, message: str) -> None:
        self.log(message, LogLevel.WARNING)

    def log_error(self, message: str) -> None:
        self.log(message, LogLevel.ERROR)

    def clear(self) -> None:
        self.table.setRowCount(0)
