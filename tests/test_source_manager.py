import pytest
import numpy as np
from core.source_manager import SourceManager
from PySide6.QtCore import QCoreApplication

@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app

@pytest.fixture
def manager(qapp):
    return SourceManager()

def test_source_manager_initialization(manager):
    assert manager.sample_rate == 44100
    assert manager.channels == 2
    assert not manager.is_playing
    assert manager.duration == 0.0

def test_resample(manager):
    # Create a simple 1 second 100Hz tone at 44100
    t = np.linspace(0, 1.0, 44100, endpoint=False)
    audio = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    audio = np.column_stack([audio, audio])

    # Resample to 48000
    resampled = manager._resample(audio, 44100, 48000)

    assert resampled.shape[1] == 2
    # Length should be exactly 48000
    assert resampled.shape[0] == 48000

def test_generate_waveform(manager, qtbot):
    # Generate 2 seconds of silence, then 2 seconds of 1.0
    silence = np.zeros((44100 * 2, 2), dtype=np.float32)
    loud = np.ones((44100 * 2, 2), dtype=np.float32)
    audio = np.vstack([silence, loud])

    with qtbot.waitSignal(manager.waveform_ready, timeout=2000) as blocker:
        manager._generate_waveform(audio, points=100)

    waveform = blocker.args[0]
    assert len(waveform) <= 101

    # First half should be 0, second half should be 1
    midpoint = len(waveform) // 2
    assert np.allclose(waveform[:midpoint-1], 0.0)
    assert np.allclose(waveform[midpoint+1:], 1.0)
