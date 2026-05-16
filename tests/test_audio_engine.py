import pytest
import numpy as np
from core.audio_engine import AudioEngine, AudioSource, MixMode
from PySide6.QtCore import QCoreApplication

@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app

@pytest.fixture
def engine(qapp):
    return AudioEngine()

def test_engine_initialization(engine):
    assert engine.sample_rate == 44100
    assert engine.channels == 2
    assert engine.current_source == AudioSource.LIVE_INPUT
    assert engine.mix_mode == MixMode.SINGLE

def test_resize_block(engine):
    # Test padding
    small_block = np.ones((500, 2), dtype=np.float32)
    resized = engine._resize_block(small_block, 1024)
    assert resized.shape == (1024, 2)
    assert np.all(resized[:500] == 1.0)
    assert np.all(resized[500:] == 0.0)

    # Test truncation
    large_block = np.ones((2000, 2), dtype=np.float32)
    resized = engine._resize_block(large_block, 1024)
    assert resized.shape == (1024, 2)
    assert np.all(resized == 1.0)

def test_apply_eq(engine):
    engine.eq_enabled = True
    engine.set_eq_band(1000, 6.0) # +6dB at 1kHz

    # Generate 1kHz sine wave
    t = np.linspace(0, 1024/44100, 1024, endpoint=False)
    sine = np.sin(2 * np.pi * 1000 * t).reshape(-1, 1)
    sine = np.column_stack((sine, sine)).astype(np.float32) * 0.1

    # Measure RMS before
    rms_before = np.sqrt(np.mean(sine**2))

    # Apply EQ
    processed = engine._apply_eq(sine)
    rms_after = np.sqrt(np.mean(processed**2))

    # RMS should be higher because of +6dB gain at 1kHz
    assert rms_after > rms_before

def test_apply_compressor(engine):
    engine.compressor_enabled = True
    engine.set_compressor(-20.0, 4.0, 0.0) # Threshold -20dB, Ratio 4:1, Makeup 0dB

    # Generate loud signal (0.8 amplitude is above -20dB)
    loud_signal = np.ones((1024, 2), dtype=np.float32) * 0.8
    rms_before = np.sqrt(np.mean(loud_signal**2))

    processed = engine._apply_compressor(loud_signal)
    rms_after = np.sqrt(np.mean(processed**2))

    # Compressor should reduce gain
    assert rms_after < rms_before

def test_auto_failover_trigger(engine, qtbot):
    engine.failover_enabled = True
    engine.mix_mode = MixMode.SINGLE
    engine.current_source = AudioSource.LIVE_INPUT
    engine._running = True

    # Fake that last activity was 10 seconds ago (timeout is 8)
    engine._last_source_activity[AudioSource.LIVE_INPUT] = engine._last_source_activity[AudioSource.LIVE_INPUT] - 10.0

    with qtbot.waitSignal(engine.source_failed, timeout=1000) as blocker:
        engine.check_failover()

    assert blocker.args[0] == AudioSource.LIVE_INPUT.value
    # Next source in chain should be targeted
    assert engine._target_source == AudioSource.MP3_FILE
