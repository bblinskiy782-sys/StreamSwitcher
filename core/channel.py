"""Channel — one independent audio processing pipeline.

Each Channel owns its own:
* AudioEngine (input device → DSP → output device)
* SourceManager (playlist / internet radio)
* IcecastStreamer (broadcast to listeners)

Multiple Channels can run simultaneously in one application, each bound
to different audio devices and broadcasting on different ports. This is
the equivalent of running two RadioBoss instances side-by-side, but in
a single window.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from core._qt_compat import QObject, Signal
from core.audio_engine import AudioEngine, AudioSource, MixMode
from core.audio_router import AudioRouter, BusConfig, BusType, OutputBus
from core.source_manager import SourceManager
from core.streamer import IcecastStreamer


@dataclass
class ChannelConfig:
    """Serialisable configuration for one channel."""
    name: str = "Канал 1"
    input_device: int | None = None
    output_device: int | None = None
    sample_rate: int = 44100
    master_volume: float = 0.8

    # Multi-output routing (RadioBoss-style)
    monitor_device: int | None = None      # PFL / предпрослушка
    monitor_enabled: bool = False
    monitor_volume: float = 1.0
    aux1_device: int | None = None
    aux1_enabled: bool = False
    aux1_volume: float = 1.0
    aux2_device: int | None = None
    aux2_enabled: bool = False
    aux2_volume: float = 1.0

    # Streaming
    stream_mode: str = "builtin"       # "builtin" | "icecast"
    stream_builtin_port: int = 8000
    stream_host: str = "localhost"
    stream_port: int = 8000
    stream_mount: str = "/stream"
    stream_password: str = ""
    stream_bitrate: int = 128
    stream_name: str = "StreamSwitcher"

    # Source
    playlist: list[str] = field(default_factory=list)
    radio_url: str = ""
    source: str = "live_input"         # "live_input" | "mp3_file" | "internet_radio"

    # DSP
    eq_enabled: bool = False
    compressor_enabled: bool = False


class Channel(QObject):
    """One independent audio pipeline.

    Lifecycle::

        ch = Channel(config=ChannelConfig(...))
        ch.start()
        ...
        ch.stop()
    """

    # Signals forwarded from sub-components for UI binding.
    level_updated = Signal(float, float)
    source_changed = Signal(str)
    track_changed = Signal(str)
    error_occurred = Signal(str)
    stream_connected = Signal()
    stream_disconnected = Signal()
    listener_count_updated = Signal(int)
    bytes_sent_updated = Signal(int)

    def __init__(self, config: ChannelConfig | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config or ChannelConfig()

        self.engine = AudioEngine(self)
        self.source_mgr = SourceManager(
            sample_rate=self.engine.sample_rate,
            channels=self.engine.channels,
            blocksize=self.engine.blocksize,
            parent=self,
        )
        self.streamer = IcecastStreamer(self)

        # Multi-output router (Main + Monitor/PFL + AUX1 + AUX2).
        self.router = AudioRouter(
            sample_rate=self.engine.sample_rate,
            channels=self.engine.channels,
            blocksize=self.engine.blocksize,
        )

        # Wire engine ↔ source manager ↔ streamer.
        self.engine._external_audio_callback = self.source_mgr.get_audio_frame
        self.engine._stream_output_callback = self._on_engine_output

        # Forward signals.
        self.engine.level_updated.connect(self.level_updated)
        self.engine.source_changed.connect(self.source_changed)
        self.engine.error_occurred.connect(self.error_occurred)
        self.source_mgr.track_changed.connect(self.track_changed)
        self.source_mgr.error_occurred.connect(self.error_occurred)
        self.streamer.connected.connect(self.stream_connected)
        self.streamer.disconnected.connect(self.stream_disconnected)
        self.streamer.listener_count_updated.connect(self.listener_count_updated)
        self.streamer.bytes_sent_updated.connect(self.bytes_sent_updated)
        self.streamer.error_occurred.connect(self.error_occurred)

        # Track change → metadata push.
        self.source_mgr.track_changed.connect(
            lambda title: self.streamer.update_metadata(title)
        )

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def apply_config(self) -> None:
        """Apply :attr:`config` to sub-components (devices, volumes, etc.)."""
        cfg = self.config
        self.engine.sample_rate = cfg.sample_rate
        self.engine.master_volume = cfg.master_volume
        if cfg.input_device is not None:
            self.engine.input_device = cfg.input_device
        if cfg.output_device is not None:
            self.engine.output_device = cfg.output_device
        self.engine.eq_enabled = cfg.eq_enabled
        self.engine.compressor_enabled = cfg.compressor_enabled

        if cfg.playlist:
            self.source_mgr.set_playlist(list(cfg.playlist))
        if cfg.radio_url:
            self.source_mgr.set_radio_url(cfg.radio_url)

        # Streamer config.
        self.streamer.stream_name = cfg.stream_name
        if cfg.stream_mode == "builtin":
            self.streamer.configure_builtin(
                port=cfg.stream_builtin_port,
                bitrate=cfg.stream_bitrate,
            )
        else:
            self.streamer.set_mode("icecast")
            self.streamer.configure(
                host=cfg.stream_host,
                port=cfg.stream_port,
                mount=cfg.stream_mount,
                password=cfg.stream_password,
                bitrate=cfg.stream_bitrate,
            )

        # Multi-output routing.
        # Main bus uses the same device as the engine output.
        self.router.add_bus(BusConfig(
            bus_type=BusType.MAIN,
            device_index=cfg.output_device,
            enabled=True,
            volume=1.0,
            label="Main",
        ))
        # Monitor / PFL.
        if cfg.monitor_device is not None:
            self.router.add_bus(BusConfig(
                bus_type=BusType.MONITOR,
                device_index=cfg.monitor_device,
                enabled=cfg.monitor_enabled,
                volume=cfg.monitor_volume,
                label="Monitor (PFL)",
            ))
        # AUX 1.
        if cfg.aux1_device is not None:
            self.router.add_bus(BusConfig(
                bus_type=BusType.AUX1,
                device_index=cfg.aux1_device,
                enabled=cfg.aux1_enabled,
                volume=cfg.aux1_volume,
                label="AUX 1",
            ))
        # AUX 2.
        if cfg.aux2_device is not None:
            self.router.add_bus(BusConfig(
                bus_type=BusType.AUX2,
                device_index=cfg.aux2_device,
                enabled=cfg.aux2_enabled,
                volume=cfg.aux2_volume,
                label="AUX 2",
            ))

    def start(self) -> None:
        """Start the audio engine (capture + playback) and output router."""
        self.apply_config()
        self.engine.start()
        self.router.start()

    def stop(self) -> None:
        """Stop everything: engine, source, streamer, router."""
        self.source_mgr.stop()
        self.streamer.stop()
        self.engine.stop()
        self.router.stop()

    def start_streaming(self) -> None:
        self.streamer.start()

    def stop_streaming(self) -> None:
        self.streamer.stop()

    # ------------------------------------------------------------------ #
    #  Source control                                                      #
    # ------------------------------------------------------------------ #

    def switch_source(self, source: AudioSource) -> None:
        self.engine.switch_source(source)

    def play_file(self, path: str | None = None) -> None:
        self.engine.switch_source(AudioSource.MP3_FILE)
        self.source_mgr.play_file(path)

    def play_radio(self, url: str | None = None) -> None:
        self.engine.switch_source(AudioSource.INTERNET_RADIO)
        self.source_mgr.play_radio(url)

    def preview_pfl(self, audio: np.ndarray) -> None:
        """Send audio to the Monitor/PFL bus (operator headphones only)."""
        try:
            self.router.route_pfl(audio)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _on_engine_output(self, audio) -> None:
        """Route final audio to streamer + multi-output buses."""
        try:
            self.streamer.push_audio(audio)
        except Exception:
            pass
        # Fan out to all output buses (Main, AUX1, AUX2).
        try:
            self.router.route_main(audio)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Snapshot                                                            #
    # ------------------------------------------------------------------ #

    def snapshot_config(self) -> ChannelConfig:
        """Capture current live state back into a ChannelConfig."""
        cfg = self.config
        cfg.master_volume = self.engine.master_volume
        cfg.input_device = self.engine.input_device
        cfg.output_device = self.engine.output_device
        cfg.sample_rate = self.engine.sample_rate
        cfg.eq_enabled = self.engine.eq_enabled
        cfg.compressor_enabled = self.engine.compressor_enabled
        cfg.playlist = list(self.source_mgr._playlist)
        cfg.radio_url = self.source_mgr._radio_url or ""
        cfg.source = self.engine.current_source.value
        return cfg
