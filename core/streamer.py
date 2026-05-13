"""
Streamer - broadcasts audio to Icecast/Shoutcast servers.
Uses HTTP PUT (Icecast) or HTTP SOURCE (Shoutcast) protocol.
"""
import base64
import queue
import socket
import threading
import time

import numpy as np

from core._qt_compat import QObject, Signal


class IcecastStreamer(QObject):
    """
    Streams PCM audio to an Icecast2 server via HTTP PUT.
    Encodes audio to MP3 using pydub/lame if available,
    otherwise sends raw PCM wrapped in a simple container.
    """
    connected = Signal()
    disconnected = Signal()
    listener_count_updated = Signal(int)
    error_occurred = Signal(str)
    bytes_sent_updated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = "localhost"
        self.port = 8000
        self.mount = "/stream"
        self.password = "hackme"
        self.bitrate = 128
        self.sample_rate = 44100
        self.channels = 2
        self.stream_name = "StreamSwitcher"
        self.genre = "Various"
        self.description = "StreamSwitcher Live"

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
        self._init_encoder()

    def _init_encoder(self):
        """Try to initialize MP3 encoder."""
        try:
            import lameenc
            self._encoder = lameenc.Encoder()
            self._encoder.set_bit_rate(self.bitrate)
            self._encoder.set_in_sample_rate(self.sample_rate)
            self._encoder.set_channels(self.channels)
            self._encoder.set_quality(2)
            self._encoder_available = True
        except ImportError:
            self._encoder_available = False

    def configure(self, host: str, port: int, mount: str,
                  password: str, bitrate: int = 128):
        self.host = host
        self.port = port
        self.mount = mount
        self.password = password
        self.bitrate = bitrate

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect_and_stream, daemon=True)
        self._thread.start()
        self._stats_thread = threading.Thread(target=self._poll_stats, daemon=True)
        self._stats_thread.start()

    def stop(self):
        self._running = False
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self.disconnected.emit()

    def push_audio(self, audio: np.ndarray):
        """Called by AudioEngine with each output block."""
        if not self._running or not self._connected:
            return
        try:
            self._audio_queue.put_nowait(audio.copy())
        except queue.Full:
            pass

    def _connect_and_stream(self):
        retry_delay = 3
        while self._running:
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(10)
                self._socket.connect((self.host, self.port))

                # Send Icecast SOURCE request
                auth = base64.b64encode(
                    f"source:{self.password}".encode()
                ).decode()
                content_type = "audio/mpeg" if self._encoder_available else "audio/pcm"
                request = (
                    f"SOURCE {self.mount} HTTP/1.0\r\n"
                    f"Authorization: Basic {auth}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"ice-name: {self.stream_name}\r\n"
                    f"ice-genre: {self.genre}\r\n"
                    f"ice-description: {self.description}\r\n"
                    f"ice-bitrate: {self.bitrate}\r\n"
                    f"ice-samplerate: {self.sample_rate}\r\n"
                    f"ice-channels: {self.channels}\r\n"
                    f"\r\n"
                )
                self._socket.sendall(request.encode())

                # Read response
                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = self._socket.recv(1024)
                    if not chunk:
                        break
                    response += chunk

                if b"200 OK" not in response:
                    raise ConnectionError(f"Server rejected: {response[:200]}")

                self._connected = True
                self._socket.settimeout(5)
                self.connected.emit()

                # Stream loop
                while self._running and self._connected:
                    try:
                        audio = self._audio_queue.get(timeout=1.0)
                        encoded = self._encode(audio)
                        if encoded:
                            self._socket.sendall(encoded)
                            self._bytes_sent += len(encoded)
                            self.bytes_sent_updated.emit(self._bytes_sent)
                    except queue.Empty:
                        continue
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break

            except Exception as e:
                self.error_occurred.emit(f"Streamer: {e}")

            self._connected = False
            self.disconnected.emit()
            if self._running:
                time.sleep(retry_delay)

    def _encode(self, audio: np.ndarray) -> bytes | None:
        """Encode numpy float32 audio to MP3 bytes or raw PCM."""
        try:
            if self._encoder_available and self._encoder:
                # Convert to int16
                pcm_int16 = (audio * 32767).astype(np.int16)
                return self._encoder.encode(pcm_int16.tobytes())
            else:
                # Raw PCM as fallback
                pcm_int16 = (audio * 32767).astype(np.int16)
                return pcm_int16.tobytes()
        except Exception:
            return None

    def _poll_stats(self):
        """Poll Icecast admin API for listener count."""
        import requests as req
        while self._running:
            try:
                url = f"http://{self.host}:{self.port}/admin/stats"
                resp = req.get(
                    url,
                    auth=("admin", self.password),
                    timeout=5
                )
                if resp.ok:
                    # Parse listener count from XML
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.text)
                    listeners = root.findtext(".//listeners", "0")
                    self.listener_count_updated.emit(int(listeners))
            except Exception:
                pass
            time.sleep(10)

    @property
    def is_connected(self) -> bool:
        return self._connected
