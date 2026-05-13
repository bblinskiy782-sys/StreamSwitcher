"""
Source Manager - handles MP3 file playback and internet radio streaming.
Provides audio frames to the AudioEngine via callback.
"""
import io
import os
import queue
import threading
import time

import numpy as np
import requests

from core._qt_compat import QObject, Signal

try:
    import soundfile as sf  # type: ignore
except ImportError:  # pragma: no cover - audio runtime optional in tests
    sf = None  # type: ignore[assignment]


class SourceManager(QObject):
    """
    Manages non-live audio sources:
    - MP3 file (local, SMB, HTTP, FTP)
    - Internet radio stream (HTTP/Icecast/Shoutcast)
    """
    track_changed = Signal(str)          # track name
    position_updated = Signal(float)     # position in seconds
    duration_updated = Signal(float)     # total duration
    waveform_ready = Signal(object)      # numpy array of waveform data
    playlist_updated = Signal(list)      # list of track names
    error_occurred = Signal(str)
    buffering = Signal(bool)             # buffering state

    BUFFER_SIZE = 4096
    RADIO_CHUNK = 16384

    def __init__(self, sample_rate=44100, channels=2, blocksize=1024, parent=None):
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize

        # Playlist
        self._playlist: list[str] = []
        self._current_index = 0
        self._radio_url = ""

        # Playback state
        self._playing = False
        self._paused = False
        self._audio_data: np.ndarray | None = None
        self._position = 0  # frame position
        self._duration = 0.0

        # Audio output queue
        self._audio_queue: queue.Queue = queue.Queue(maxsize=50)

        # Threads
        self._decode_thread: threading.Thread | None = None
        self._radio_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Radio buffer
        self._radio_buffer = queue.Queue(maxsize=200)
        self._radio_pcm_buffer = np.array([], dtype=np.float32)

    # ------------------------------------------------------------------ #
    #  Playlist management                                                 #
    # ------------------------------------------------------------------ #

    def set_playlist(self, paths: list[str]):
        self._playlist = paths
        self._current_index = 0
        names = [os.path.basename(p) for p in paths]
        self.playlist_updated.emit(names)

    def add_to_playlist(self, path: str):
        self._playlist.append(path)
        names = [os.path.basename(p) for p in self._playlist]
        self.playlist_updated.emit(names)

    def remove_from_playlist(self, index: int):
        """Remove the track at ``index``. No-op when out of range."""
        if not (0 <= index < len(self._playlist)):
            return
        self._playlist.pop(index)
        if self._current_index >= len(self._playlist):
            self._current_index = max(0, len(self._playlist) - 1)
        names = [os.path.basename(p) for p in self._playlist]
        self.playlist_updated.emit(names)

    def clear_playlist(self):
        self._playlist.clear()
        self._current_index = 0
        self.playlist_updated.emit([])

    def set_radio_url(self, url: str):
        self._radio_url = url

    # ------------------------------------------------------------------ #
    #  Playback control                                                    #
    # ------------------------------------------------------------------ #

    def play_file(self, path: str | None = None):
        """Start playing a file (or current playlist item)."""
        self._stop_internal()
        self._stop_event.clear()

        if path:
            if path not in self._playlist:
                self._playlist.append(path)
            self._current_index = self._playlist.index(path)

        if not self._playlist:
            self.error_occurred.emit("Playlist is empty")
            return

        target = self._playlist[self._current_index]
        self._playing = True
        self._paused = False

        self._decode_thread = threading.Thread(
            target=self._decode_and_buffer, args=(target,), daemon=True
        )
        self._decode_thread.start()
        self.track_changed.emit(os.path.basename(target))

    def play_radio(self, url: str | None = None):
        """Start streaming internet radio."""
        self._stop_internal()
        self._stop_event.clear()

        if url:
            self._radio_url = url
        if not self._radio_url:
            self.error_occurred.emit("No radio URL set")
            return

        self._playing = True
        self._paused = False
        self._radio_pcm_buffer = np.array([], dtype=np.float32)

        self._radio_thread = threading.Thread(
            target=self._stream_radio, daemon=True
        )
        self._radio_thread.start()
        self.track_changed.emit(self._radio_url)

    def stop(self):
        self._stop_internal()

    def pause(self):
        self._paused = not self._paused

    def next_track(self):
        if not self._playlist:
            return
        self._current_index = (self._current_index + 1) % len(self._playlist)
        self.play_file()

    def prev_track(self):
        if not self._playlist:
            return
        self._current_index = (self._current_index - 1) % len(self._playlist)
        self.play_file()

    def seek(self, position_seconds: float):
        if self._audio_data is not None:
            frame = int(position_seconds * self.sample_rate)
            self._position = max(0, min(frame, len(self._audio_data) - 1))

    def _stop_internal(self):
        self._playing = False
        self._paused = False
        self._stop_event.set()
        # Clear queues
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        while not self._radio_buffer.empty():
            try:
                self._radio_buffer.get_nowait()
            except queue.Empty:
                break

    # ------------------------------------------------------------------ #
    #  Audio frame provider (called by AudioEngine)                       #
    # ------------------------------------------------------------------ #

    def get_audio_frame(self, frames: int) -> np.ndarray | None:
        """Called by AudioEngine output callback to get next audio block."""
        if not self._playing or self._paused:
            return None

        if self._audio_data is not None:
            return self._get_file_frame(frames)
        else:
            return self._get_radio_frame(frames)

    def _get_file_frame(self, frames: int) -> np.ndarray | None:
        if self._audio_data is None:
            return None
        end = self._position + frames
        if self._position >= len(self._audio_data):
            # Track ended - go to next
            threading.Thread(target=self._auto_next, daemon=True).start()
            return None

        chunk = self._audio_data[self._position:end]
        self._position = min(end, len(self._audio_data))

        # Emit position
        pos_sec = self._position / self.sample_rate
        self.position_updated.emit(pos_sec)

        # Pad if needed
        if len(chunk) < frames:
            pad = np.zeros((frames - len(chunk), self.channels), dtype=np.float32)
            chunk = np.vstack([chunk, pad])

        return chunk.astype(np.float32)

    def _get_radio_frame(self, frames: int) -> np.ndarray | None:
        needed = frames * self.channels
        if len(self._radio_pcm_buffer) < needed:
            # Try to fill from radio buffer
            try:
                chunk = self._radio_buffer.get_nowait()
                self._radio_pcm_buffer = np.append(self._radio_pcm_buffer, chunk)
            except queue.Empty:
                return None

        if len(self._radio_pcm_buffer) < needed:
            return None

        out = self._radio_pcm_buffer[:needed]
        self._radio_pcm_buffer = self._radio_pcm_buffer[needed:]
        return out.reshape(frames, self.channels)

    def _auto_next(self):
        time.sleep(0.1)
        if self._playlist and self._current_index < len(self._playlist) - 1:
            self._current_index += 1
            self.play_file()
        else:
            self._playing = False

    # ------------------------------------------------------------------ #
    #  File decoding                                                       #
    # ------------------------------------------------------------------ #

    def _decode_and_buffer(self, path: str):
        """Decode audio file to PCM numpy array."""
        try:
            self.buffering.emit(True)
            audio_data, sr = self._load_audio(path)
            if audio_data is None:
                return

            # Resample if needed
            if sr != self.sample_rate:
                audio_data = self._resample(audio_data, sr, self.sample_rate)

            # Ensure stereo
            if audio_data.ndim == 1:
                audio_data = np.column_stack([audio_data, audio_data])
            elif audio_data.shape[1] == 1:
                audio_data = np.column_stack([audio_data[:, 0], audio_data[:, 0]])

            self._audio_data = audio_data.astype(np.float32)
            self._position = 0
            self._duration = len(audio_data) / self.sample_rate
            self.duration_updated.emit(self._duration)

            # Generate waveform for mini-player
            threading.Thread(
                target=self._generate_waveform,
                args=(audio_data,),
                daemon=True
            ).start()

            self.buffering.emit(False)

        except Exception as e:
            self.error_occurred.emit(f"Decode error: {e}")
            self.buffering.emit(False)

    def _load_audio(self, path: str) -> tuple:
        """Load audio from local file, HTTP, or SMB path."""
        try:
            if path.startswith(("http://", "https://", "ftp://")):
                return self._load_from_url(path)
            elif path.startswith("smb://") or path.startswith("\\\\"):
                return self._load_from_smb(path)
            else:
                data, sr = sf.read(path, dtype="float32", always_2d=True)
                return data, sr
        except Exception:
            # Try pydub as fallback for MP3
            try:
                from pydub import AudioSegment
                seg = AudioSegment.from_file(path)
                sr = seg.frame_rate
                samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
                samples = samples / (2 ** 15)
                if seg.channels == 2:
                    samples = samples.reshape(-1, 2)
                else:
                    samples = samples.reshape(-1, 1)
                return samples, sr
            except Exception as e2:
                self.error_occurred.emit(f"Cannot load audio: {e2}")
                return None, None

    def _load_from_url(self, url: str) -> tuple:
        """Download and decode audio from HTTP/FTP URL."""
        self.buffering.emit(True)
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)
        data, sr = sf.read(buf, dtype="float32", always_2d=True)
        return data, sr

    def _load_from_smb(self, path: str) -> tuple:
        """Load from SMB network share (mapped drive or UNC path)."""
        # On Windows, UNC paths work directly
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return data, sr

    def _resample(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Simple linear resampling."""
        try:
            import scipy.signal as sig
            ratio = target_sr / orig_sr
            new_len = int(len(audio) * ratio)
            if audio.ndim == 1:
                return sig.resample(audio, new_len)
            result = np.zeros((new_len, audio.shape[1]), dtype=np.float32)
            for ch in range(audio.shape[1]):
                result[:, ch] = sig.resample(audio[:, ch], new_len)
            return result
        except Exception:
            return audio

    def _generate_waveform(self, audio: np.ndarray, points: int = 1000):
        """Generate downsampled waveform for visualization."""
        try:
            mono = audio[:, 0] if audio.ndim > 1 else audio
            step = max(1, len(mono) // points)
            waveform = np.array([
                float(np.max(np.abs(mono[i:i + step])))
                for i in range(0, len(mono), step)
            ])
            self.waveform_ready.emit(waveform)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Radio streaming                                                     #
    # ------------------------------------------------------------------ #

    def _stream_radio(self):
        """Stream internet radio and decode to PCM."""
        retry_count = 0
        max_retries = 10

        while not self._stop_event.is_set() and retry_count < max_retries:
            try:
                self.buffering.emit(True)
                headers = {"Icy-MetaData": "1"}
                resp = requests.get(
                    self._radio_url,
                    stream=True,
                    headers=headers,
                    timeout=15
                )
                resp.raise_for_status()
                self.buffering.emit(False)
                retry_count = 0

                # Decode stream chunks
                buf = b""
                for chunk in resp.iter_content(chunk_size=self.RADIO_CHUNK):
                    if self._stop_event.is_set():
                        break
                    buf += chunk
                    # Try to decode accumulated buffer
                    try:
                        audio_io = io.BytesIO(buf)
                        data, sr = sf.read(audio_io, dtype="float32", always_2d=True)
                        if sr != self.sample_rate:
                            data = self._resample(data, sr, self.sample_rate)
                        if data.ndim == 1:
                            data = np.column_stack([data, data])
                        pcm = data.flatten().astype(np.float32)
                        try:
                            self._radio_buffer.put_nowait(pcm)
                        except queue.Full:
                            pass
                        buf = b""
                    except Exception:
                        # Buffer not yet decodable, keep accumulating
                        if len(buf) > 1024 * 1024:  # 1MB max buffer
                            buf = b""

            except requests.exceptions.ConnectionError:
                retry_count += 1
                self.error_occurred.emit(
                    f"Radio connection lost. Retry {retry_count}/{max_retries}..."
                )
                time.sleep(3)
            except Exception as e:
                retry_count += 1
                self.error_occurred.emit(f"Radio error: {e}")
                time.sleep(3)

        if retry_count >= max_retries:
            self.error_occurred.emit("Radio: max retries exceeded")

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def current_track(self) -> str:
        if self._playlist and self._current_index < len(self._playlist):
            return os.path.basename(self._playlist[self._current_index])
        return ""

    @property
    def position(self) -> float:
        if self._audio_data is not None and self.sample_rate > 0:
            return self._position / self.sample_rate
        return 0.0

    @property
    def duration(self) -> float:
        return self._duration
