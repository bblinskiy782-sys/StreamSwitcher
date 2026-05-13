"""Tests for :mod:`core.playlist`."""

from __future__ import annotations

import textwrap

from core import playlist as pl

# ---------------------------------------------------------------------------
# M3U
# ---------------------------------------------------------------------------


def test_parse_simple_m3u():
    content = textwrap.dedent(
        """\
        #EXTM3U
        /music/track1.mp3
        http://example.com/stream
        """
    )
    tracks = pl.parse_m3u(content)
    assert [t.path for t in tracks] == ["/music/track1.mp3", "http://example.com/stream"]
    assert tracks[0].duration == 0.0
    assert tracks[0].title == ""


def test_parse_extended_m3u():
    content = textwrap.dedent(
        """\
        #EXTM3U
        #EXTINF:230,Daft Punk - One More Time
        /music/dp.mp3
        #EXTINF:-1,Live Stream
        http://stream/
        """
    )
    tracks = pl.parse_m3u(content)
    assert len(tracks) == 2
    assert tracks[0].duration == 230.0
    assert tracks[0].artist == "Daft Punk"
    assert tracks[0].title == "One More Time"
    assert tracks[1].duration == 0.0
    assert tracks[1].title == "Live Stream"


def test_parse_m3u_with_blank_and_comment_lines():
    content = textwrap.dedent(
        """\
        #EXTM3U

        # a comment line
        #EXTINF:60,Title Only
        /music/x.mp3
        """
    )
    tracks = pl.parse_m3u(content)
    assert len(tracks) == 1
    assert tracks[0].title == "Title Only"


def test_write_then_parse_m3u_round_trip():
    original = [
        pl.Track(path="/a.mp3", artist="Artist A", title="Track A", duration=120),
        pl.Track(path="http://example.com/", title="Live"),
    ]
    rendered = pl.write_m3u(original)
    reparsed = pl.parse_m3u(rendered)
    assert [t.path for t in reparsed] == [t.path for t in original]
    assert reparsed[0].artist == "Artist A"
    assert reparsed[0].title == "Track A"
    assert reparsed[0].duration == 120


# ---------------------------------------------------------------------------
# PLS
# ---------------------------------------------------------------------------


def test_parse_pls():
    content = textwrap.dedent(
        """\
        [playlist]
        File1=/music/one.mp3
        Title1=One
        Length1=200
        File2=http://stream/
        Title2=Live
        Length2=-1
        NumberOfEntries=2
        Version=2
        """
    )
    tracks = pl.parse_pls(content)
    assert [t.path for t in tracks] == ["/music/one.mp3", "http://stream/"]
    assert tracks[0].duration == 200.0
    assert tracks[0].title == "One"
    # Negative length normalised to 0.
    assert tracks[1].duration == 0.0


def test_write_then_parse_pls_round_trip():
    original = [
        pl.Track(path="/a.mp3", artist="A", title="T", duration=42),
        pl.Track(path="/b.mp3", title="No Artist"),
    ]
    rendered = pl.write_pls(original)
    parsed = pl.parse_pls(rendered)
    assert [t.path for t in parsed] == ["/a.mp3", "/b.mp3"]
    # Title in PLS combines artist and title.
    assert "T" in parsed[0].title
    assert parsed[0].duration == 42.0


def test_parse_pls_ignores_garbage_lines():
    content = "junk\n[playlist]\nfoo\nFile1=/x.mp3\nNumberOfEntries=1\n"
    tracks = pl.parse_pls(content)
    assert len(tracks) == 1
    assert tracks[0].path == "/x.mp3"


# ---------------------------------------------------------------------------
# Track display
# ---------------------------------------------------------------------------


def test_track_display_prefers_artist_title():
    t = pl.Track(path="/x.mp3", artist="Artist", title="Title")
    assert t.display == "Artist — Title"


def test_track_display_falls_back_to_basename():
    t = pl.Track(path="/path/to/file.mp3")
    assert t.display == "file.mp3"


# ---------------------------------------------------------------------------
# Tag reading (best-effort; degrades gracefully)
# ---------------------------------------------------------------------------


def test_read_tags_missing_file_returns_empty(tmp_path):
    out = pl.read_tags(str(tmp_path / "nope.mp3"))
    assert out == {}


def test_enrich_track_missing_file_is_noop(tmp_path):
    t = pl.Track(path=str(tmp_path / "nope.mp3"), title="kept")
    pl.enrich_track(t)
    assert t.title == "kept"
