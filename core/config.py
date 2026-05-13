"""Persistent application configuration.

The whole user state (audio devices, master volume, EQ, playlist, schedule,
radio presets, streaming target, remote API key) is serialised to a single
JSON file. The default location is OS-dependent:

* Linux / macOS: ``~/.config/streamswitcher/config.json``
* Windows: ``%APPDATA%\\StreamSwitcher\\config.json``

The file format is versioned (``"version": 1``). Older versions are migrated
on load.
"""

from __future__ import annotations

import json
import os
import sys
import typing
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

CONFIG_VERSION = 1


# ---------------------------------------------------------------------------
# Sub-dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CompressorConfig:
    enabled: bool = False
    threshold_db: float = -18.0
    ratio: float = 4.0
    makeup_db: float = 6.0
    attack_ms: float = 10.0
    release_ms: float = 100.0


@dataclass
class EQConfig:
    enabled: bool = False
    bands: dict[str, float] = field(
        default_factory=lambda: {
            "60": 0.0,
            "250": 0.0,
            "1000": 0.0,
            "4000": 0.0,
            "12000": 0.0,
        }
    )

    def bands_int_keys(self) -> dict[int, float]:
        """Return bands with integer-typed keys (JSON only supports strings)."""
        return {int(k): float(v) for k, v in self.bands.items()}


@dataclass
class StreamingConfig:
    host: str = "localhost"
    port: int = 8000
    mount: str = "/stream"
    password: str = ""
    bitrate: int = 128
    stream_name: str = "StreamSwitcher"
    genre: str = "Various"
    description: str = "StreamSwitcher Live"


@dataclass
class RadioPreset:
    name: str
    url: str


@dataclass
class ScheduleEntryDict:
    time_str: str
    action: str
    target: str = ""
    repeat_daily: bool = True
    enabled: bool = True


@dataclass
class AutoDJConfig:
    enabled: bool = False
    shuffle: bool = False
    repeat: str = "all"   # "off" | "one" | "all"
    avoid_repeat_minutes: int = 30
    crossfade_seconds: float = 0.0


@dataclass
class CrossfadeConfigDict:
    enabled: bool = True
    duration_sec: float = 0.0
    curve: str = "equal_power"


@dataclass
class AppConfig:
    """Top-level application configuration."""

    version: int = CONFIG_VERSION
    sample_rate: int = 44100
    input_device: int | None = None
    output_device: int | None = None
    master_volume: float = 0.8

    eq: EQConfig = field(default_factory=EQConfig)
    compressor: CompressorConfig = field(default_factory=CompressorConfig)
    crossfade: CrossfadeConfigDict = field(default_factory=CrossfadeConfigDict)

    playlist: list[str] = field(default_factory=list)
    radio_url: str = ""
    radio_presets: list[RadioPreset] = field(
        default_factory=lambda: [
            RadioPreset(name="Радио Рекорд", url="http://air.radiorecord.ru:805/rr_320"),
            RadioPreset(name="Europa Plus",
                        url="http://europaplus.hostingradio.ru:8052/europaplus128.mp3"),
            RadioPreset(name="DI.FM Trance", url="http://prem2.di.fm:80/trance"),
            RadioPreset(name="SomaFM Groove", url="http://ice1.somafm.com/groovesalad-128-mp3"),
        ]
    )

    schedule: list[ScheduleEntryDict] = field(default_factory=list)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    autodj: AutoDJConfig = field(default_factory=AutoDJConfig)

    remote_api_port: int = 8080
    remote_api_key: str = ""   # empty = public access (backward compat)

    failover_enabled: bool = True

    # ------------------------------------------------------------------ #
    #  Serialisation                                                       #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return _to_dict_recursive(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        return _from_dict_recursive(cls, _migrate(data))

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path is not None else default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: Path | str | None = None) -> AppConfig:
        target = Path(path) if path is not None else default_config_path()
        if not target.exists():
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    """OS-appropriate default location for ``config.json``."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "StreamSwitcher" / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return Path(xdg) / "streamswitcher" / "config.json"


def _to_dict_recursive(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_dict_recursive(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_to_dict_recursive(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_dict_recursive(v) for k, v in obj.items()}
    return obj


def _from_dict_recursive(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass from a (possibly partial) dict."""
    if not is_dataclass(cls):
        return data

    kwargs: dict[str, Any] = {}
    # Resolve string-style annotations (`from __future__ import annotations`)
    # into real types using the module's globals.
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {}
    field_map = {f.name: f for f in fields(cls)}

    for name, f in field_map.items():
        if name not in data:
            continue
        value = data[name]
        target_type = hints.get(name, f.type)
        if isinstance(target_type, str):
            target_type = globals().get(target_type, target_type)

        if is_dataclass(target_type) and isinstance(value, dict):
            kwargs[name] = _from_dict_recursive(target_type, value)
        elif _is_list_of_dataclass(target_type) and isinstance(value, list):
            inner = _list_inner_type(target_type)
            kwargs[name] = [_from_dict_recursive(inner, item) for item in value]
        else:
            kwargs[name] = value
    return cls(**kwargs)


def _is_list_of_dataclass(t: Any) -> bool:
    origin = getattr(t, "__origin__", None)
    if origin is not list:
        return False
    args = getattr(t, "__args__", ())
    return bool(args) and is_dataclass(args[0])


def _list_inner_type(t: Any) -> Any:
    return t.__args__[0]


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Forward-migrate config data from older versions to ``CONFIG_VERSION``."""
    version = data.get("version", 0)
    # Currently only version 1 exists; this function is the hook for future
    # migrations (e.g. when fields are renamed or restructured).
    if version > CONFIG_VERSION:
        # User has a newer config than this binary understands — keep the
        # known fields, drop the rest gracefully by relying on dataclass
        # defaults.
        data["version"] = CONFIG_VERSION
    return data


# Convenience helper for tests / debugging
def asdict_safe(cfg: AppConfig) -> dict[str, Any]:
    return asdict(cfg)
