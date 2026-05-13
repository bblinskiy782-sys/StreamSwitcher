"""Playlist primitives: M3U / PLS parsing & serialisation, ID3 tag reading.

This module is **pure** (no Qt, no audio I/O) so it can be unit-tested
without spinning up the full app.

Track metadata is exposed via :class:`Track`. The :func:`read_tags` helper
uses ``mutagen`` (already declared as a runtime dependency) to read ID3 /
Vorbis / MP4 tags from a file path. It gracefully degrades when the library
or file are unavailable.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class Track:
    """One playlist entry."""

    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0       # seconds
    bitrate: int = 0            # kbps
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def display(self) -> str:
        """Pretty label for UI lists."""
        if self.artist and self.title:
            return f"{self.artist} — {self.title}"
        if self.title:
            return self.title
        return os.path.basename(self.path) or self.path


# ---------------------------------------------------------------------------
# M3U
# ---------------------------------------------------------------------------


def parse_m3u(content: str) -> list[Track]:
    """Parse an M3U / M3U8 playlist.

    Both extended (``#EXTM3U`` / ``#EXTINF:duration,artist - title``) and
    plain playlists are supported.
    """
    lines = [ln.rstrip() for ln in content.splitlines()]
    tracks: list[Track] = []
    pending_duration: float = 0.0
    pending_meta: str = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.upper() == "#EXTM3U":
            continue
        if line.startswith("#EXTINF:"):
            body = line[len("#EXTINF:"):]
            duration_str, _, meta = body.partition(",")
            try:
                pending_duration = float(duration_str)
            except ValueError:
                pending_duration = 0.0
            pending_meta = meta.strip()
            continue
        if line.startswith("#"):
            # Other extension directives are ignored.
            continue

        track = Track(path=line, duration=max(0.0, pending_duration))
        if pending_meta:
            if " - " in pending_meta:
                artist, title = pending_meta.split(" - ", 1)
                track.artist = artist.strip()
                track.title = title.strip()
            else:
                track.title = pending_meta

        tracks.append(track)
        pending_duration = 0.0
        pending_meta = ""

    return tracks


def write_m3u(tracks: Iterable[Track]) -> str:
    """Serialise tracks to an extended M3U string."""
    out = ["#EXTM3U"]
    for t in tracks:
        duration = int(round(t.duration)) if t.duration > 0 else -1
        meta = ""
        if t.artist or t.title:
            meta = f"{t.artist} - {t.title}".strip(" -")
        out.append(f"#EXTINF:{duration},{meta}")
        out.append(t.path)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# PLS
# ---------------------------------------------------------------------------


def parse_pls(content: str) -> list[Track]:
    """Parse a PLS playlist."""
    entries: dict[int, Track] = {}

    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("[") or line.startswith(";"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()

        for prefix, attr, caster in (
            ("File", "path", str),
            ("Title", "title", str),
            ("Length", "duration", _to_float),
        ):
            if key.startswith(prefix) and key[len(prefix):].isdigit():
                idx = int(key[len(prefix):])
                entries.setdefault(idx, Track(path=""))
                setattr(entries[idx], attr, caster(value))
                break

    return [entries[k] for k in sorted(entries.keys()) if entries[k].path]


def write_pls(tracks: list[Track]) -> str:
    """Serialise tracks to a PLS string."""
    lines = ["[playlist]"]
    for i, t in enumerate(tracks, start=1):
        lines.append(f"File{i}={t.path}")
        title = t.display
        lines.append(f"Title{i}={title}")
        length = int(round(t.duration)) if t.duration > 0 else -1
        lines.append(f"Length{i}={length}")
    lines.append(f"NumberOfEntries={len(tracks)}")
    lines.append("Version=2")
    return "\n".join(lines) + "\n"


def _to_float(value: str) -> float:
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# ID3 / Vorbis tag reading
# ---------------------------------------------------------------------------


def read_tags(path: str) -> dict[str, str]:
    """Best-effort tag reader using ``mutagen``.

    Returns a dict with normalised keys: ``title``, ``artist``, ``album``,
    ``duration``, ``bitrate``. Missing values are simply absent.
    """
    try:
        from mutagen import File as MutagenFile  # type: ignore
    except ImportError:
        return {}

    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        return {}

    if audio is None:
        return {}

    out: dict[str, str] = {}

    def _first(key: str) -> str | None:
        try:
            val = audio.get(key)
        except Exception:
            return None
        if not val:
            return None
        if isinstance(val, list):
            return str(val[0])
        return str(val)

    for tag in ("title", "artist", "album", "albumartist", "genre", "date"):
        v = _first(tag)
        if v:
            out[tag] = v

    info = getattr(audio, "info", None)
    if info is not None:
        if getattr(info, "length", None):
            out["duration"] = f"{float(info.length):.3f}"
        if getattr(info, "bitrate", None):
            # mutagen returns bps, normalise to kbps for display.
            out["bitrate"] = str(int(info.bitrate // 1000))

    return out


def enrich_track(track: Track) -> Track:
    """Read tags from disk into ``track`` (in place) and return it."""
    tags = read_tags(track.path)
    if not tags:
        return track
    track.tags = tags
    track.title = track.title or tags.get("title", "")
    track.artist = track.artist or tags.get("artist", "")
    track.album = track.album or tags.get("album", "")
    if not track.duration:
        try:
            track.duration = float(tags.get("duration", 0.0))
        except ValueError:
            track.duration = 0.0
    if not track.bitrate:
        try:
            track.bitrate = int(tags.get("bitrate", 0))
        except ValueError:
            track.bitrate = 0
    return track
