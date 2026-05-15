"""Configuration profiles manager.

A *profile* is simply a named copy of the application config file stored
in the same directory as the main ``config.json``:

    <config_dir>/
        config.json          ← active config
        profiles/
            Studio.json
            Mobile.json
            Night.json

The user can create, rename, delete, and switch between profiles.
Switching means: save current state → load the selected profile into
the live config → restart affected subsystems.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from core.config import AppConfig, default_config_path


def _profiles_dir(config_path: Path | str | None = None) -> Path:
    base = Path(config_path) if config_path else default_config_path()
    return base.parent / "profiles"


def list_profiles(config_path: Path | str | None = None) -> list[str]:
    """Return sorted list of profile names (without .json extension)."""
    d = _profiles_dir(config_path)
    if not d.exists():
        return []
    return sorted(
        p.stem for p in d.glob("*.json") if p.is_file()
    )


def save_profile(name: str, config: AppConfig,
                 config_path: Path | str | None = None) -> Path:
    """Save the current config as a named profile. Overwrites if exists."""
    d = _profiles_dir(config_path)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{name}.json"
    target.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def load_profile(name: str,
                 config_path: Path | str | None = None) -> AppConfig:
    """Load a named profile and return it as an AppConfig instance."""
    d = _profiles_dir(config_path)
    target = d / f"{name}.json"
    if not target.exists():
        raise FileNotFoundError(f"Profile '{name}' not found at {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    return AppConfig.from_dict(data)


def delete_profile(name: str,
                   config_path: Path | str | None = None) -> bool:
    """Delete a named profile. Returns True if it existed."""
    d = _profiles_dir(config_path)
    target = d / f"{name}.json"
    if target.exists():
        target.unlink()
        return True
    return False


def rename_profile(old_name: str, new_name: str,
                   config_path: Path | str | None = None) -> bool:
    """Rename a profile. Returns True on success."""
    d = _profiles_dir(config_path)
    src = d / f"{old_name}.json"
    dst = d / f"{new_name}.json"
    if not src.exists() or dst.exists():
        return False
    src.rename(dst)
    return True


def duplicate_profile(name: str, new_name: str,
                      config_path: Path | str | None = None) -> bool:
    """Copy an existing profile under a new name."""
    d = _profiles_dir(config_path)
    src = d / f"{name}.json"
    dst = d / f"{new_name}.json"
    if not src.exists() or dst.exists():
        return False
    shutil.copy2(src, dst)
    return True
