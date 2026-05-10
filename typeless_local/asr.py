"""Jarvis ASR adapter used by the standalone app."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    """Transcription result normalized for this app."""

    text: str
    language: str
    confidence: float


class JarvisASR:
    """Thin adapter around Jarvis' existing SpeechRecognizer."""

    def __init__(self, jarvis_root: Path, config: dict) -> None:
        self.jarvis_root = jarvis_root
        if str(jarvis_root) not in sys.path:
            sys.path.insert(0, str(jarvis_root))

        from core.speech_recognizer import SpeechRecognizer

        self._recognizer = SpeechRecognizer(config)
        LOGGER.info("ASR provider: %s", self._recognizer.provider)

    def transcribe(self, audio: np.ndarray) -> Transcript:
        """Transcribe mono float32 audio."""

        result = self._recognizer.transcribe(audio)
        text = str(getattr(result, "text", "") or "").strip()
        return Transcript(
            text=text,
            language=str(getattr(result, "language", "") or "unknown"),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
        )
