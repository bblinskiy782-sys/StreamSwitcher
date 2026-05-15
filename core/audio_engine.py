"""
Audio Engine - Core audio processing, capture, passthrough, and mixing.
Supports WASAPI (Windows) via sounddevice.
"""
import queue
import threading
import time
from collections.abc import Callable
from enum import Enum

import numpy as np

from core._qt_compat import QObject, Signal

try:
    import sounddevice as sd  # type: ignore
except (ImportError, OSError):  # pragma: no cover - audio runtime optional in tests
    sd = None  # type: ignore[assignment]


class AudioSource(Enum):
    LIVE_INPUT = "live_input"
    MP3_FILE = "mp3_file"
    INTERNET_RADIO = "internet_radio"


class MixMode(Enum):
    """How the engine combines sources."""
    SINGLE = "single"      # exclusive one source
    DUAL = "dual"          # live + (mp3 or radio) mixed together


class AudioEngine(QObject):
    """
    Main audio engine: captures from input device, mixes sources,
    applies DSP, and outputs to selected output device.
    """
    level_updated = Signal(float, float)       # left, right RMS levels
    source_changed = Signal(str)               # new source name
    error_occurred = Signal(str)               # error message
    silence_detected = Signal()                # silence > threshold
    clip_detected = Signal()                   # clipping detected
    source_failed = Signal(str)                # source name that failed (for failover)
    mix_mode_changed = Signal(str)             # new mix mode

    FADE_STEPS = 50
    FADE_DURATION = 1.0   # seconds for full fade
    SILENCE_THRESHOLD = 0.005
    SILENCE_TIMEOUT = 30.0  # seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sample_rate = 44100
        self.channels = 2
        self.blocksize = 1024
        self.dtype = np.float32

        self.input_device: int | None = None
        self.output_device: int | None = None

        self.current_source = AudioSource.LIVE_INPUT
        self._target_source = AudioSource.LIVE_INPUT

        # Mix mode
        self.mix_mode = MixMode.SINGLE
        self.secondary_source = AudioSource.MP3_FILE
        self.live_volume = 1.0
        self.secondary_volume = 0.6

        # Auto-failover
        self.failover_enabled = True
        self.failover_chain = [
            AudioSource.LIVE_INPUT,
            AudioSource.MP3_FILE,
            AudioSource.INTERNET_RADIO,
        ]
        self._last_source_activity = {
            AudioSource.LIVE_INPUT: time.time(),
            AudioSource.MP3_FILE: time.time(),
            AudioSource.INTERNET_RADIO: time.time(),
        }
        self.FAILOVER_TIMEOUT = 8.0

        # Volume / fade
        self.master_volume = 1.0
        self._fade_volume = 1.0
        self._is_fading = False
        self._muted = False

        # DSP
        self.eq_enabled = False
        self.compressor_enabled = False
        self.eq_bands = {60: 0.0, 250: 0.0, 1000: 0.0, 4000: 0.0, 12000: 0.0}
        self.compressor_threshold = -18.0  # dBFS
        self.compressor_ratio = 4.0
        self.compressor_makeup = 6.0       # dB

        # Streams
        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None
        self._running = False

        # Audio buffers
        self._live_buffer = queue.Queue(maxsize=20)
        self._mix_buffer = queue.Queue(maxsize=20)

        # External audio source (MP3 / radio) - injected by source manager
        self._external_audio_callback: Callable | None = None

        # Silence detection
        self._silence_start: float | None = None
        self._silence_fired = False

        # Level metering
        self._level_left = 0.0
        self._level_right = 0.0

        # Streaming output callback
        self._stream_output_callback: Callable | None = None

    # ------------------------------------------------------------------ #
    #  Device management                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_devices() -> list[dict]:
        """Return list of available audio devices."""
        devices = []
        if sd is None:
            return devices
        try:
            for i, dev in enumerate(sd.query_devices()):
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "max_input_channels": dev["max_input_channels"],
                    "max_output_channels": dev["max_output_channels"],
                    "default_samplerate": dev["default_samplerate"],
                    "hostapi": sd.query_hostapis(dev["hostapi"])["name"],
                })
        except Exception:
            pass
        return devices

    def set_input_device(self, device_index: int):
        was_running = self._running
        if was_running:
            self.stop()
        self.input_device = device_index
        if was_running:
            self.start()

    def set_output_device(self, device_index: int):
        was_running = self._running
        if was_running:
            self.stop()
        self.output_device = device_index
        if was_running:
            self.start()

    # ------------------------------------------------------------------ #
    #  Start / Stop                                                        #
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        if sd is None:
            self.error_occurred.emit(
                "sounddevice is not available — running in headless mode"
            )
            return
        self._running = True

        in_dev = self.input_device if (self.input_device is not None and self.input_device >= 0) else None
        out_dev = self.output_device if (self.output_device is not None and self.output_device >= 0) else None

        # --- Output stream (mandatory for playback) ---
        try:
            self._output_stream = sd.OutputStream(
                device=out_dev,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=self._output_callback,
                latency="low",
            )
            self._output_stream.start()
        except Exception as e:
            # Try fallback: first available output device
            self._output_stream = None
            try:
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    if dev["max_output_channels"] >= self.channels:
                        try:
                            self._output_stream = sd.OutputStream(
                                device=i,
                                samplerate=self.sample_rate,
                                channels=self.channels,
                                dtype=self.dtype,
                                blocksize=self.blocksize,
                                callback=self._output_callback,
                                latency="low",
                            )
                            self._output_stream.start()
                            self.output_device = i
                            self.error_occurred.emit(
                                f"Output: использую '{dev['name']}' (default не сработал: {e})"
                            )
                            break
                        except Exception:
                            continue
            except Exception:
                pass
            if self._output_stream is None:
                self._running = False
                self.error_occurred.emit(
                    f"Не удалось открыть выходное устройство: {e}"
                )
                return

        # --- Input stream (optional — failure not fatal) ---
        try:
            self._input_stream = sd.InputStream(
                device=in_dev,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=self._input_callback,
                latency="low",
            )
            self._input_stream.start()
        except Exception as e:
            self._input_stream = None
            self.error_occurred.emit(
                f"Вход недоступен (Live input выключен): {e}"
            )

    def stop(self):
        self._running = False
        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None
        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

    def restart(self):
        self.stop()
        time.sleep(0.1)
        self.start()

    # ------------------------------------------------------------------ #
    #  Source switching with fade                                          #
    # ------------------------------------------------------------------ #

    def switch_source(self, new_source: AudioSource):
        if new_source == self.current_source:
            return
        self._target_source = new_source
        threading.Thread(target=self._do_fade_switch, daemon=True).start()

    def _do_fade_switch(self):
        self._is_fading = True
        # Fade out
        for i in range(self.FADE_STEPS, -1, -1):
            self._fade_volume = i / self.FADE_STEPS
            time.sleep(self.FADE_DURATION / self.FADE_STEPS)

        self.current_source = self._target_source
        self.source_changed.emit(self.current_source.value)

        # Fade in
        for i in range(0, self.FADE_STEPS + 1):
            self._fade_volume = i / self.FADE_STEPS
            time.sleep(self.FADE_DURATION / self.FADE_STEPS)

        self._is_fading = False

    # ------------------------------------------------------------------ #
    #  Audio callbacks                                                     #
    # ------------------------------------------------------------------ #

    def _input_callback(self, indata: np.ndarray, frames: int,
                        time_info, status):
        """Called by sounddevice for each input block."""
        if status:
            pass  # handle xrun silently
        data = indata.copy()
        try:
            self._live_buffer.put_nowait(data)
        except queue.Full:
            pass

        # Silence detection on live input
        if self.current_source == AudioSource.LIVE_INPUT:
            rms = float(np.sqrt(np.mean(data ** 2)))
            if rms < self.SILENCE_THRESHOLD:
                if self._silence_start is None:
                    self._silence_start = time.time()
                elif (time.time() - self._silence_start > self.SILENCE_TIMEOUT
                      and not self._silence_fired):
                    self._silence_fired = True
                    self.silence_detected.emit()
            else:
                self._silence_start = None
                self._silence_fired = False

    def _output_callback(self, outdata: np.ndarray, frames: int,
                         time_info, status):
        """Called by sounddevice to fill output buffer."""
        if not self._running:
            outdata[:] = 0
            return

        audio = self._get_current_audio(frames)

        # Apply DSP
        if self.eq_enabled:
            audio = self._apply_eq(audio)
        if self.compressor_enabled:
            audio = self._apply_compressor(audio)

        # Apply fade and master volume
        effective_vol = self._fade_volume * self.master_volume
        if self._muted:
            effective_vol = 0.0
        audio = audio * effective_vol

        # Clip detection
        if np.any(np.abs(audio) >= 0.99):
            self.clip_detected.emit()

        # Level metering
        if audio.shape[1] >= 2:
            self._level_left = float(np.sqrt(np.mean(audio[:, 0] ** 2)))
            self._level_right = float(np.sqrt(np.mean(audio[:, 1] ** 2)))
        else:
            lvl = float(np.sqrt(np.mean(audio ** 2)))
            self._level_left = self._level_right = lvl
        self.level_updated.emit(self._level_left, self._level_right)

        # Send to streaming encoder
        if self._stream_output_callback:
            try:
                self._stream_output_callback(audio)
            except Exception:
                pass

        outdata[:] = np.clip(audio, -1.0, 1.0)

    def _get_current_audio(self, frames: int) -> np.ndarray:
        """Get audio block from the current source (or mix)."""
        silence = np.zeros((frames, self.channels), dtype=self.dtype)

        # ---- DUAL MIX MODE ----
        if self.mix_mode == MixMode.DUAL:
            live = self._get_live_audio(frames)
            secondary = self._get_external_audio(frames, self.secondary_source)
            mixed = (live * self.live_volume +
                     secondary * self.secondary_volume)
            return mixed

        # ---- SINGLE MODE ----
        if self.current_source == AudioSource.LIVE_INPUT:
            audio = self._get_live_audio(frames)
            if np.any(np.abs(audio) > 0.001):
                self._last_source_activity[AudioSource.LIVE_INPUT] = time.time()
            return audio

        elif self.current_source in (AudioSource.MP3_FILE,
                                     AudioSource.INTERNET_RADIO):
            audio = self._get_external_audio(frames, self.current_source)
            if np.any(np.abs(audio) > 0.001):
                self._last_source_activity[self.current_source] = time.time()
            return audio

        return silence

    def _get_live_audio(self, frames: int) -> np.ndarray:
        """Get one block of live input audio."""
        silence = np.zeros((frames, self.channels), dtype=self.dtype)
        try:
            data = self._live_buffer.get_nowait()
            if data.shape[0] != frames:
                data = self._resize_block(data, frames)
            return data
        except queue.Empty:
            return silence

    def _get_external_audio(self, frames: int, source: AudioSource) -> np.ndarray:
        """Get one block from file/radio via callback."""
        silence = np.zeros((frames, self.channels), dtype=self.dtype)
        if self._external_audio_callback:
            try:
                data = self._external_audio_callback(frames)
                if data is not None:
                    if data.shape[0] != frames:
                        data = self._resize_block(data, frames)
                    return data
            except Exception:
                pass
        return silence

    def _resize_block(self, data: np.ndarray, frames: int) -> np.ndarray:
        if data.shape[0] > frames:
            return data[:frames]
        pad = np.zeros((frames - data.shape[0], self.channels), dtype=self.dtype)
        return np.vstack([data, pad])

    # ------------------------------------------------------------------ #
    #  DSP                                                                 #
    # ------------------------------------------------------------------ #

    def _apply_eq(self, audio: np.ndarray) -> np.ndarray:
        """Simple peak EQ using biquad filters (approximated)."""
        try:
            from scipy.signal import iirpeak, sosfilt
            result = audio.copy()
            for freq, gain_db in self.eq_bands.items():
                if abs(gain_db) < 0.1:
                    continue
                Q = 1.0
                w0 = freq / (self.sample_rate / 2)
                if w0 >= 1.0:
                    continue
                sos = iirpeak(w0, Q, fs=2.0)
                # Apply gain
                gain_linear = 10 ** (gain_db / 20.0)
                for ch in range(result.shape[1]):
                    filtered = sosfilt(sos, result[:, ch])
                    result[:, ch] = result[:, ch] + (filtered - result[:, ch]) * (gain_linear - 1)
            return result
        except Exception:
            return audio

    def _apply_compressor(self, audio: np.ndarray) -> np.ndarray:
        """Simple feed-forward compressor/limiter."""
        threshold_linear = 10 ** (self.compressor_threshold / 20.0)
        makeup_linear = 10 ** (self.compressor_makeup / 20.0)
        ratio = self.compressor_ratio

        result = audio.copy()
        rms = np.sqrt(np.mean(result ** 2))
        if rms > threshold_linear:
            over = rms / threshold_linear
            gain_reduction = over ** (1.0 / ratio - 1.0)
            result = result * gain_reduction

        result = result * makeup_linear
        return result

    # ------------------------------------------------------------------ #
    #  Controls                                                            #
    # ------------------------------------------------------------------ #

    def set_mute(self, muted: bool):
        self._muted = muted

    def set_volume(self, volume: float):
        """Set master volume 0.0 - 1.0"""
        self.master_volume = max(0.0, min(1.0, volume))

    def set_live_volume(self, volume: float):
        """Set live input volume for dual mode 0.0 - 1.0"""
        self.live_volume = max(0.0, min(1.0, volume))

    def set_secondary_volume(self, volume: float):
        """Set secondary source volume for dual mode 0.0 - 1.0"""
        self.secondary_volume = max(0.0, min(1.0, volume))

    def set_mix_mode(self, mode: MixMode):
        self.mix_mode = mode
        self.mix_mode_changed.emit(mode.value)

    def set_secondary_source(self, source: AudioSource):
        self.secondary_source = source

    def set_failover_enabled(self, enabled: bool):
        self.failover_enabled = enabled

    def check_failover(self):
        """Called periodically to check if current source is dead."""
        if not self.failover_enabled or not self._running:
            return
        if self.mix_mode == MixMode.DUAL:
            return  # don't failover in dual mode

        now = time.time()
        last_active = self._last_source_activity.get(self.current_source, now)
        if now - last_active > self.FAILOVER_TIMEOUT:
            # Current source is dead, find next in chain
            current_idx = -1
            for i, src in enumerate(self.failover_chain):
                if src == self.current_source:
                    current_idx = i
                    break
            if current_idx >= 0:
                next_idx = (current_idx + 1) % len(self.failover_chain)
                next_src = self.failover_chain[next_idx]
                self.source_failed.emit(self.current_source.value)
                self.switch_source(next_src)
                # Reset timer for new source
                self._last_source_activity[next_src] = now

    def set_eq_band(self, freq: int, gain_db: float):
        self.eq_bands[freq] = gain_db

    def set_compressor(self, threshold_db: float, ratio: float, makeup_db: float):
        self.compressor_threshold = threshold_db
        self.compressor_ratio = ratio
        self.compressor_makeup = makeup_db

    def get_levels(self) -> tuple[float, float]:
        return self._level_left, self._level_right
