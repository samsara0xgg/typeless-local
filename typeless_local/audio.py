"""Microphone recording primitives."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

LOGGER = logging.getLogger(__name__)
LevelCallback = Callable[[float], None]


class VoiceActivityAnalyzer:
    """Convert microphone chunks into a smoothed voice-band activity level."""

    def __init__(
        self,
        sample_rate: int,
        fft_size: int = 2048,
        noise_threshold: float = 0.01,
        voice_threshold: float = 0.06,
    ) -> None:
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.noise_threshold = noise_threshold
        self.voice_threshold = voice_threshold
        self._smoothed = 0.0

    def analyze(self, chunk: np.ndarray) -> float:
        """Return a 0..1 level based mostly on vocal-frequency energy."""

        if chunk.size == 0:
            self._smoothed *= 0.25
            return self._smoothed

        raw = max(self._rms_level(chunk) * 0.35, self._voice_band_level(chunk))
        if raw <= self.noise_threshold:
            target = 0.0
        elif raw >= self.voice_threshold:
            target = min(1.0, (raw - self.noise_threshold) / (self.voice_threshold * 2.8))
        else:
            target = ((raw - self.noise_threshold) / (self.voice_threshold - self.noise_threshold)) * 0.35

        if target >= self._smoothed:
            self._smoothed = target
        else:
            self._smoothed = self._smoothed * 0.25 + target * 0.75
        return max(0.0, min(1.0, self._smoothed))

    def _rms_level(self, chunk: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
        return max(0.0, min(1.0, rms * 8.0))

    def _voice_band_level(self, chunk: np.ndarray) -> float:
        fft_size = self.fft_size
        padded = np.zeros(fft_size, dtype=np.float32)
        sample_count = min(chunk.size, fft_size)
        window = np.hanning(sample_count).astype(np.float32)
        padded[:sample_count] = chunk[:sample_count] * window

        spectrum = np.abs(np.fft.rfft(padded)) / (fft_size / 2.0)
        start = min(14, spectrum.size - 1)
        end = min(140, spectrum.size)
        if end <= start:
            return 0.0
        band = spectrum[start:end]
        band_rms = float(np.sqrt(np.mean(np.square(band), dtype=np.float64)))
        return max(0.0, min(1.0, band_rms * 22.0))


class MicrophoneRecorder:
    """Record mono float32 microphone audio until stopped."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        block_duration: float = 0.05,
        on_level: LevelCallback | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_duration = block_duration
        self.on_level = on_level
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._started_at = 0.0
        self._analyzer = VoiceActivityAnalyzer(sample_rate)

    @property
    def is_recording(self) -> bool:
        """Whether an input stream is currently open."""

        return self._stream is not None

    @property
    def elapsed(self) -> float:
        """Elapsed recording seconds."""

        if not self._started_at:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def chunk_count(self) -> int:
        """Number of audio chunks received for the active recording."""

        with self._lock:
            return len(self._chunks)

    def get_volume_level(self, audio: np.ndarray) -> float:
        """Compute normalized RMS volume for mono audio."""

        normalized = np.asarray(audio, dtype=np.float32)
        if normalized.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(normalized), dtype=np.float64)))

    def is_quality_ok(
        self,
        audio: np.ndarray,
        *,
        min_duration: float,
        low_volume_threshold: float,
    ) -> tuple[bool, str]:
        """Validate audio before ASR to avoid Whisper silence hallucinations."""

        normalized = np.asarray(audio, dtype=np.float32)
        duration_seconds = normalized.size / self.sample_rate
        volume_level = self.get_volume_level(normalized)
        issues: list[str] = []

        if normalized.size == 0:
            issues.append("audio is empty")
        if duration_seconds < min_duration:
            issues.append(
                f"duration {duration_seconds:.2f}s is below minimum {min_duration:.2f}s"
            )
        if volume_level < low_volume_threshold:
            issues.append(
                "volume "
                f"{volume_level:.4f} is below threshold {low_volume_threshold:.4f}"
            )

        if issues:
            return False, f"Audio quality warning: {'; '.join(issues)}."
        return True, "Audio quality check passed."

    def start(self) -> None:
        """Start recording."""

        if self._stream is not None:
            return

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is required for microphone recording.") from exc

        self._chunks = []
        self._started_at = time.monotonic()
        blocksize = max(1, int(self.sample_rate * self.block_duration))

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info
            if status:
                LOGGER.warning("Audio input status: %s", status)
            chunk = np.asarray(indata[:, 0], dtype=np.float32).copy()
            with self._lock:
                self._chunks.append(chunk)
            if self.on_level is not None and chunk.size:
                self.on_level(self._analyzer.analyze(chunk))

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=blocksize,
            callback=callback,
        )
        self._stream.start()
        LOGGER.info("Microphone recording started")

    def stop(self) -> np.ndarray:
        """Stop recording and return captured mono audio."""

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                LOGGER.warning("Failed to stop microphone stream cleanly", exc_info=True)
                abort = getattr(stream, "abort", None)
                if abort is not None:
                    try:
                        abort()
                    except Exception:
                        LOGGER.debug("Failed to abort microphone stream", exc_info=True)
            finally:
                try:
                    stream.close()
                except Exception:
                    LOGGER.warning("Failed to close microphone stream", exc_info=True)
        with self._lock:
            chunks = list(self._chunks)
            self._chunks = []
        self._started_at = 0.0
        if not chunks:
            return np.empty(0, dtype=np.float32)
        audio = np.concatenate(chunks, axis=0).astype(np.float32, copy=False)
        LOGGER.info("Microphone recording stopped with %.2fs audio", audio.size / self.sample_rate)
        return audio
