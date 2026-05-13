"""Tests for the Icecast SOURCE handshake produced by :mod:`core.streamer`.

The streamer is wired up so that we can validate the bytes it sends without
actually opening a network socket — we monkeypatch ``socket.socket`` to a
fake that records ``sendall`` calls and answers with a canned response.
"""

from __future__ import annotations

import base64
import time

from core.streamer import IcecastStreamer


class _FakeSocket:
    """Minimal socket stand-in used by :class:`IcecastStreamer._connect_and_stream`."""

    def __init__(self, *args, **kwargs) -> None:
        self.sent: list[bytes] = []
        self._reply = b"HTTP/1.0 200 OK\r\n\r\n"
        self._read = False

    def settimeout(self, _timeout):
        pass

    def connect(self, _addr):
        pass

    def sendall(self, data: bytes):
        self.sent.append(data)

    def recv(self, _n: int) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._reply

    def close(self):
        pass


def test_handshake_request_is_well_formed(monkeypatch):
    fake = _FakeSocket()
    monkeypatch.setattr("core.streamer.socket.socket", lambda *a, **kw: fake)

    streamer = IcecastStreamer()
    streamer.configure(
        host="example.com",
        port=8000,
        mount="/teststream",
        password="hackme",
        bitrate=128,
    )

    # Run the connect/stream loop for a brief window, then stop it.
    streamer.start()
    deadline = time.time() + 1.5
    while time.time() < deadline and not fake.sent:
        time.sleep(0.05)
    streamer.stop()

    assert fake.sent, "streamer never wrote a handshake to the socket"
    request = fake.sent[0].decode("ascii", errors="replace")

    # Required parts of the Icecast SOURCE protocol.
    assert request.startswith("SOURCE /teststream HTTP/1.0\r\n")
    assert "ice-name: StreamSwitcher" in request
    assert "ice-bitrate: 128" in request
    assert "ice-samplerate: 44100" in request
    assert "ice-channels: 2" in request

    expected_auth = base64.b64encode(b"source:hackme").decode()
    assert f"Authorization: Basic {expected_auth}" in request

    # Header block terminates with double CRLF.
    assert request.endswith("\r\n\r\n")


def test_configure_updates_fields():
    streamer = IcecastStreamer()
    streamer.configure(host="h", port=9000, mount="/m", password="p", bitrate=64)
    assert (streamer.host, streamer.port, streamer.mount,
            streamer.password, streamer.bitrate) == ("h", 9000, "/m", "p", 64)
