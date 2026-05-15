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
from core.crossfade import CrossfadeConfig, crossfade_blocks
from core.radio_stream import RadioStreamDecoder, RadioStreamError

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
        self._stop_event = threading.Event()

        # Internet radio decoder (ffmpeg-backed, streams MP3/AAC/OGG).
        self._radio_decoder: RadioStreamDecoder | None = None

        # Crossfade
        self.crossfade_config = CrossfadeConfig(duration_sec=0.0, enabled=True)
        self._next_audio_data: np.ndarray | None = None  # preloaded next track
        self._crossfading = False
        self._crossfade_pos = 0
        self._crossfade_frames = 0

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
        # File playback is mutually exclusive with radio.
        self._audio_data = None

        try:
            decoder = RadioStreamDecoder(
                self._radio_url,
                sample_rate=self.sample_rate,
                channels=self.channels,
            )
        except RadioStreamError as e:
            self._playing = False
            self.error_occurred.emit(str(e))
            return

        decoder.on_metadata = lambda title: self.track_changed.emit(title)
        decoder.on_buffering = lambda busy: self.buffering.emit(bool(busy))
        decoder.on_error = lambda msg: self.error_occurred.emit(msg)
        decoder.on_connected = lambda: self.buffering.emit(False)

        self._radio_decoder = decoder
        try:
            decoder.start()
        except RadioStreamError as e:
            self._playing = False
            self._radio_decoder = None
            self.error_occurred.emit(str(e))
            return

        self.track_changed.emit(self._radio_url)

    def stop(self):
        self._stop_internal()

    def stop_radio(self):
        """Stop only the radio decoder, preserving file playback state.

        Runs the actual teardown in a background thread to avoid blocking
        the GUI (the decoder's stop() joins network threads which can take
        several seconds if the HTTP connection is slow to close).
        """
        decoder = self._radio_decoder
        self._radio_decoder = None
        if decoder is not None:
            threading.Thread(
                target=self._stop_decoder_bg, args=(decoder,), daemon=True
            ).start()

    @staticmethod
    def _stop_decoder_bg(decoder):
        try:
            decoder.stop()
        except Exception:
            pass

    def stop_file(self):
        """Stop file playback but keep the playlist intact."""
        self._playing = False
        self._audio_data = None
        self._position = 0

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
        # Stop the radio decoder in background to avoid blocking the GUI.
        decoder = self._radio_decoder
        self._radio_decoder = None
        if decoder is not None:
            threading.Thread(
                target=self._stop_decoder_bg, args=(decoder,), daemon=True
            ).start()

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

        # --- Crossfade logic ---
        cf_frames = self.crossfade_config.frames_for(self.sample_rate)
        remaining = len(self._audio_data) - self._position
        if cf_frames > 0 and remaining <= cf_frames and remaining > 0:
            # We're in the crossfade zone — preload next track if not done.
            if self._next_audio_data is None and not self._crossfading:
                self._preload_next_track()
            if self._next_audio_data is not None:
                # Mix: fade out current, fade in next.
                progress = 1.0 - (remaining / cf_frames)  # 0→1
                fade_out = 1.0 - progress
                fade_in = progress
                next_pos = self._crossfade_pos
                next_end = next_pos + len(chunk)
                if next_end <= len(self._next_audio_data):
                    next_chunk = self._next_audio_data[next_pos:next_end]
                    self._crossfade_pos = next_end
                    chunk = (chunk * fade_out + next_chunk * fade_in).astype(np.float32)
                    self._crossfading = True

        # If crossfade finished (track ended), switch to next track seamlessly.
        if self._position >= len(self._audio_data) and self._next_audio_data is not None:
            self._audio_data = self._next_audio_data
            self._position = self._crossfade_pos
            self._next_audio_data = None
            self._crossfading = False
            self._crossfade_pos = 0
            self._duration = len(self._audio_data) / self.sample_rate
            self.duration_updated.emit(self._duration)
            if self._playlist and self._current_index < len(self._playlist) - 1:
                self._current_index += 1
                self.track_changed.emit(os.path.basename(
                    self._playlist[self._current_index]))
            return chunk

        # Emit position
        pos_sec = self._position / self.sample_rate
        self.position_updated.emit(pos_sec)

        # Pad if needed
        if len(chunk) < frames:
            pad = np.zeros((frames - len(chunk), self.channels), dtype=np.float32)
            chunk = np.vstack([chunk, pad])

        return chunk.astype(np.float32)

    def _preload_next_track(self) -> None:
        """Load the next track in playlist into _next_audio_data for crossfade."""
        if not self._playlist:
            return
        next_idx = self._current_index + 1
        if next_idx >= len(self._playlist):
            return  # no next track
        path = self._playlist[next_idx]
        try:
            audio_data, sr = self._load_audio(path)
            if audio_data is None:
                return
            if sr != self.sample_rate:
                audio_data = self._resample(audio_data, sr, self.sample_rate)
            if audio_data.ndim == 1:
                audio_data = np.column_stack([audio_data, audio_data])
            elif audio_data.shape[1] == 1:
                audio_data = np.column_stack([audio_data[:, 0], audio_data[:, 0]])
            self._next_audio_data = audio_data.astype(np.float32)
            self._crossfade_pos = 0
        except Exception:
            self._next_audio_data = None

    def _get_radio_frame(self, frames: int) -> np.ndarray | None:
        decoder = self._radio_decoder
        if decoder is None:
            return None
        return decoder.read_pcm(frames)

    def _auto_next(self):
        """Called when a track ends — pick next via AutoDJ or sequential."""
        time.sleep(0.1)
        if not self._playlist:
            self._playing = False
            return

        # If AutoDJ is attached, let it pick the next track.
        if hasattr(self, '_autodj') and self._autodj and self._autodj.rules.enabled:
            next_path = self._autodj.next_track(self._playlist)
            if next_path:
                if next_path in self._playlist:
                    self._current_index = self._playlist.index(next_path)
                self.play_file(next_path)
                return
            # AutoDJ returned None (repeat=off, exhausted) — stop.
            self._playing = False
            return

        # Sequential fallback.
        if self._current_index < len(self._playlist) - 1:
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

    # Streaming radio decoding is now handled by :class:`core.radio_stream.RadioStreamDecoder`,
    # which pipes audio through ffmpeg and correctly strips ICY metadata.
    # The decoder is created in :meth:`play_radio` and read from
    # :meth:`_get_radio_frame`.

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
