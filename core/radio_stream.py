"""Robust internet radio streaming decoder.

The previous implementation tried to feed raw MP3 chunks into
``soundfile.read(BytesIO(...))``, which:

* libsndfile does not support streaming MP3 reliably;
* it did not strip ICY metadata blocks from the stream, so binary metadata
  was passed to the decoder as audio and produced clicks / decode failures;
* it silently dropped up to 1 MiB on any decode error, which is exactly
  what "постоянно обрывы" looks like from the outside.

This module replaces that path with a proper streaming pipeline:

1. HTTP ``GET`` with ``Icy-MetaData: 1``;
2. parse the ``icy-metaint`` header and, on the fly, strip metadata blocks
   from the audio byte stream while emitting ``StreamTitle`` updates;
3. pipe the cleaned audio bytes into an ``ffmpeg`` child process that
   decodes any input codec (MP3 / AAC / OGG) into 16-bit little-endian
   interleaved PCM at the requested sample rate and channel count;
4. read PCM from ffmpeg's stdout into a bounded queue that the audio
   engine consumes;
5. auto-reconnect with exponential back-off on network errors.

``ffmpeg`` binary is discovered in this order:
``imageio_ffmpeg.get_ffmpeg_exe()`` → ``pydub.utils.which("ffmpeg")`` →
bare ``"ffmpeg"`` (PATH).
"""
from __future__ import annotations

import logging
import queue
import re
import shutil
import subprocess
import threading
import time

import numpy as np
import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ffmpeg discovery
# ---------------------------------------------------------------------------


def _discover_ffmpeg() -> str | None:
    """Return a path to an ffmpeg executable, or ``None`` if not found."""
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        from pydub.utils import which  # type: ignore
        exe = which("ffmpeg")
        if exe:
            return exe
    except Exception:
        pass
    return None


FFMPEG_EXE = _discover_ffmpeg()


# ---------------------------------------------------------------------------
# ICY metadata helper
# ---------------------------------------------------------------------------


_STREAM_TITLE_RE = re.compile(rb"StreamTitle='([^']*)';")


def parse_stream_title(meta_block: bytes) -> str | None:
    """Extract ``StreamTitle`` value from a raw SHOUTcast metadata block."""
    if not meta_block:
        return None
    m = _STREAM_TITLE_RE.search(meta_block)
    if not m:
        return None
    try:
        return m.group(1).decode("utf-8", errors="replace").strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Streaming decoder
# ---------------------------------------------------------------------------


class RadioStreamError(RuntimeError):
    """Raised when the stream cannot be opened or decoded at all."""


class RadioStreamDecoder:
    """
    Pull audio from an internet-radio URL and decode it to PCM frames.

    Events are reported via plain callback attributes; keeping this class
    Qt-free makes it easy to unit-test.

        decoder = RadioStreamDecoder(url, sample_rate=44100, channels=2)
        decoder.on_metadata = lambda title: ...
        decoder.on_buffering = lambda busy: ...
        decoder.on_error = lambda msg: ...
        decoder.start()
        ... decoder.read_pcm(frames) ...
        decoder.stop()
    """

    HTTP_READ_TIMEOUT = 15.0
    HTTP_CONNECT_TIMEOUT = 8.0
    MAX_RETRIES = 20
    BACKOFF_INITIAL = 1.0
    BACKOFF_MAX = 20.0
    PCM_QUEUE_SECONDS = 6.0        # buffer roughly this many seconds of PCM
    HTTP_CHUNK_BYTES = 4096
    FFMPEG_READ_BYTES = 4096

    def __init__(
        self,
        url: str,
        sample_rate: int = 44100,
        channels: int = 2,
    ) -> None:
        self.url = url
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)

        # Callbacks
        self.on_metadata = None          # type: ignore[assignment]
        self.on_buffering = None         # type: ignore[assignment]
        self.on_error = None             # type: ignore[assignment]
        self.on_connected = None         # type: ignore[assignment]

        # ~6 s of audio, each item = samples for one HTTP chunk decoded.
        # Bound is deliberately generous so that short network hiccups are
        # absorbed without starving the output.
        bytes_per_sec = self.sample_rate * self.channels * 2
        target_bytes = int(bytes_per_sec * self.PCM_QUEUE_SECONDS)
        target_items = max(16, target_bytes // self.FFMPEG_READ_BYTES)
        self._pcm_queue: queue.Queue[bytes] = queue.Queue(maxsize=target_items)

        self._running = False
        self._stop_event = threading.Event()
        self._ffmpeg_proc: subprocess.Popen | None = None

        self._net_thread: threading.Thread | None = None
        self._ffmpeg_reader_thread: threading.Thread | None = None

        self._leftover = b""
        self._last_title: str | None = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        if not FFMPEG_EXE:
            raise RadioStreamError(
                "ffmpeg not found. Install 'imageio-ffmpeg' "
                "or add ffmpeg to PATH."
            )
        self._running = True
        self._stop_event.clear()
        self._net_thread = threading.Thread(
            target=self._network_loop, name="RadioDecoder-net", daemon=True)
        self._net_thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        self._terminate_ffmpeg()
        # Wait for the network thread to exit.
        if self._net_thread is not None:
            self._net_thread.join(timeout=5.0)
            self._net_thread = None
        # Drain queue so the audio thread returns None quickly.
        try:
            while True:
                self._pcm_queue.get_nowait()
        except queue.Empty:
            pass

    def read_pcm(self, frames: int) -> np.ndarray | None:
        """Return ``frames`` stereo float32 samples or ``None`` if not ready."""
        need_bytes = frames * self.channels * 2
        buf = self._leftover
        while len(buf) < need_bytes:
            try:
                chunk = self._pcm_queue.get_nowait()
            except queue.Empty:
                # Keep whatever we have for the next call.
                self._leftover = buf
                return None
            buf += chunk
        out, self._leftover = buf[:need_bytes], buf[need_bytes:]
        pcm = np.frombuffer(out, dtype="<i2").astype(np.float32) / 32768.0
        return pcm.reshape(frames, self.channels)

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    #  Network loop (one shot per connection attempt)                      #
    # ------------------------------------------------------------------ #

    def _network_loop(self) -> None:
        attempt = 0
        backoff = self.BACKOFF_INITIAL
        while self._running and attempt < self.MAX_RETRIES:
            try:
                self._emit_buffering(True)
                self._pump_once()
                # pump_once returns normally only on graceful EOF.
                attempt += 1
            except requests.exceptions.RequestException as e:
                attempt += 1
                self._emit_error(
                    f"Radio connection error ({attempt}/{self.MAX_RETRIES}): {e}"
                )
            except RadioStreamError as e:
                self._emit_error(str(e))
                break
            except Exception as e:  # pragma: no cover - defensive
                attempt += 1
                self._emit_error(f"Radio decode error: {e}")
            finally:
                self._terminate_ffmpeg()
                self._emit_buffering(False)

            if not self._running:
                break
            # Exponential back-off, capped.
            time.sleep(backoff)
            backoff = min(backoff * 2, self.BACKOFF_MAX)

        self._running = False

    def _pump_once(self) -> None:
        """Open one connection and stream through ffmpeg until EOF/stop."""
        headers = {
            "Icy-MetaData": "1",
            "User-Agent": "StreamSwitcher/1.0",
        }
        resp = requests.get(
            self.url,
            stream=True,
            headers=headers,
            timeout=(self.HTTP_CONNECT_TIMEOUT, self.HTTP_READ_TIMEOUT),
        )
        try:
            resp.raise_for_status()

            # Initial ICY / HTTP metadata from response headers.
            metaint = _parse_int_header(resp.headers.get("icy-metaint"))
            icy_name = resp.headers.get("icy-name") or resp.headers.get("ice-name")
            if icy_name:
                self._emit_metadata(icy_name)

            self._spawn_ffmpeg()
            if self.on_connected:
                try:
                    self.on_connected()
                except Exception:
                    pass

            bytes_since_meta = 0
            try:
                stdin = self._ffmpeg_proc.stdin  # type: ignore[union-attr]
            except Exception:
                stdin = None
            if stdin is None:
                raise RadioStreamError("ffmpeg stdin unavailable")

            self._emit_buffering(False)

            for chunk in resp.iter_content(chunk_size=self.HTTP_CHUNK_BYTES):
                if not self._running or self._stop_event.is_set():
                    break
                if not chunk:
                    continue

                if metaint and metaint > 0:
                    audio_parts, bytes_since_meta = self._split_metadata(
                        chunk, metaint, bytes_since_meta
                    )
                    for part in audio_parts:
                        if part:
                            try:
                                stdin.write(part)
                            except (BrokenPipeError, OSError):
                                return
                else:
                    try:
                        stdin.write(chunk)
                    except (BrokenPipeError, OSError):
                        return

            try:
                stdin.close()
            except Exception:
                pass
        finally:
            # Always close the HTTP response to release the TCP socket.
            try:
                resp.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  ICY splitter                                                        #
    # ------------------------------------------------------------------ #

    def _split_metadata(
        self, data: bytes, metaint: int, bytes_since_meta: int
    ) -> tuple[list[bytes], int]:
        """Strip ICY metadata blocks from ``data``.

        Returns ``(audio_chunks, updated_bytes_since_meta)``. ``audio_chunks``
        contains byte slices that are pure audio and safe to forward to the
        decoder. Any ``StreamTitle`` found is reported via callback.
        """
        audio_parts: list[bytes] = []
        i = 0
        n = len(data)
        # State machine: while ``bytes_since_meta < metaint`` we are inside
        # the audio window; once we hit ``metaint`` we must consume the
        # metadata block before continuing.
        #
        # Metadata block layout:
        #   1 byte  N (length in 16-byte units, may be 0)
        #   N*16 bytes payload
        #
        # The payload may cross a chunk boundary, so we handle partial
        # consumption via instance attributes.

        # Lazily initialised scratch state stored on the instance so that
        # we can resume across ``iter_content`` chunks.
        meta_state = getattr(self, "_meta_state", None)
        if meta_state is None:
            meta_state = {"phase": "audio", "remaining": 0, "buf": bytearray()}
            self._meta_state = meta_state

        while i < n:
            if meta_state["phase"] == "audio":
                room = metaint - bytes_since_meta
                take = min(room, n - i)
                if take > 0:
                    audio_parts.append(data[i:i + take])
                    i += take
                    bytes_since_meta += take
                if bytes_since_meta >= metaint:
                    meta_state["phase"] = "length"
                    bytes_since_meta = 0

            elif meta_state["phase"] == "length":
                length_units = data[i]
                i += 1
                meta_state["remaining"] = length_units * 16
                meta_state["buf"] = bytearray()
                if meta_state["remaining"] == 0:
                    # Empty metadata block = "no change".
                    meta_state["phase"] = "audio"
                else:
                    meta_state["phase"] = "payload"

            elif meta_state["phase"] == "payload":
                take = min(meta_state["remaining"], n - i)
                meta_state["buf"].extend(data[i:i + take])
                i += take
                meta_state["remaining"] -= take
                if meta_state["remaining"] == 0:
                    title = parse_stream_title(bytes(meta_state["buf"]))
                    if title and title != self._last_title:
                        self._last_title = title
                        self._emit_metadata(title)
                    meta_state["phase"] = "audio"
                    meta_state["buf"] = bytearray()

        return audio_parts, bytes_since_meta

    # ------------------------------------------------------------------ #
    #  ffmpeg process                                                      #
    # ------------------------------------------------------------------ #

    def _spawn_ffmpeg(self) -> None:
        assert FFMPEG_EXE is not None
        self._leftover = b""
        cmd = [
            FFMPEG_EXE,
            "-loglevel", "error",
            "-nostdin",
            "-hide_banner",
            "-i", "pipe:0",
            "-vn",
            "-ac", str(self.channels),
            "-ar", str(self.sample_rate),
            "-f", "s16le",
            "pipe:1",
        ]
        # Hide the console window on Windows.
        creationflags = 0
        try:
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        except AttributeError:
            pass
        self._ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            creationflags=creationflags,
        )
        self._ffmpeg_reader_thread = threading.Thread(
            target=self._ffmpeg_reader, name="RadioDecoder-ffmpeg", daemon=True)
        self._ffmpeg_reader_thread.start()

    def _ffmpeg_reader(self) -> None:
        proc = self._ffmpeg_proc
        if proc is None or proc.stdout is None:
            return
        try:
            while self._running and not self._stop_event.is_set():
                data = proc.stdout.read(self.FFMPEG_READ_BYTES)
                if not data:
                    break
                try:
                    self._pcm_queue.put(data, timeout=1.0)
                except queue.Full:
                    # Slow consumer — drop a chunk to avoid unbounded latency.
                    try:
                        self._pcm_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._pcm_queue.put_nowait(data)
                    except queue.Full:
                        pass
        except Exception:  # pragma: no cover - defensive
            pass

    def _terminate_ffmpeg(self) -> None:
        proc = self._ffmpeg_proc
        self._ffmpeg_proc = None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass
        # Wait for the reader thread to finish so it doesn't leak.
        if self._ffmpeg_reader_thread is not None:
            self._ffmpeg_reader_thread.join(timeout=2.0)
            self._ffmpeg_reader_thread = None
        # Reset ICY state so a reconnect starts clean.
        self._meta_state = None

    # ------------------------------------------------------------------ #
    #  Callback helpers                                                    #
    # ------------------------------------------------------------------ #

    def _emit_metadata(self, title: str) -> None:
        cb = self.on_metadata
        if cb:
            try:
                cb(title)
            except Exception:  # pragma: no cover - defensive
                pass

    def _emit_buffering(self, busy: bool) -> None:
        cb = self.on_buffering
        if cb:
            try:
                cb(busy)
            except Exception:  # pragma: no cover - defensive
                pass

    def _emit_error(self, msg: str) -> None:
        logger.warning("%s", msg)
        cb = self.on_error
        if cb:
            try:
                cb(msg)
            except Exception:  # pragma: no cover - defensive
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_int_header(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
