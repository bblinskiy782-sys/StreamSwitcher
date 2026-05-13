"""
Dark Mode Pro stylesheet for StreamSwitcher.
"""

DARK_STYLESHEET = """
/* ===== Global ===== */
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
}

QMainWindow {
    background-color: #0d1117;
}

/* ===== GroupBox ===== */
QGroupBox {
    border: 1px solid #21262d;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
    color: #58a6ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #58a6ff;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 6px 14px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #58a6ff;
    color: #58a6ff;
}
QPushButton:pressed {
    background-color: #1f6feb;
    border-color: #1f6feb;
    color: #ffffff;
}
QPushButton:checked {
    background-color: #1f6feb;
    border-color: #388bfd;
    color: #ffffff;
}
QPushButton:disabled {
    background-color: #161b22;
    color: #484f58;
    border-color: #21262d;
}

/* Source buttons */
QPushButton#btn_live {
    background-color: #1a3a1a;
    border-color: #2ea043;
    color: #3fb950;
    font-weight: bold;
}
QPushButton#btn_live:checked {
    background-color: #2ea043;
    color: #ffffff;
}
QPushButton#btn_mp3 {
    background-color: #1a2a3a;
    border-color: #1f6feb;
    color: #58a6ff;
    font-weight: bold;
}
QPushButton#btn_mp3:checked {
    background-color: #1f6feb;
    color: #ffffff;
}
QPushButton#btn_radio {
    background-color: #2a1a3a;
    border-color: #8957e5;
    color: #a371f7;
    font-weight: bold;
}
QPushButton#btn_radio:checked {
    background-color: #8957e5;
    color: #ffffff;
}

/* Transport buttons */
QPushButton#btn_play  { background-color: #1a3a1a; border-color: #2ea043; color: #3fb950; }
QPushButton#btn_play:hover  { background-color: #2ea043; color: #fff; }
QPushButton#btn_stop  { background-color: #3a1a1a; border-color: #f85149; color: #f85149; }
QPushButton#btn_stop:hover  { background-color: #f85149; color: #fff; }
QPushButton#btn_next  { background-color: #1a2a3a; border-color: #1f6feb; color: #58a6ff; }
QPushButton#btn_next:hover  { background-color: #1f6feb; color: #fff; }
QPushButton#btn_mute  { background-color: #2a2a1a; border-color: #d29922; color: #d29922; }
QPushButton#btn_mute:checked { background-color: #d29922; color: #000; }

/* ===== Sliders ===== */
QSlider::groove:horizontal {
    height: 4px;
    background: #21262d;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #58a6ff;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #1f6feb;
    border-radius: 2px;
}
QSlider::groove:vertical {
    width: 4px;
    background: #21262d;
    border-radius: 2px;
}
QSlider::handle:vertical {
    background: #58a6ff;
    border: none;
    width: 14px;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
}
QSlider::sub-page:vertical {
    background: #1f6feb;
    border-radius: 2px;
}

/* ===== ComboBox ===== */
QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 8px;
    color: #c9d1d9;
    min-height: 26px;
}
QComboBox:hover { border-color: #58a6ff; }
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #58a6ff;
    width: 0;
    height: 0;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    color: #c9d1d9;
}

/* ===== LineEdit ===== */
QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 8px;
    color: #c9d1d9;
    min-height: 26px;
}
QLineEdit:focus { border-color: #58a6ff; }

/* ===== SpinBox / TimeEdit ===== */
QSpinBox, QDoubleSpinBox, QTimeEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 8px;
    color: #c9d1d9;
    min-height: 26px;
}
QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus { border-color: #58a6ff; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {
    background-color: #21262d;
    border: none;
    width: 16px;
}

/* ===== TableWidget ===== */
QTableWidget {
    background-color: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    gridline-color: #21262d;
    color: #c9d1d9;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #161b22;
    border: none;
    border-bottom: 1px solid #21262d;
    border-right: 1px solid #21262d;
    padding: 6px 8px;
    color: #8b949e;
    font-weight: bold;
}

/* ===== ListWidget ===== */
QListWidget {
    background-color: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    color: #c9d1d9;
}
QListWidget::item { padding: 4px 8px; }
QListWidget::item:selected { background-color: #1f6feb; color: #fff; }
QListWidget::item:hover { background-color: #161b22; }

/* ===== TabWidget ===== */
QTabWidget::pane {
    border: 1px solid #21262d;
    border-radius: 0 6px 6px 6px;
    background-color: #0d1117;
}
QTabBar::tab {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 6px 16px;
    color: #8b949e;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #58a6ff;
    border-color: #21262d;
}
QTabBar::tab:hover { color: #c9d1d9; }

/* ===== ScrollBar ===== */
QScrollBar:vertical {
    background: #0d1117;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #58a6ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #0d1117;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background: #58a6ff; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ===== CheckBox ===== */
QCheckBox { color: #c9d1d9; spacing: 6px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background: #161b22;
}
QCheckBox::indicator:checked {
    background: #1f6feb;
    border-color: #1f6feb;
}

/* ===== Label ===== */
QLabel { color: #c9d1d9; }
QLabel#label_source_name { color: #3fb950; font-weight: bold; font-size: 11pt; }
QLabel#label_uptime { color: #58a6ff; }
QLabel#label_listeners { color: #a371f7; }
QLabel#label_clip { color: #f85149; font-weight: bold; }

/* ===== StatusBar ===== */
QStatusBar {
    background-color: #161b22;
    border-top: 1px solid #21262d;
    color: #8b949e;
}
QStatusBar::item { border: none; }

/* ===== ToolTip ===== */
QToolTip {
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 4px 8px;
    border-radius: 4px;
}

/* ===== Splitter ===== */
QSplitter::handle { background-color: #21262d; }
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
"""
