"""Tests for :mod:`core.config`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config as cfg_mod


def test_defaults_round_trip(tmp_config_path: Path):
    cfg = cfg_mod.AppConfig()
    saved_at = cfg.save(tmp_config_path)
    assert saved_at == tmp_config_path
    assert tmp_config_path.exists()
    loaded = cfg_mod.AppConfig.load(tmp_config_path)
    assert loaded.to_dict() == cfg.to_dict()


def test_load_missing_file_returns_defaults(tmp_path: Path):
    target = tmp_path / "does-not-exist.json"
    loaded = cfg_mod.AppConfig.load(target)
    assert loaded.master_volume == cfg_mod.AppConfig().master_volume


def test_load_corrupt_file_returns_defaults(tmp_config_path: Path):
    tmp_config_path.write_text("{not valid json", encoding="utf-8")
    loaded = cfg_mod.AppConfig.load(tmp_config_path)
    assert loaded.version == cfg_mod.CONFIG_VERSION


def test_partial_dict_uses_defaults_for_missing_fields():
    partial = {"version": 1, "master_volume": 0.4}
    cfg = cfg_mod.AppConfig.from_dict(partial)
    assert cfg.master_volume == pytest.approx(0.4)
    # Other fields fall back to dataclass defaults.
    assert cfg.sample_rate == 44100
    assert cfg.eq.enabled is False


def test_modify_playlist_persists(tmp_config_path: Path):
    cfg = cfg_mod.AppConfig()
    cfg.playlist = ["/music/a.mp3", "/music/b.mp3"]
    cfg.eq.enabled = True
    cfg.eq.bands["1000"] = 3.0
    cfg.save(tmp_config_path)

    loaded = cfg_mod.AppConfig.load(tmp_config_path)
    assert loaded.playlist == cfg.playlist
    assert loaded.eq.enabled is True
    assert loaded.eq.bands_int_keys()[1000] == pytest.approx(3.0)


def test_radio_presets_round_trip(tmp_config_path: Path):
    cfg = cfg_mod.AppConfig()
    cfg.radio_presets.append(cfg_mod.RadioPreset(name="My Station", url="http://x:8000/s"))
    cfg.save(tmp_config_path)

    loaded = cfg_mod.AppConfig.load(tmp_config_path)
    names = [p.name for p in loaded.radio_presets]
    assert "My Station" in names


def test_schedule_round_trip(tmp_config_path: Path):
    cfg = cfg_mod.AppConfig()
    cfg.schedule = [
        cfg_mod.ScheduleEntryDict(
            time_str="08:00:00", action="play_radio", target="http://r/", repeat_daily=True
        ),
        cfg_mod.ScheduleEntryDict(
            time_str="20:00:00", action="stop", target="", repeat_daily=False
        ),
    ]
    cfg.save(tmp_config_path)
    loaded = cfg_mod.AppConfig.load(tmp_config_path)
    assert [e.time_str for e in loaded.schedule] == ["08:00:00", "20:00:00"]
    assert loaded.schedule[0].action == "play_radio"
    assert loaded.schedule[1].repeat_daily is False


def test_to_dict_is_json_serialisable(tmp_config_path: Path):
    cfg = cfg_mod.AppConfig()
    data = cfg.to_dict()
    # Round-trip via JSON to make sure no non-serialisable types crept in.
    s = json.dumps(data)
    parsed = json.loads(s)
    assert parsed["version"] == cfg_mod.CONFIG_VERSION


def test_default_config_path_returns_path():
    p = cfg_mod.default_config_path()
    assert isinstance(p, Path)
    assert p.name == "config.json"


def test_migration_caps_future_version():
    future = {"version": 999, "master_volume": 0.5}
    cfg = cfg_mod.AppConfig.from_dict(future)
    assert cfg.version == cfg_mod.CONFIG_VERSION
    assert cfg.master_volume == pytest.approx(0.5)
