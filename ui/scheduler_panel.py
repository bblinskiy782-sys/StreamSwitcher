"""
Scheduler Panel - UI for managing timed events.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QTimeEdit, QComboBox, QLineEdit, QCheckBox, QHeaderView,
    QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtGui import QColor


class SchedulerPanel(QWidget):
    """
    Panel for creating and managing scheduled events.
    """
    entry_added = Signal(str, str, str, bool)    # time, action, target, repeat
    entry_removed = Signal(int)                   # entry id
    entry_toggled = Signal(int)                   # entry id
    entry_edited = Signal(int, str, str, str, bool)  # id, time, action, target, repeat

    ACTIONS = [
        ("play_file", "▶ Воспроизвести файл"),
        ("play_radio", "📻 Включить радио"),
        ("switch_live", "🎤 Переключить на вход"),
        ("stop", "⏹ Остановить"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []  # list of ScheduleEntry
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- Add entry form ----
        form_group = QGroupBox("Добавить событие")
        form_layout = QHBoxLayout(form_group)
        form_layout.setSpacing(8)

        form_layout.addWidget(QLabel("Время:"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm:ss")
        self.time_edit.setTime(QTime.currentTime())
        self.time_edit.setMinimumWidth(90)
        form_layout.addWidget(self.time_edit)

        form_layout.addWidget(QLabel("Действие:"))
        self.action_combo = QComboBox()
        for key, label in self.ACTIONS:
            self.action_combo.addItem(label, key)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        form_layout.addWidget(self.action_combo)

        form_layout.addWidget(QLabel("Цель:"))
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("Путь к файлу или URL...")
        self.target_edit.setMinimumWidth(200)
        form_layout.addWidget(self.target_edit, 1)

        self.browse_btn = QPushButton("📂")
        self.browse_btn.setMaximumWidth(32)
        self.browse_btn.setToolTip("Выбрать файл")
        self.browse_btn.clicked.connect(self._browse_file)
        form_layout.addWidget(self.browse_btn)

        self.repeat_check = QCheckBox("Ежедневно")
        self.repeat_check.setChecked(True)
        form_layout.addWidget(self.repeat_check)

        add_btn = QPushButton("➕ Добавить")
        add_btn.clicked.connect(self._add_entry)
        form_layout.addWidget(add_btn)

        layout.addWidget(form_group)

        # ---- Schedule table ----
        table_group = QGroupBox("Расписание")
        table_layout = QVBoxLayout(table_group)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Время", "Действие", "Цель", "Повтор", "Статус"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(4, 70)
        self.table.setColumnWidth(5, 70)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.doubleClicked.connect(self._edit_selected)
        table_layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.toggle_btn = QPushButton("⏸ Вкл/Выкл")
        self.toggle_btn.clicked.connect(self._toggle_selected)
        self.remove_btn = QPushButton("🗑 Удалить")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.edit_btn = QPushButton("✏ Редактировать")
        self.edit_btn.clicked.connect(self._edit_selected_btn)
        btn_row.addWidget(self.toggle_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch()
        table_layout.addLayout(btn_row)

        layout.addWidget(table_group)

    def _on_action_changed(self, index: int):
        action = self.action_combo.currentData()
        needs_target = action in ("play_file", "play_radio")
        self.target_edit.setEnabled(needs_target)
        self.browse_btn.setEnabled(action == "play_file")

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать аудиофайл", "",
            "Audio Files (*.mp3 *.wav *.flac *.ogg *.aac);;All Files (*)"
        )
        if path:
            self.target_edit.setText(path)

    def _add_entry(self):
        time_str = self.time_edit.time().toString("HH:mm:ss")
        action = self.action_combo.currentData()
        target = self.target_edit.text().strip()
        repeat = self.repeat_check.isChecked()

        if action in ("play_file", "play_radio") and not target:
            QMessageBox.warning(self, "Ошибка", "Укажите цель для этого действия")
            return

        self.entry_added.emit(time_str, action, target, repeat)

    def _toggle_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        entry_id = int(self.table.item(row, 0).text())
        self.entry_toggled.emit(entry_id)

    def _remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        entry_id = int(self.table.item(row, 0).text())
        self.entry_removed.emit(entry_id)

    def update_entries(self, entries: list):
        """Refresh the table from a list of ScheduleEntry objects."""
        self._entries = entries
        self.table.setRowCount(0)
        action_labels = dict(self.ACTIONS)

        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(str(entry.id)))
            self.table.setItem(row, 1, QTableWidgetItem(entry.time_str))
            self.table.setItem(row, 2, QTableWidgetItem(
                action_labels.get(entry.action, entry.action)
            ))
            self.table.setItem(row, 3, QTableWidgetItem(entry.target or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(
                "✓" if entry.repeat_daily else "✗"
            ))

            status = "✅ Активно" if entry.enabled else "⏸ Пауза"
            status_item = QTableWidgetItem(status)
            if not entry.enabled:
                status_item.setForeground(QColor("#484f58"))
            self.table.setItem(row, 5, status_item)

    def highlight_fired(self, entry_id: int):
        """Flash a row when its event fires."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and int(item.text()) == entry_id:
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(QColor("#1f6feb"))
                break

    def _edit_selected_btn(self):
        row = self.table.currentRow()
        if row >= 0:
            self._open_edit_dialog(row)

    def _edit_selected(self, index):
        self._open_edit_dialog(index.row())

    def _open_edit_dialog(self, row: int):
        """Open edit dialog for the selected schedule entry."""
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]

        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Редактировать событие #{entry.id}")
        dlg.setMinimumWidth(400)
        form = QFormLayout(dlg)

        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm:ss")
        h, m, s = map(int, entry.time_str.split(":"))
        time_edit.setTime(QTime(h, m, s))
        form.addRow("Время:", time_edit)

        action_combo = QComboBox()
        for key, label in self.ACTIONS:
            action_combo.addItem(label, key)
        # Set current action
        for i in range(action_combo.count()):
            if action_combo.itemData(i) == entry.action:
                action_combo.setCurrentIndex(i)
                break
        form.addRow("Действие:", action_combo)

        target_edit = QLineEdit(entry.target or "")
        target_edit.setPlaceholderText("Путь к файлу или URL...")
        form.addRow("Цель:", target_edit)

        repeat_check = QCheckBox("Ежедневно")
        repeat_check.setChecked(entry.repeat_daily)
        form.addRow("", repeat_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_time = time_edit.time().toString("HH:mm:ss")
            new_action = action_combo.currentData()
            new_target = target_edit.text().strip()
            new_repeat = repeat_check.isChecked()
            self.entry_edited.emit(
                entry.id, new_time, new_action, new_target, new_repeat
            )
