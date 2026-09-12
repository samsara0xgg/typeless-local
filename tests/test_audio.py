from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np

from typeless_local.audio import MicrophoneRecorder, VoiceActivityAnalyzer


def test_microphone_recorder_collects_audio_and_reports_level(monkeypatch) -> None:
    levels = []
    streams = []

    class FakeInputStream:
        def __init__(self, samplerate, channels, dtype, blocksize, callback):
            self.samplerate = samplerate
            self.channels = channels
            self.dtype = dtype
            self.blocksize = blocksize
            self.callback = callback
            self.closed = False
            streams.append(self)

        def start(self) -> None:
            data = np.full((self.blocksize, self.channels), 0.05, dtype=np.float32)
            self.callback(data, self.blocksize, None, None)

        def stop(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(InputStream=FakeInputStream),
    )
    recorder = MicrophoneRecorder(
        sample_rate=16000,
        channels=1,
        block_duration=0.05,
        on_level=levels.append,
    )

    recorder.start()
    audio = recorder.stop()

    assert streams[0].samplerate == 16000
    assert streams[0].blocksize == 800
    assert streams[0].closed is True
    assert np.allclose(audio, np.full(800, 0.05, dtype=np.float32))
    assert 0.0 < levels[0] <= 1.0


def test_microphone_recorder_closes_stream_when_stop_fails(monkeypatch) -> None:
    streams = []

    class FakeInputStream:
        def __init__(self, samplerate, channels, dtype, blocksize, callback):
            self.channels = channels
            self.blocksize = blocksize
            self.callback = callback
            self.aborted = False
            self.closed = False
            streams.append(self)

        def start(self) -> None:
            data = np.full((self.blocksize, self.channels), 0.05, dtype=np.float32)
            self.callback(data, self.blocksize, None, None)

        def stop(self) -> None:
            raise RuntimeError("stop failed")

        def abort(self) -> None:
            self.aborted = True

        def close(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(InputStream=FakeInputStream),
    )
    recorder = MicrophoneRecorder(sample_rate=16000, channels=1, block_duration=0.05)

    recorder.start()
    audio = recorder.stop()

    assert streams[0].aborted is True
    assert streams[0].closed is True
    assert np.allclose(audio, np.full(800, 0.05, dtype=np.float32))


def test_voice_activity_analyzer_prefers_vocal_band_over_silence() -> None:
    analyzer = VoiceActivityAnalyzer(sample_rate=16000)
    silence = np.zeros(800, dtype=np.float32)
    t = np.arange(800, dtype=np.float32) / 16000
    voice = (0.12 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    silent_level = analyzer.analyze(silence)
    voice_levels = [analyzer.analyze(voice) for _ in range(6)]

    assert silent_level == 0.0
    assert voice_levels[0] > 0.05
    assert voice_levels[-1] == voice_levels[0]


def test_voice_activity_analyzer_responds_to_soft_speech_onset() -> None:
    """Soft initial syllables must produce a visible waveform level.

    Previously rms*0.35 ≈ voice_band_level ≈ noise_threshold for soft onsets,
    so the overlay stayed flat for the first ~half-second of dictation while
    audio was already being captured. Thresholds must be low enough that a
    quiet 440Hz tone (amplitude 0.025) registers above zero.
    """

    analyzer = VoiceActivityAnalyzer(sample_rate=16000)
    t = np.arange(800, dtype=np.float32) / 16000
    soft_voice = (0.025 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    level = analyzer.analyze(soft_voice)

    assert level > 0.0


def test_microphone_recorder_quality_gate_rejects_silence_and_short_audio() -> None:
    recorder = MicrophoneRecorder(sample_rate=16000)

    assert recorder.is_quality_ok(
        np.zeros(16000, dtype=np.float32),
        min_duration=0.25,
        low_volume_threshold=0.02,
    )[0] is False
    assert recorder.is_quality_ok(
        np.full(1600, 0.1, dtype=np.float32),
        min_duration=0.25,
        low_volume_threshold=0.02,
    )[0] is False
    assert recorder.is_quality_ok(
        np.full(16000, 0.1, dtype=np.float32),
        min_duration=0.25,
        low_volume_threshold=0.02,
    )[0] is True
