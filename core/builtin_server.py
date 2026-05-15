"""Built-in SHOUTcast-v1-compatible broadcast server.

Inspired by the "Integrated server" in RadioBoss
(https://manual.djsoft.net/radioboss/en/integrated-server.htm):
listeners connect directly to StreamSwitcher on ``http://<host>:<port>``
and receive a live MP3 stream with ICY metadata interleaved — no external
Icecast/Shoutcast required. Typical use case is LAN broadcasting.

Protocol summary (implemented here):

* On connection we read the request line (``GET / HTTP/1.x``) and either
  ``Icy-MetaData: 1`` or its absence.
* We answer with an ``ICY 200 OK`` preamble and icy-* headers, including
  ``icy-metaint: <N>`` when the client asked for metadata.
* From that point we stream raw MP3 frames. Every ``N`` audio bytes we
  inject a metadata block:

      <1-byte length / 16> <length*16 bytes of "StreamTitle='...';">

  padded with NUL to the next 16-byte boundary. Length=0 means "no change".

Concurrency model: one accept thread + one writer thread per client +
a central broadcast queue per client. Slow clients are dropped instead
of blocking the broadcast.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_METAINT = 16000        # bytes between metadata blocks
DEFAULT_MAX_CLIENTS = 100
DEFAULT_CLIENT_QUEUE = 256     # audio chunks buffered per client
ACCEPT_POLL_SEC = 0.5          # how often the accept loop checks for stop


# ---------------------------------------------------------------------------
# ICY metadata helper
# ---------------------------------------------------------------------------


def encode_icy_metadata(title: str) -> bytes:
    """Encode a SHOUTcast ICY metadata block.

    Format: ``<length/16 byte><length*16 bytes of "StreamTitle='...';">``
    padded with NUL bytes. Maximum 16 * 255 = 4080 bytes of payload.
    Returns ``b"\\x00"`` for an empty title (= "no change").
    """
    if not title:
        return b"\x00"

    # Escape single quotes in title — Shoutcast v1 uses raw single-quoted
    # strings, apostrophes must be stripped or the block becomes unparseable.
    safe = title.replace("'", "\u2019")
    payload = f"StreamTitle='{safe}';".encode("utf-8", errors="replace")

    # Pad to 16-byte boundary, cap at 255 * 16 = 4080 bytes.
    max_payload = 255 * 16
    if len(payload) > max_payload:
        payload = payload[:max_payload]
    length_units = (len(payload) + 15) // 16
    padded = payload.ljust(length_units * 16, b"\x00")
    return bytes([length_units]) + padded


# ---------------------------------------------------------------------------
# Client handle
# ---------------------------------------------------------------------------


@dataclass
class _Client:
    sock: socket.socket
    addr: tuple[str, int]
    queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=DEFAULT_CLIENT_QUEUE))
    wants_metadata: bool = False
    bytes_sent: int = 0
    connected_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------


class BuiltinBroadcastServer:
    """Tiny SHOUTcast-v1 compatible broadcast server.

    Usage::

        srv = BuiltinBroadcastServer(port=8000, station_name="My Radio")
        srv.start()
        # ... whenever you have encoded MP3 bytes:
        srv.broadcast(mp3_bytes)
        # ... on track change:
        srv.update_metadata("Artist - Title")
        # ...
        srv.stop()
    """

    def __init__(
        self,
        port: int = 8000,
        host: str = "0.0.0.0",
        station_name: str = "StreamSwitcher",
        genre: str = "Various",
        bitrate: int = 128,
        description: str = "StreamSwitcher Live",
        public: bool = False,
        content_type: str = "audio/mpeg",
        metaint: int = DEFAULT_METAINT,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> None:
        self.host = host
        self.port = port
        self.station_name = station_name
        self.genre = genre
        self.bitrate = bitrate
        self.description = description
        self.public = public
        self.content_type = content_type
        self.metaint = max(1, int(metaint))
        self.max_clients = max_clients

        self._running = False
        self._listen_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._clients: list[_Client] = []
        self._clients_lock = threading.Lock()

        # Current metadata, and the ICY block lazily (re)built on change.
        self._metadata_title: str = ""
        self._metadata_block: bytes = b"\x00"
        self._metadata_version: int = 0

        self._total_bytes_sent: int = 0

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(ACCEPT_POLL_SEC)
        sock.bind((self.host, self.port))
        sock.listen(max(8, self.max_clients))
        self._listen_sock = sock
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="BuiltinServer-accept", daemon=True
        )
        self._accept_thread.start()
        logger.info("BuiltinBroadcastServer listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._running = False
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except Exception:
                pass
            self._listen_sock = None
        # Close all clients.
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            self._disconnect_client(c, reason="server stop")
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None

    # ------------------------------------------------------------------ #
    #  Accept loop                                                         #
    # ------------------------------------------------------------------ #

    def _accept_loop(self) -> None:
        assert self._listen_sock is not None
        while self._running:
            try:
                client_sock, addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client_sock.settimeout(5.0)
            try:
                self._handle_new_client(client_sock, addr)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Rejected client %s: %s", addr, e)
                try:
                    client_sock.close()
                except Exception:
                    pass

    def _handle_new_client(
        self, sock: socket.socket, addr: tuple[str, int]
    ) -> None:
        # Read request headers.
        raw = b""
        while b"\r\n\r\n" not in raw and len(raw) < 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            raw += chunk

        headers = raw.decode("latin-1", errors="replace")
        first_line = headers.split("\r\n", 1)[0] if headers else ""
        lower = headers.lower()
        wants_meta = "icy-metadata: 1" in lower or "icy-metadata:1" in lower

        # Enforce listener limit.
        with self._clients_lock:
            if len(self._clients) >= self.max_clients:
                reject = (
                    b"HTTP/1.0 503 Service Unavailable\r\n"
                    b"Connection: close\r\n\r\n"
                )
                try:
                    sock.sendall(reject)
                finally:
                    sock.close()
                return

        # Write SHOUTcast v1 handshake.
        response_lines = [
            "ICY 200 OK",
            f"icy-notice1: <BR>StreamSwitcher built-in server<BR>",
            f"icy-notice2: StreamSwitcher/1.0<BR>",
            f"icy-name: {self.station_name}",
            f"icy-genre: {self.genre}",
            f"icy-url: http://{self.host}:{self.port}/",
            f"icy-pub: {1 if self.public else 0}",
            f"icy-br: {self.bitrate}",
            f"content-type: {self.content_type}",
        ]
        if wants_meta:
            response_lines.append(f"icy-metaint: {self.metaint}")
        response_lines.append("")  # blank line
        response_lines.append("")
        response = ("\r\n".join(response_lines)).encode("ascii")

        try:
            sock.sendall(response)
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            logger.info("Listener %s dropped during handshake (request: %r)",
                        addr, first_line)
            return

        client = _Client(sock=sock, addr=addr, wants_metadata=wants_meta)
        # Each client has its own writer thread so that one slow listener
        # does not stall the broadcast.
        t = threading.Thread(
            target=self._client_writer, args=(client,),
            name=f"Listener-{addr[0]}:{addr[1]}", daemon=True
        )
        with self._clients_lock:
            self._clients.append(client)
        t.start()
        logger.info("Listener connected: %s (meta=%s)", addr, wants_meta)

    # ------------------------------------------------------------------ #
    #  Writer — one per client                                             #
    # ------------------------------------------------------------------ #

    def _client_writer(self, client: _Client) -> None:
        bytes_since_meta = 0
        last_meta_version = -1
        try:
            client.sock.settimeout(None)  # block in sendall; we time out via dequeue
            while self._running:
                try:
                    chunk = client.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if chunk is None:
                    break

                # Slice so that metadata is injected exactly at metaint for
                # metadata-aware clients.
                if client.wants_metadata:
                    offset = 0
                    while offset < len(chunk):
                        remaining = self.metaint - bytes_since_meta
                        take = min(remaining, len(chunk) - offset)
                        try:
                            client.sock.sendall(chunk[offset:offset + take])
                        except OSError:
                            raise
                        bytes_since_meta += take
                        client.bytes_sent += take
                        offset += take
                        if bytes_since_meta >= self.metaint:
                            # Inject metadata: either the current block or a
                            # "no change" placeholder (b"\x00").
                            if last_meta_version != self._metadata_version:
                                meta = self._metadata_block
                                last_meta_version = self._metadata_version
                            else:
                                meta = b"\x00"
                            try:
                                client.sock.sendall(meta)
                            except OSError:
                                raise
                            bytes_since_meta = 0
                else:
                    try:
                        client.sock.sendall(chunk)
                    except OSError:
                        raise
                    client.bytes_sent += len(chunk)
        except OSError:
            pass
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Writer error for %s: %s", client.addr, e)
        finally:
            self._disconnect_client(client, reason="writer exit")

    def _disconnect_client(self, client: _Client, reason: str = "") -> None:
        with self._clients_lock:
            try:
                self._clients.remove(client)
            except ValueError:
                pass
        try:
            client.sock.close()
        except Exception:
            pass
        logger.info("Listener %s disconnected (%s)", client.addr, reason)

    # ------------------------------------------------------------------ #
    #  Public broadcast API                                                #
    # ------------------------------------------------------------------ #

    def broadcast(self, data: bytes) -> None:
        """Fan out a chunk of MP3 bytes to all current listeners.

        Listeners whose queue is full (slow connection) are dropped instead
        of stalling the caller.
        """
        if not data or not self._running:
            return
        self._total_bytes_sent += len(data)
        with self._clients_lock:
            clients = list(self._clients)
        dropped: list[_Client] = []
        for c in clients:
            try:
                c.queue.put_nowait(data)
            except queue.Full:
                dropped.append(c)
        for c in dropped:
            self._disconnect_client(c, reason="slow consumer")

    def update_metadata(self, title: str) -> None:
        """Set the ``StreamTitle`` for ICY metadata."""
        title = (title or "").strip()
        if title == self._metadata_title:
            return
        self._metadata_title = title
        self._metadata_block = encode_icy_metadata(title)
        self._metadata_version += 1

    # ------------------------------------------------------------------ #
    #  Stats                                                               #
    # ------------------------------------------------------------------ #

    @property
    def listener_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    @property
    def total_bytes_sent(self) -> int:
        return self._total_bytes_sent

    @property
    def is_running(self) -> bool:
        return self._running

    def listener_info(self) -> list[dict]:
        with self._clients_lock:
            return [
                {
                    "addr": f"{c.addr[0]}:{c.addr[1]}",
                    "bytes_sent": c.bytes_sent,
                    "connected_sec": time.time() - c.connected_at,
                    "metadata": c.wants_metadata,
                }
                for c in self._clients
            ]
