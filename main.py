"""
StreamSwitcher - Professional Audio Broadcasting Station
Entry point
"""
import os
import sys

# Ensure the app directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("StreamSwitcher")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("StreamSwitcher")

    # Set default font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
