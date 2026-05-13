"""Tiny PySide6 fallback for headless environments.

The core modules emit Qt signals so the UI can react to engine events.
Installing PySide6 (~50 MB) just to run unit tests on pure logic would be
wasteful, so this module provides a stub ``QObject`` / ``Signal`` pair that
matches the API surface ``core`` uses when PySide6 isn't importable.

The real PySide6 implementation is preferred when available. Tests that
exercise UI integration must still install PySide6 explicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from PySide6.QtCore import QObject, Signal  # type: ignore[assignment]

    HAS_QT = True
except ImportError:  # pragma: no cover - exercised only when PySide6 is absent
    HAS_QT = False

    class _StubSignalInstance:
        """Per-instance handle returned when accessing ``Signal`` on a QObject."""

        def __init__(self) -> None:
            self._slots: list[Callable[..., Any]] = []

        def connect(self, slot: Callable[..., Any]) -> None:
            self._slots.append(slot)

        def disconnect(self, slot: Callable[..., Any] | None = None) -> None:
            if slot is None:
                self._slots.clear()
                return
            try:
                self._slots.remove(slot)
            except ValueError:
                pass

        def emit(self, *args: Any, **kwargs: Any) -> None:
            for slot in list(self._slots):
                try:
                    slot(*args, **kwargs)
                except Exception:
                    # Mirror Qt: swallow handler errors.
                    pass

    class Signal:  # type: ignore[no-redef]
        """Descriptor that lazily creates a stub signal per instance."""

        def __init__(self, *types: Any) -> None:
            self._types = types

        def __set_name__(self, owner: type, name: str) -> None:
            self._attr = f"_stub_signal_{name}"

        def __get__(self, instance: Any, owner: type | None = None) -> _StubSignalInstance:
            if instance is None:
                return self  # type: ignore[return-value]
            sig = instance.__dict__.get(self._attr)
            if sig is None:
                sig = _StubSignalInstance()
                instance.__dict__[self._attr] = sig
            return sig

    class QObject:  # type: ignore[no-redef]
        """Minimal QObject stand-in (accepts a parent for API compatibility)."""

        def __init__(self, parent: Any | None = None) -> None:
            self._qt_parent = parent


__all__ = ["QObject", "Signal", "HAS_QT"]
