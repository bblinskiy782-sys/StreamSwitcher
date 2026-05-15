"""Tests for the built-in SHOUTcast-v1-style broadcast server."""
from __future__ import annotations

import socket
import time

import pytest

from core.builtin_server import (
    BuiltinBroadcastServer,
    encode_icy_metadata,
)


# ---------------------------------------------------------------------------
# Metadata encoding
# ---------------------------------------------------------------------------


def test_encode_icy_metadata_empty_is_single_null():
    assert encode_icy_metadata("") == b"\x00"


def test_encode_icy_metadata_length_byte_matches_payload():
    block = encode_icy_metadata("Artist - Title")
    assert isinstance(block, bytes)
    length_units = block[0]
    payload = block[1:]
    assert len(payload) == length_units * 16
    # Body is padded with NUL, so payload should contain the StreamTitle text.
    assert b"StreamTitle='Artist - Title';" in payload
    # Padded with NUL to multiple of 16.
    assert (len(payload) % 16) == 0


def test_encode_icy_metadata_escapes_single_quotes():
    block = encode_icy_metadata("It's on")
    # Raw apostrophes must be substituted — they would break the
    # single-quoted SHOUTcast format.
    assert b"It's" not in block
    assert b"It" in block


def test_encode_icy_metadata_caps_at_max_length():
    huge = "A" * 10_000
    block = encode_icy_metadata(huge)
    # 1 length byte + 255 * 16 payload bytes = 4081.
    assert len(block) == 1 + 255 * 16


# ---------------------------------------------------------------------------
# Server + client end-to-end
# ---------------------------------------------------------------------------


def _get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _connect_and_read(port: int, request_headers: str,
                      read_bytes: int = 2048,
                      timeout: float = 3.0) -> bytes:
    sock = socket.socket()
    sock.settimeout(timeout)
    sock.connect(("127.0.0.1", port))
    sock.sendall(request_headers.encode("ascii"))
    data = b""
    deadline = time.time() + timeout
    try:
        while len(data) < read_bytes and time.time() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    return data


@pytest.fixture
def server():
    srv = BuiltinBroadcastServer(
        port=_get_free_port(),
        host="127.0.0.1",
        station_name="Test Radio",
        genre="Probe",
        bitrate=128,
        metaint=32,  # tiny for tests
    )
    srv.start()
    # Give the accept thread a moment to enter its loop.
    time.sleep(0.05)
    yield srv
    srv.stop()


def test_handshake_sends_icy_headers(server):
    data = _connect_and_read(
        server.port,
        "GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n",
    )
    head = data.split(b"\r\n\r\n", 1)[0]
    assert head.startswith(b"ICY 200 OK\r\n")
    assert b"icy-name: Test Radio" in head
    assert b"icy-br: 128" in head
    assert b"content-type: audio/mpeg" in head
    # This client did not ask for metadata, so no icy-metaint.
    assert b"icy-metaint" not in head


def test_handshake_advertises_metaint_when_requested(server):
    data = _connect_and_read(
        server.port,
        "GET / HTTP/1.0\r\nHost: 127.0.0.1\r\nIcy-MetaData: 1\r\n\r\n",
    )
    head = data.split(b"\r\n\r\n", 1)[0]
    assert b"icy-metaint: 32" in head


def test_broadcast_reaches_connected_listener(server):
    # Open a listener without metadata interleaving — raw MP3 bytes come
    # straight back.
    sock = socket.socket()
    sock.settimeout(3.0)
    sock.connect(("127.0.0.1", server.port))
    sock.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")

    # Drain the headers.
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1024)

    # Wait until the server has registered the client.
    for _ in range(50):
        if server.listener_count >= 1:
            break
        time.sleep(0.02)
    assert server.listener_count == 1

    payload = b"SS-AUDIO-" + b"X" * 200
    server.broadcast(payload)

    received = b""
    deadline = time.time() + 2.0
    while len(received) < len(payload) and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        received += chunk
    sock.close()

    assert payload in received


def test_metaint_block_injected_at_expected_offset(server):
    """With Icy-MetaData:1 and a small metaint, the server interleaves a
    zero-length metadata block (``b"\\x00"``) every ``metaint`` bytes when
    no title is set."""
    sock = socket.socket()
    sock.settimeout(3.0)
    sock.connect(("127.0.0.1", server.port))
    sock.sendall(
        b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\nIcy-MetaData: 1\r\n\r\n"
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1024)
    body = head.split(b"\r\n\r\n", 1)[1]

    for _ in range(50):
        if server.listener_count >= 1:
            break
        time.sleep(0.02)

    # Send enough audio for two full metaint windows.
    payload = bytes(range(256)) * 1  # 256 distinct bytes, repeats deterministic
    server.broadcast(payload * 3)  # 768 bytes of audio

    received = body
    deadline = time.time() + 2.0
    while len(received) < 32 + 1 + 32 and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        received += chunk
    sock.close()

    # First 32 bytes must be audio, byte 32 must be the metadata-length
    # byte (0 = no change), and byte 33 onwards continues audio.
    assert len(received) >= 32 + 1 + 32
    assert received[32] == 0


def test_update_metadata_delivers_stream_title(server):
    sock = socket.socket()
    sock.settimeout(3.0)
    sock.connect(("127.0.0.1", server.port))
    sock.sendall(
        b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\nIcy-MetaData: 1\r\n\r\n"
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1024)
    body = head.split(b"\r\n\r\n", 1)[1]

    for _ in range(50):
        if server.listener_count >= 1:
            break
        time.sleep(0.02)

    server.update_metadata("Demo - Song")
    server.broadcast(b"A" * 200)

    received = body
    deadline = time.time() + 2.0
    while b"StreamTitle=" not in received and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        received += chunk
    sock.close()

    assert b"StreamTitle='Demo - Song';" in received


def test_stop_disconnects_clients(server):
    sock = socket.socket()
    sock.settimeout(3.0)
    sock.connect(("127.0.0.1", server.port))
    sock.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1024)

    for _ in range(50):
        if server.listener_count >= 1:
            break
        time.sleep(0.02)

    server.stop()
    time.sleep(0.1)
    assert server.listener_count == 0
    sock.close()
