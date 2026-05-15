"""Radio panel — editable list of internet-radio presets.

Lets the user add / edit / remove / reorder stations, import / export the
list, and play any station either from the URL field or by double-clicking
a preset. Mirrors the workflow RadioBoss uses for its station list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Edit dialog
# ---------------------------------------------------------------------------


@dataclass
class _PresetDraft:
    name: str
    url: str


class PresetEditorDialog(QDialog):
    """Modal editor for a single radio preset (name + URL)."""

    def __init__(self, parent: QWidget | None = None,
                 preset: _PresetDraft | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Радиостанция")
        self.setModal(True)
        self.resize(440, 140)

        form = QFormLayout(self)
        self.name_edit = QLineEdit(preset.name if preset else "")
        self.name_edit.setPlaceholderText("Моя любимая станция")
        form.addRow("Название:", self.name_edit)

        self.url_edit = QLineEdit(preset.url if preset else "")
        self.url_edit.setPlaceholderText("http://stream.example.com:8000/stream")
        form.addRow("URL:", self.url_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Проверка", "Укажите название.")
            return
        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Проверка",
                "URL должен начинаться с http:// или https://"
            )
            return
        self.accept()

    def result_preset(self) -> _PresetDraft:
        return _PresetDraft(
            name=self.name_edit.text().strip(),
            url=self.url_edit.text().strip(),
        )


# ---------------------------------------------------------------------------
# Radio panel
# ---------------------------------------------------------------------------


class RadioPanel(QWidget):
    """Editable list of radio presets + URL/Play controls.

    Emits ``play_requested(url)`` when the user wants to start playback and
    ``presets_changed(list[dict])`` whenever the in-panel preset list is
    mutated (so the host window can persist the change).
    """

    play_requested = Signal(str)
    presets_changed = Signal(list)    # list[dict] with 'name' / 'url'

    COLUMNS = ("Название", "URL")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # --- URL + Play -------------------------------------------------
        url_group = QGroupBox("URL интернет-радио")
        url_layout = QVBoxLayout(url_group)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://stream.example.com:8000/stream")
        self.url_edit.returnPressed.connect(self._on_play_from_url)
        url_row.addWidget(self.url_edit, 1)

        play_btn = QPushButton("▶ Слушать")
        play_btn.setObjectName("btn_play")
        play_btn.clicked.connect(self._on_play_from_url)
        url_row.addWidget(play_btn)

        url_layout.addLayout(url_row)

        self.buffer_label = QLabel("")
        self.buffer_label.setStyleSheet("color: #d29922;")
        self.buffer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_layout.addWidget(self.buffer_label)

        outer.addWidget(url_group)

        # --- Preset list + toolbar --------------------------------------
        presets_group = QGroupBox("Пресеты")
        presets_layout = QVBoxLayout(presets_group)

        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("➕ Добавить")
        self.add_btn.clicked.connect(self._on_add)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏ Изменить")
        self.edit_btn.clicked.connect(self._on_edit)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("🗑 Удалить")
        self.remove_btn.clicked.connect(self._on_remove)
        toolbar.addWidget(self.remove_btn)

        toolbar.addSpacing(12)

        self.up_btn = QPushButton("⬆")
        self.up_btn.setToolTip("Переместить вверх")
        self.up_btn.clicked.connect(lambda: self._move_selected(-1))
        toolbar.addWidget(self.up_btn)

        self.down_btn = QPushButton("⬇")
        self.down_btn.setToolTip("Переместить вниз")
        self.down_btn.clicked.connect(lambda: self._move_selected(1))
        toolbar.addWidget(self.down_btn)

        toolbar.addSpacing(12)

        self.import_btn = QPushButton("📂 Импорт")
        self.import_btn.clicked.connect(self._on_import)
        toolbar.addWidget(self.import_btn)

        self.export_btn = QPushButton("💾 Экспорт")
        self.export_btn.clicked.connect(self._on_export)
        toolbar.addWidget(self.export_btn)

        toolbar.addStretch()
        presets_layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._on_play_selected)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        presets_layout.addWidget(self.table)
        outer.addWidget(presets_group, 1)

        # Keyboard shortcuts that work while focus is on the table.
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.table,
                  activated=self._on_play_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self.table,
                  activated=self._on_play_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table,
                  activated=self._on_remove)

        self._update_buttons()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_url_text(self, url: str) -> None:
        self.url_edit.setText(url or "")

    def url_text(self) -> str:
        return self.url_edit.text().strip()

    def set_presets(self, presets: list) -> None:
        """Replace the preset list. Accepts dataclasses or dicts with
        ``name`` / ``url`` attributes."""
        self.table.setRowCount(0)
        for p in presets or []:
            name = getattr(p, "name", None) or p.get("name", "")
            url = getattr(p, "url", None) or p.get("url", "")
            self._append_row(name, url)
        self._update_buttons()

    def presets(self) -> list[dict]:
        """Return the current preset list as plain dicts."""
        out: list[dict] = []
        for row in range(self.table.rowCount()):
            out.append({
                "name": self.table.item(row, 0).text(),
                "url": self.table.item(row, 1).text(),
            })
        return out

    def set_buffering(self, is_buffering: bool) -> None:
        self.buffer_label.setText("⏳ Буферизация..." if is_buffering else "")

    # ------------------------------------------------------------------ #
    #  Actions                                                             #
    # ------------------------------------------------------------------ #

    def _on_play_from_url(self) -> None:
        url = self.url_text()
        if url:
            self.play_requested.emit(url)

    def _on_play_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        url = self.table.item(row, 1).text()
        self.url_edit.setText(url)
        self.play_requested.emit(url)

    def _on_add(self) -> None:
        dlg = PresetEditorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            p = dlg.result_preset()
            self._append_row(p.name, p.url)
            self._emit_change()

    def _on_edit(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        current = _PresetDraft(
            name=self.table.item(row, 0).text(),
            url=self.table.item(row, 1).text(),
        )
        dlg = PresetEditorDialog(self, preset=current)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            p = dlg.result_preset()
            self.table.item(row, 0).setText(p.name)
            self.table.item(row, 1).setText(p.url)
            self._emit_change()

    def _on_remove(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Удаление",
            f"Удалить станцию «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.table.removeRow(row)
            self._emit_change()
            self._update_buttons()

    def _move_selected(self, delta: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.table.rowCount():
            return
        self._swap_rows(row, new_row)
        self.table.selectRow(new_row)
        self._emit_change()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт пресетов", "",
            "Presets (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.warning(self, "Импорт", f"Не удалось прочитать файл: {e}")
            return
        if not isinstance(data, list):
            QMessageBox.warning(self, "Импорт", "Ожидался JSON-массив пресетов.")
            return
        # Validate shape — accept both {name, url} and {title, stream_url}.
        cleaned: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("title") or ""
            url = item.get("url") or item.get("stream_url") or ""
            if name and url:
                cleaned.append({"name": str(name), "url": str(url)})
        for p in cleaned:
            self._append_row(p["name"], p["url"])
        self._emit_change()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт пресетов", "presets.json",
            "Presets (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.presets(), fh, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", f"Не удалось записать файл: {e}")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _append_row(self, name: str, url: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item_name = QTableWidgetItem(f"📻 {name}" if name and not name.startswith("📻") else name)
        item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item_name.setData(Qt.ItemDataRole.UserRole, name)
        self.table.setItem(row, 0, item_name)
        item_url = QTableWidgetItem(url)
        item_url.setFlags(item_url.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, item_url)
        self._update_buttons()

    def _swap_rows(self, a: int, b: int) -> None:
        for col in range(self.table.columnCount()):
            text_a = self.table.item(a, col).text()
            text_b = self.table.item(b, col).text()
            self.table.item(a, col).setText(text_b)
            self.table.item(b, col).setText(text_a)

    def _update_buttons(self) -> None:
        row = self.table.currentRow()
        has_selection = row >= 0
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)
        self.up_btn.setEnabled(has_selection and row > 0)
        self.down_btn.setEnabled(
            has_selection and row < self.table.rowCount() - 1
        )

    def _emit_change(self) -> None:
        self.presets_changed.emit(self.presets())
