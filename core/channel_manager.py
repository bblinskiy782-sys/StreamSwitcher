"""Channel Manager — orchestrates multiple independent audio channels.

Typical usage:

    mgr = ChannelManager()
    mgr.add_channel(ChannelConfig(name="Канал 1", input_device=0, ...))
    mgr.add_channel(ChannelConfig(name="Канал 2", input_device=2, ...))
    mgr.start_all()
    ...
    mgr.stop_all()
"""
from __future__ import annotations

from core._qt_compat import QObject, Signal
from core.channel import Channel, ChannelConfig


class ChannelManager(QObject):
    """Holds and manages N independent :class:`Channel` instances."""

    channel_added = Signal(int)      # index
    channel_removed = Signal(int)    # index

    MAX_CHANNELS = 8

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._channels: list[Channel] = []

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def add_channel(self, config: ChannelConfig | None = None) -> Channel:
        """Create and register a new channel. Returns the Channel object."""
        if len(self._channels) >= self.MAX_CHANNELS:
            raise RuntimeError(
                f"Maximum {self.MAX_CHANNELS} channels reached."
            )
        ch = Channel(config=config or ChannelConfig(), parent=self)
        idx = len(self._channels)
        self._channels.append(ch)
        self.channel_added.emit(idx)
        return ch

    def remove_channel(self, index: int) -> None:
        """Stop and remove the channel at *index*."""
        if not (0 <= index < len(self._channels)):
            return
        ch = self._channels.pop(index)
        ch.stop()
        self.channel_removed.emit(index)

    def channel(self, index: int) -> Channel:
        return self._channels[index]

    @property
    def channels(self) -> list[Channel]:
        return list(self._channels)

    @property
    def count(self) -> int:
        return len(self._channels)

    # ------------------------------------------------------------------ #
    #  Bulk operations                                                     #
    # ------------------------------------------------------------------ #

    def start_all(self) -> None:
        for ch in self._channels:
            ch.start()

    def stop_all(self) -> None:
        for ch in self._channels:
            ch.stop()

    # ------------------------------------------------------------------ #
    #  Serialisation helpers                                               #
    # ------------------------------------------------------------------ #

    def configs(self) -> list[ChannelConfig]:
        """Snapshot all channel configs."""
        return [ch.snapshot_config() for ch in self._channels]

    def load_configs(self, configs: list[ChannelConfig]) -> None:
        """Replace all channels with the given configs."""
        self.stop_all()
        self._channels.clear()
        for cfg in configs:
            self.add_channel(cfg)
