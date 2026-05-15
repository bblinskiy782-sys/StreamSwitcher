"""Tests for :mod:`core.profiles`."""
from __future__ import annotations

import json
from pathlib import Path

from core.config import AppConfig
from core.profiles import (
    delete_profile,
    duplicate_profile,
    list_profiles,
    load_profile,
    rename_profile,
    save_profile,
)


def test_save_and_load_profile(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg = AppConfig()
    cfg.master_volume = 0.42
    cfg.streaming.mode = "builtin"
    cfg.streaming.builtin_port = 9999

    save_profile("Studio", cfg, cfg_path)
    names = list_profiles(cfg_path)
    assert "Studio" in names

    loaded = load_profile("Studio", cfg_path)
    assert loaded.master_volume == 0.42
    assert loaded.streaming.mode == "builtin"
    assert loaded.streaming.builtin_port == 9999


def test_list_profiles_empty(tmp_path):
    cfg_path = tmp_path / "config.json"
    assert list_profiles(cfg_path) == []


def test_delete_profile(tmp_path):
    cfg_path = tmp_path / "config.json"
    save_profile("ToDelete", AppConfig(), cfg_path)
    assert "ToDelete" in list_profiles(cfg_path)
    assert delete_profile("ToDelete", cfg_path) is True
    assert "ToDelete" not in list_profiles(cfg_path)
    assert delete_profile("ToDelete", cfg_path) is False


def test_rename_profile(tmp_path):
    cfg_path = tmp_path / "config.json"
    save_profile("Old", AppConfig(), cfg_path)
    assert rename_profile("Old", "New", cfg_path) is True
    assert "New" in list_profiles(cfg_path)
    assert "Old" not in list_profiles(cfg_path)


def test_duplicate_profile(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg = AppConfig()
    cfg.master_volume = 0.77
    save_profile("Original", cfg, cfg_path)
    assert duplicate_profile("Original", "Copy", cfg_path) is True
    loaded = load_profile("Copy", cfg_path)
    assert loaded.master_volume == 0.77


def test_load_nonexistent_raises(tmp_path):
    import pytest
    cfg_path = tmp_path / "config.json"
    with pytest.raises(FileNotFoundError):
        load_profile("NoSuch", cfg_path)
