"""Tests for :mod:`core.radio_stream`.

These tests focus on the pure-Python bits of the decoder:

* ICY ``StreamTitle`` parsing;
* metadata-stripping state machine (``_split_metadata``).

The ffmpeg-backed decode path is not exercised here — it requires a real
ffmpeg process and a network socket, and is covered indirectly by
integration runs against a local stream.
"""
from __future__ import annotations

from core.radio_stream import (
    RadioStreamDecoder,
    _parse_int_header,
    parse_stream_title,
)


# ---------------------------------------------------------------------------
# ICY title parsing
# ---------------------------------------------------------------------------


def test_parse_stream_title_simple():
    block = b"\x02StreamTitle='Artist - Song';\x00\x00\x00\x00"
    assert parse_stream_title(block) == "Artist - Song"


def test_parse_stream_title_empty_returns_none():
    # Length byte 0 = "no change" marker; there is no payload.
    assert parse_stream_title(b"") is None
    assert parse_stream_title(b"\x00") is None


def test_parse_stream_title_unicode():
    block = b"\x03StreamTitle='\xd0\xad\xd1\x85\xd0\xbe';\x00"
    assert parse_stream_title(block) == "Эхо"


def test_parse_int_header():
    assert _parse_int_header("16000") == 16000
    assert _parse_int_header(" 4096 ") == 4096
    assert _parse_int_header(None) is None
    assert _parse_int_header("abc") is None


# ---------------------------------------------------------------------------
# Metadata stripper
# ---------------------------------------------------------------------------


def _make_decoder(**kwargs) -> RadioStreamDecoder:
    # We do not call .start(), so ffmpeg is never spawned.
    return RadioStreamDecoder("http://example/test", **kwargs)


def _make_metadata_block(title: str) -> bytes:
    payload = f"StreamTitle='{title}';".encode()
    length_units = (len(payload) + 15) // 16
    padded = payload.ljust(length_units * 16, b"\x00")
    return bytes([length_units]) + padded


def test_split_metadata_strips_single_block():
    decoder = _make_decoder()
    metaint = 16
    audio_a = b"A" * metaint
    meta = _make_metadata_block("X - Y")
    audio_b = b"B" * metaint
    stream = audio_a + meta + audio_b

    titles: list[str] = []
    decoder.on_metadata = titles.append

    parts, remaining = decoder._split_metadata(stream, metaint, 0)
    assert b"".join(parts) == audio_a + audio_b
    assert titles == ["X - Y"]
    # Hit metaint exactly at the end of audio_b, so the counter was reset
    # and the state machine is ready to accept the next metadata block.
    assert remaining == 0


def test_split_metadata_handles_empty_blocks():
    decoder = _make_decoder()
    metaint = 8
    # Two windows with a "no change" (length=0) marker between them.
    stream = b"A" * metaint + b"\x00" + b"B" * metaint
    parts, remaining = decoder._split_metadata(stream, metaint, 0)
    assert b"".join(parts) == b"A" * metaint + b"B" * metaint
    assert remaining == 0


def test_split_metadata_tracks_partial_audio_window():
    decoder = _make_decoder()
    metaint = 16
    # Half a window of audio only — no metadata yet, so the counter should
    # reflect how many audio bytes we've consumed so far.
    parts, remaining = decoder._split_metadata(b"A" * 10, metaint, 0)
    assert b"".join(parts) == b"A" * 10
    assert remaining == 10


def test_split_metadata_across_chunk_boundaries():
    decoder = _make_decoder()
    metaint = 8
    meta = _make_metadata_block("Split Title")
    stream = b"A" * metaint + meta + b"B" * metaint

    # Feed the stream in 4-byte chunks to stress the state machine.
    rebuilt = bytearray()
    bytes_since = 0
    titles: list[str] = []
    decoder.on_metadata = titles.append
    for i in range(0, len(stream), 4):
        parts, bytes_since = decoder._split_metadata(
            stream[i:i + 4], metaint, bytes_since
        )
        for p in parts:
            rebuilt.extend(p)

    assert bytes(rebuilt) == b"A" * metaint + b"B" * metaint
    assert titles == ["Split Title"]


def test_split_metadata_ignores_duplicate_titles():
    decoder = _make_decoder()
    metaint = 8
    meta = _make_metadata_block("Same")
    stream = b"A" * metaint + meta + b"B" * metaint + meta + b"C" * metaint

    titles: list[str] = []
    decoder.on_metadata = lambda t: titles.append(t)

    rebuilt = bytearray()
    bytes_since = 0
    for chunk_start in range(0, len(stream), 5):
        parts, bytes_since = decoder._split_metadata(
            stream[chunk_start:chunk_start + 5], metaint, bytes_since
        )
        for p in parts:
            rebuilt.extend(p)

    # Both metadata blocks carry the same title; we must only emit it once.
    assert titles == ["Same"]
    assert bytes(rebuilt) == b"A" * metaint + b"B" * metaint + b"C" * metaint
