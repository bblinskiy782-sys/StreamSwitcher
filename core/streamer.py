"""
Streamer - broadcasts audio to Icecast/Shoutcast servers or to a built-in
SHOUTcast-v1 compatible broadcast server (RadioBoss-style integrated server).

Two modes, picked at runtime:

* ``"icecast"`` — modern Icecast 2.4+ ``PUT`` with fallback to legacy
  ``SOURCE``. For broadcasting to an *external* Icecast/Shoutcast server.
* ``"builtin"`` — the stream is encoded to MP3 and fed into our own
  :class:`core.builtin_server.BuiltinBroadcastServer`. Listeners connect
  directly to StreamSwitcher on ``http://<ip>:<port>`` — no external server
  required.

MP3 encoding is done via ``lameenc``. Without it the stream is unplayable
in either mode, so we refuse to start and surface a clear error instead
of silently sending garbage.
"""
from __future__ import annotations

import base64
import queue
import socket
import threading
import time

import numpy as np

from core._qt_compat import QObject, Signal
from core.builtin_server import BuiltinBroadcastServer


class IcecastStreamer(QObject):
    """
    Streams PCM audio to an Icecast2 server.

    Pipeline:
        audio (float32 numpy) -> int16 PCM -> lameenc MP3 -> socket.sendall
    """
    connected = Signal()
    disconnected = Signal()
    listener_count_updated = Signal(int)
    error_occurred = Signal(str)
    bytes_sent_updated = Signal(int)

    # Connection-level tunables
    CONNECT_TIMEOUT = 10.0
    SOCKET_TIMEOUT = 10.0
    RETRY_DELAY_SEC = 3.0
    USER_AGENT = "StreamSwitcher/1.0"

    def __init__(self, parent=None):
        super().__init__(parent)
        # Mode: "icecast" (external server) or "builtin" (integrated server).
        self.mode: str = "icecast"

        # External-server target (Icecast / SHOUTcast).
        self.host = "localhost"
        self.port = 8000
        self.mount = "/stream"
        self.password = "hackme"

        # Shared encoding / metadata settings.
        self.bitrate = 128
        self.sample_rate = 44100
        self.channels = 2
        self.stream_name = "StreamSwitcher"
        self.genre = "Various"
        self.description = "StreamSwitcher Live"
        # Separate admin password for stats polling. Falls back to source
        # password when empty (backward compat with older configs).
        self.admin_password: str = ""

        # Built-in server target.
        self.builtin_bind_host: str = "0.0.0.0"
        self.builtin_port: int = 8000
        self.builtin_public: bool = False
        self._builtin_server: BuiltinBroadcastServer | None = None

        self._running = False
        self._connected = False
        self._socket: socket.socket | None = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._thread: threading.Thread | None = None
        self._stats_thread: threading.Thread | None = None
        self._bytes_sent = 0

        # MP3 encoder
        self._encoder = None
        self._encoder_available = False
        self._encoder_lock = threading.Lock()
        self._init_encoder()

    # ------------------------------------------------------------------ #
    #  Encoder                                                             #
    # ------------------------------------------------------------------ #

    def _init_encoder(self) -> None:
        """(Re)initialise MP3 encoder with current bitrate/sample-rate/channels."""
        try:
            import lameenc  # type: ignore
        except ImportError:
            self._encoder = None
            self._encoder_available = False
            return

        with self._encoder_lock:
            enc = lameenc.Encoder()
            enc.set_bit_rate(self.bitrate)
            enc.set_in_sample_rate(self.sample_rate)
            enc.set_channels(self.channels)
            enc.set_quality(2)
            self._encoder = enc
            self._encoder_available = True

    def configure(self, host: str, port: int, mount: str,
                  password: str, bitrate: int = 128) -> None:
        self.host = host
        self.port = port
        # Icecast mount points must start with '/'. Be forgiving on input.
        self.mount = mount if mount.startswith("/") else f"/{mount}"
        self.password = password
        self.bitrate = bitrate
        # Recreate encoder so the new bitrate actually takes effect.
        self._init_encoder()

    def configure_builtin(self, port: int, bind_host: str = "0.0.0.0",
                          bitrate: int = 128, public: bool = False) -> None:
        """Configure the integrated (built-in) broadcast server target.

        Listeners will connect directly to ``http://<bind_host>:<port>/``.
        No external Icecast/Shoutcast is required.
        """
        self.mode = "builtin"
        self.builtin_port = int(port)
        self.builtin_bind_host = bind_host
        self.builtin_public = bool(public)
        self.bitrate = int(bitrate)
        self._init_encoder()

    def set_mode(self, mode: str) -> None:
        """Select broadcast mode: ``"icecast"`` or ``"builtin"``."""
        if mode not in ("icecast", "builtin"):
            raise ValueError(f"unknown streamer mode: {mode!r}")
        self.mode = mode

    def update_metadata(self, title: str) -> None:
        """Push a new ``StreamTitle`` to listeners.

        * Built-in server: updates the ICY metadata block.
        * Icecast mode: sends an HTTP admin request to update the mount metadata.
        """
        if self._builtin_server is not None:
            self._builtin_server.update_metadata(title)
        if self.mode == "icecast" and self._connected and title:
            import threading
            threading.Thread(
                target=self._push_icecast_metadata,
                args=(title,), daemon=True
            ).start()

    def _push_icecast_metadata(self, title: str) -> None:
        """Send metadata update to Icecast admin API."""
        try:
            import requests
            import urllib.parse
            encoded = urllib.parse.quote(title, safe="")
            url = (
                f"http://{self.host}:{self.port}"
                f"/admin/metadata?mount={urllib.parse.quote(self.mount)}"
                f"&mode=updinfo&song={encoded}"
            )
            admin_pw = self.admin_password or self.password
            requests.get(url, auth=("source", admin_pw), timeout=5)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        if not self._encoder_available:
            self.error_occurred.emit(
                "MP3 encoder (lameenc) is not installed — listeners would "
                "receive unplayable raw PCM. Install with: pip install lameenc"
            )
            return
        self._running = True
        self._bytes_sent = 0

        if self.mode == "builtin":
            # Start the integrated server and a worker that encodes audio
            # from the queue and broadcasts it to all listeners.
            try:
                self._builtin_server = BuiltinBroadcastServer(
                    port=self.builtin_port,
                    host=self.builtin_bind_host,
                    station_name=self.stream_name,
                    genre=self.genre,
                    bitrate=self.bitrate,
                    description=self.description,
                    public=self.builtin_public,
                )
                self._builtin_server.start()
            except OSError as e:
                self._running = False
                self._builtin_server = None
                self.error_occurred.emit(
                    f"Built-in server: cannot bind to "
                    f"{self.builtin_bind_host}:{self.builtin_port} — {e}"
                )
                return
            self._connected = True
            self.connected.emit()
            self._thread = threading.Thread(
                target=self._builtin_loop, name="Streamer-builtin", daemon=True)
            self._thread.start()
            self._stats_thread = threading.Thread(
                target=self._poll_builtin_stats, name="Streamer-builtin-stats",
                daemon=True)
            self._stats_thread.start()
            return

        # Icecast mode.
        self._thread = threading.Thread(target=self._connect_and_stream, daemon=True)
        self._thread.start()
        self._stats_thread = threading.Thread(target=self._poll_stats, daemon=True)
        self._stats_thread.start()

    def stop(self) -> None:
        self._running = False
        self._connected = False

        # Wait for the encoding thread to exit so we don't race on the encoder.
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._stats_thread is not None:
            self._stats_thread.join(timeout=2.0)
            self._stats_thread = None

        # Flush encoder to not lose the MP3 tail.
        try:
            if self._encoder_available and self._encoder:
                with self._encoder_lock:
                    tail = self._encoder.flush()
                if tail:
                    if self._builtin_server is not None:
                        try:
                            self._builtin_server.broadcast(tail)
                        except Exception:
                            pass
                    elif self._socket is not None:
                        try:
                            self._socket.sendall(tail)
                        except Exception:
                            pass
        except Exception:
            pass

        # Drain leftover audio queue to free memory.
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        if self._builtin_server is not None:
            try:
                self._builtin_server.stop()
            except Exception:
                pass
            self._builtin_server = None
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self.disconnected.emit()

    def push_audio(self, audio: np.ndarray) -> None:
        """Called by AudioEngine with each output block."""
        if not self._running or not self._connected:
            return
        try:
            self._audio_queue.put_nowait(audio)
        except queue.Full:
            # Drop oldest to keep latency bounded.
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait(audio)
            except queue.Full:
                pass

    # ------------------------------------------------------------------ #
    #  Built-in server path                                                #
    # ------------------------------------------------------------------ #

    def _builtin_loop(self) -> None:
        """Encode audio from the queue and hand it to the built-in server."""
        while self._running:
            try:
                audio = self._audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            encoded = self._encode(audio)
            if not encoded or self._builtin_server is None:
                continue
            try:
                self._builtin_server.broadcast(encoded)
            except Exception:
                continue
            self._bytes_sent += len(encoded)
            self.bytes_sent_updated.emit(self._bytes_sent)

    def _poll_builtin_stats(self) -> None:
        last = -1
        while self._running:
            srv = self._builtin_server
            if srv is not None:
                count = srv.listener_count
                if count != last:
                    last = count
                    self.listener_count_updated.emit(count)
            time.sleep(2)

    # ------------------------------------------------------------------ #
    #  Icecast handshake + stream loop                                     #
    # ------------------------------------------------------------------ #

    def _build_headers(self, method: str) -> bytes:
        """Assemble an Icecast source request.

        Includes the mandatory ``Host:`` header — without it most proxies
        and CDNs (nginx, Cloudflare, AzuraCast, Centova) reject the stream.
        """
        auth = base64.b64encode(f"source:{self.password}".encode()).decode()
        content_type = "audio/mpeg"
        # Icecast uses ``Host: name:port`` so the server can multiplex
        # multiple virtual hosts on one socket.
        host_header = f"{self.host}:{self.port}"

        lines = [
            f"{method} {self.mount} HTTP/1.0",
            f"Host: {host_header}",
            f"Authorization: Basic {auth}",
            f"User-Agent: {self.USER_AGENT}",
            f"Content-Type: {content_type}",
            f"ice-name: {self.stream_name}",
            f"ice-genre: {self.genre}",
            f"ice-description: {self.description}",
            f"ice-bitrate: {self.bitrate}",
            f"ice-samplerate: {self.sample_rate}",
            f"ice-channels: {self.channels}",
            "ice-public: 1",
            "Expect: 100-continue" if method == "PUT" else "",
            "",  # blank line after headers
            "",
        ]
        request = "\r\n".join(l for l in lines if l is not None)
        # Collapse the empty "Expect" line if method != PUT
        request = request.replace("\r\n\r\n\r\n", "\r\n\r\n")
        return request.encode("ascii")

    def _open_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.CONNECT_TIMEOUT)
        sock.connect((self.host, self.port))
        # Keepalive helps detect dead upstream connections (CDN/proxy drops).
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        return sock

    @staticmethod
    def _read_response(sock: socket.socket, max_bytes: int = 8192) -> bytes:
        response = b""
        while b"\r\n\r\n" not in response and len(response) < max_bytes:
            chunk = sock.recv(1024)
            if not chunk:
                break
            response += chunk
        return response

    def _handshake(self, method: str) -> tuple[socket.socket, bytes]:
        sock = self._open_socket()
        sock.sendall(self._build_headers(method))
        # For ``PUT`` with ``Expect: 100-continue`` the server answers
        # ``HTTP/1.1 100 Continue`` first, then the final status. Read until
        # we see the header terminator twice at most.
        response = self._read_response(sock)
        if response.startswith(b"HTTP/1.1 100") or b" 100 " in response[:40]:
            # Discard the 100-continue and wait for the real answer.
            response = self._read_response(sock)
        return sock, response

    def _connect_and_stream(self) -> None:
        while self._running:
            sock: socket.socket | None = None
            try:
                # Try modern PUT first, fall back to legacy SOURCE.
                try:
                    sock, response = self._handshake("PUT")
                    if b" 200" not in response and b" 100" not in response:
                        try:
                            sock.close()
                        except Exception:
                            pass
                        sock, response = self._handshake("SOURCE")
                except (OSError, ConnectionError):
                    if sock is not None:
                        try:
                            sock.close()
                        except Exception:
                            pass
                    sock, response = self._handshake("SOURCE")

                if b" 200" not in response:
                    snippet = response[:200].decode("latin-1", errors="replace")
                    raise ConnectionError(
                        f"Server rejected handshake: {snippet!r}"
                    )

                self._socket = sock
                self._connected = True
                self._socket.settimeout(self.SOCKET_TIMEOUT)
                self.connected.emit()

                # Stream loop
                while self._running and self._connected:
                    try:
                        audio = self._audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    encoded = self._encode(audio)
                    if not encoded:
                        continue
                    try:
                        self._socket.sendall(encoded)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                    self._bytes_sent += len(encoded)
                    self.bytes_sent_updated.emit(self._bytes_sent)

            except Exception as e:
                self.error_occurred.emit(f"Streamer: {e}")
            finally:
                self._connected = False
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self._socket = None
                self.disconnected.emit()

            if self._running:
                time.sleep(self.RETRY_DELAY_SEC)

    # ------------------------------------------------------------------ #
    #  Encoding                                                            #
    # ------------------------------------------------------------------ #

    def _encode(self, audio: np.ndarray) -> bytes | None:
        """Encode float32 audio (-1..1) to MP3 bytes."""
        try:
            if not self._encoder_available or not self._encoder:
                return None
            # lameenc expects interleaved int16 PCM.
            pcm_int16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            with self._encoder_lock:
                return self._encoder.encode(pcm_int16.tobytes())
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Listener stats                                                      #
    # ------------------------------------------------------------------ #

    def _poll_stats(self) -> None:
        """Poll Icecast admin API for listener count."""
        import requests as req
        while self._running:
            admin_pw = self.admin_password or self.password
            try:
                url = f"http://{self.host}:{self.port}/admin/stats"
                resp = req.get(url, auth=("admin", admin_pw), timeout=5)
                if resp.ok:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.text)
                    # Prefer the listener count for *our* mount if present.
                    mount_node = None
                    for src in root.findall("source"):
                        if src.get("mount") == self.mount:
                            mount_node = src
                            break
                    node = mount_node if mount_node is not None else root
                    listeners = node.findtext(".//listeners", "0")
                    self.listener_count_updated.emit(int(listeners))
            except Exception:
                pass
            time.sleep(10)

    @property
    def is_connected(self) -> bool:
        return self._connected
