"""Audio Router — multi-output bus system.

Implements the RadioBoss-style output routing where a single audio pipeline
can send audio to multiple physical devices simultaneously:

* **Main** — primary output (on-air / speakers)
* **Monitor (PFL)** — pre-fader listen for the operator's headphones
* **AUX 1 / AUX 2** — auxiliary outputs (e.g. recording feed, zone 2)

Each bus is an independent ``sounddevice.OutputStream`` bound to a
specific audio device. The router receives the final mixed audio from
the engine and fans it out to all active buses.

PFL (Pre-Fader Listen) is special: it receives audio from the *next*
queued track (or any cued source) *before* it goes on air, so the
operator can preview without the audience hearing it.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

try:
    import sounddevice as sd  # type: ignore
except (ImportError, OSError):
    sd = None  # type: ignore[assignment]


class BusType(Enum):
    MAIN = "main"
    MONITOR = "monitor"       # PFL / предпрослушка
    AUX1 = "aux1"
    AUX2 = "aux2"
    JINGLE = "jingle"         # dedicated jingle output


@dataclass
class BusConfig:
    """Configuration for one output bus."""
    bus_type: BusType = BusType.MAIN
    device_index: int | None = None
    enabled: bool = True
    volume: float = 1.0
    label: str = ""


class OutputBus:
    """One output stream bound to a physical audio device."""

    def __init__(self, config: BusConfig, sample_rate: int = 44100,
                 channels: int = 2, blocksize: int = 1024) -> None:
        self.config = config
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize

        self._stream: sd.OutputStream | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=30)
        self._running = False

    def start(self) -> None:
        if self._running or sd is None:
            return
        if not self.config.enabled:
            return
        try:
            self._stream = sd.OutputStream(
                device=self.config.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                blocksize=self.blocksize,
                callback=self._callback,
                latency="low",
            )
            self._stream.start()
            self._running = True
        except Exception:
            self._running = False

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def push(self, audio: np.ndarray) -> None:
        """Push a block of audio to this bus. Non-blocking, drops if full."""
        if not self._running or not self.config.enabled:
            return
        scaled = audio * self.config.volume
        try:
            self._queue.put_nowait(scaled)
        except queue.Full:
            pass

    def _callback(self, outdata: np.ndarray, frames: int,
                  time_info, status) -> None:
        try:
            data = self._queue.get_nowait()
            if data.shape[0] != frames:
                if data.shape[0] > frames:
                    data = data[:frames]
                else:
                    pad = np.zeros((frames - data.shape[0], self.channels),
                                   dtype=np.float32)
                    data = np.vstack([data, pad])
            outdata[:] = np.clip(data, -1.0, 1.0)
        except queue.Empty:
            outdata[:] = 0

    @property
    def is_running(self) -> bool:
        return self._running


class AudioRouter:
    """Manages multiple output buses and routes audio to them.

    Usage::

        router = AudioRouter(sample_rate=44100, channels=2, blocksize=1024)
        router.add_bus(BusConfig(bus_type=BusType.MAIN, device_index=0))
        router.add_bus(BusConfig(bus_type=BusType.MONITOR, device_index=2))
        router.start()
        ...
        router.route_main(audio_block)       # goes to MAIN + AUX buses
        router.route_pfl(preview_block)      # goes to MONITOR only
        ...
        router.stop()
    """

    def __init__(self, sample_rate: int = 44100, channels: int = 2,
                 blocksize: int = 1024) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self._buses: dict[BusType, OutputBus] = {}

    def add_bus(self, config: BusConfig) -> None:
        """Add or replace a bus."""
        if config.bus_type in self._buses:
            self._buses[config.bus_type].stop()
        bus = OutputBus(
            config=config,
            sample_rate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
        )
        self._buses[config.bus_type] = bus

    def remove_bus(self, bus_type: BusType) -> None:
        bus = self._buses.pop(bus_type, None)
        if bus:
            bus.stop()

    def get_bus(self, bus_type: BusType) -> OutputBus | None:
        return self._buses.get(bus_type)

    def start(self) -> None:
        for bus in self._buses.values():
            bus.start()

    def stop(self) -> None:
        for bus in self._buses.values():
            bus.stop()

    def set_bus_volume(self, bus_type: BusType, volume: float) -> None:
        bus = self._buses.get(bus_type)
        if bus:
            bus.config.volume = max(0.0, min(1.0, volume))

    def set_bus_device(self, bus_type: BusType, device_index: int | None) -> None:
        """Change the device for a bus (requires restart of that bus)."""
        bus = self._buses.get(bus_type)
        if bus:
            was_running = bus.is_running
            bus.stop()
            bus.config.device_index = device_index
            if was_running:
                bus.start()

    def set_bus_enabled(self, bus_type: BusType, enabled: bool) -> None:
        bus = self._buses.get(bus_type)
        if bus:
            if enabled and not bus.is_running:
                bus.config.enabled = True
                bus.start()
            elif not enabled and bus.is_running:
                bus.stop()
                bus.config.enabled = False

    # ------------------------------------------------------------------ #
    #  Routing                                                             #
    # ------------------------------------------------------------------ #

    def route_main(self, audio: np.ndarray) -> None:
        """Send audio to MAIN, AUX1, AUX2, JINGLE buses."""
        for bt in (BusType.MAIN, BusType.AUX1, BusType.AUX2, BusType.JINGLE):
            bus = self._buses.get(bt)
            if bus:
                bus.push(audio)

    def route_pfl(self, audio: np.ndarray) -> None:
        """Send audio to MONITOR (PFL) bus only — operator preview."""
        bus = self._buses.get(BusType.MONITOR)
        if bus:
            bus.push(audio)

    def route_to(self, bus_type: BusType, audio: np.ndarray) -> None:
        """Send audio to a specific bus."""
        bus = self._buses.get(bus_type)
        if bus:
            bus.push(audio)

    # ------------------------------------------------------------------ #
    #  Info                                                                #
    # ------------------------------------------------------------------ #

    @property
    def bus_types(self) -> list[BusType]:
        return list(self._buses.keys())

    def bus_configs(self) -> list[BusConfig]:
        return [bus.config for bus in self._buses.values()]
