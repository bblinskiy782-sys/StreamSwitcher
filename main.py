"""StreamSwitcher — Professional Audio Broadcasting Station.

Entry point. By default starts the PySide6 GUI; ``--headless`` runs the
engine, scheduler, source manager and Remote API without a window — useful
for running on a server / Raspberry Pi / CI smoke tests.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

# Ensure the app directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="streamswitcher")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without GUI (engine + Remote API + scheduler only).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.json (default: OS-appropriate location).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Remote API port (overrides config).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Remote API Bearer token (overrides config).",
    )
    return parser.parse_args(argv)


def run_headless(args: argparse.Namespace) -> int:
    """Run StreamSwitcher without a GUI."""
    from core.audio_engine import AudioEngine
    from core.config import AppConfig
    from core.history import HistoryEntry, HistoryLog
    from core.remote_api import RemoteAPI
    from core.scheduler import Scheduler
    from core.source_manager import AudioSource, SourceManager

    cfg = AppConfig.load(args.config)
    port = args.port if args.port is not None else cfg.remote_api_port
    api_key = args.api_key if args.api_key is not None else cfg.remote_api_key

    engine = AudioEngine(sample_rate=cfg.sample_rate)
    source_manager = SourceManager()
    scheduler = Scheduler()
    history = HistoryLog()
    api = RemoteAPI(port=port, api_key=api_key)

    if cfg.playlist:
        source_manager.set_playlist(cfg.playlist)
    if cfg.radio_url:
        source_manager.set_radio_url(cfg.radio_url)

    api.get_status = lambda: {
        "source": engine.current_source.value if engine.current_source else "idle",
        "running": engine._running,
        "playlist_size": len(source_manager._playlist),
        "history_size": len(history.entries),
    }
    api.on_play = lambda: engine.start()
    api.on_stop = lambda: engine.stop()
    api.on_mute = lambda: setattr(engine, "muted", not getattr(engine, "muted", False))
    api.on_next = lambda: source_manager.next_track()
    api.on_volume = lambda v: setattr(engine, "master_volume", v)
    api.on_source_switch = lambda s: engine.switch_source(AudioSource(s))
    api.get_playlist = lambda: list(source_manager._playlist)
    api.set_playlist = lambda paths: source_manager.set_playlist(paths)
    api.on_playlist_add = lambda p: source_manager.add_to_playlist(p)
    api.on_playlist_remove = lambda i: source_manager.remove_from_playlist(i)
    api.get_history = lambda limit: [
        {
            "timestamp": e.timestamp,
            "source": e.source,
            "track": e.track,
            "duration": e.duration,
        }
        for e in history.recent(limit)
    ]

    def _on_track_changed(name: str) -> None:
        history.append(HistoryEntry.now(source="mp3_file", track=name))

    source_manager.track_changed.connect(_on_track_changed)

    api.start()
    scheduler.start()
    print(f"[headless] Remote API listening on http://0.0.0.0:{port}")
    print(f"[headless] Config: {args.config or 'default'}")

    stop_event = {"value": False}

    def _shutdown(*_: object) -> None:
        stop_event["value"] = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not stop_event["value"]:
            time.sleep(0.5)
    finally:
        scheduler.stop()
        engine.stop()
        api.stop()
        try:
            cfg.save(args.config)
        except Exception:
            pass
    return 0


def run_gui() -> int:
    """Run the standard PySide6 GUI application."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("StreamSwitcher")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("StreamSwitcher")
    app.setFont(QFont("Segoe UI", 9))

    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.headless:
        return run_headless(args)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
