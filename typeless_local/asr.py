"""Jarvis ASR adapter used by the standalone app."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
import re
import sys
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)

_PROMPT_ECHO_RE = re.compile(r"^\s*Common terms:[^\n]*\n", re.IGNORECASE)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    confidence: float


class JarvisASR:
    """Thin adapter around Jarvis' existing SpeechRecognizer."""

    def __init__(self, jarvis_root: Path, config: dict) -> None:
        self.jarvis_root = jarvis_root
        if jarvis_root and str(jarvis_root) not in sys.path:
            sys.path.insert(0, str(jarvis_root))

        try:
            from typeless_local._vendor.jarvis_core.speech_recognizer import SpeechRecognizer
        except ImportError:
            if jarvis_root and str(jarvis_root) not in sys.path:
                sys.path.insert(0, str(jarvis_root))
            from core.speech_recognizer import SpeechRecognizer

        self._recognizer = SpeechRecognizer(config)
        self._accepts_per_call_prompt = self._detect_per_call_prompt()
        LOGGER.info(
            "ASR provider: %s (per-call prompt: %s)",
            self._recognizer.provider,
            self._accepts_per_call_prompt,
        )

    @property
    def model_name(self) -> str:
        cfg = getattr(self._recognizer, "_config", None) or {}
        asr_cfg = cfg.get("asr", {}) if isinstance(cfg, dict) else {}
        provider = getattr(self._recognizer, "provider", "unknown")
        model = asr_cfg.get(f"{provider}_model") or asr_cfg.get("model") or ""
        return f"{provider}:{model}" if model else str(provider)

    def _detect_per_call_prompt(self) -> bool:
        try:
            sig = inspect.signature(self._recognizer.transcribe)
            return "initial_prompt" in sig.parameters
        except (TypeError, ValueError):
            return False

    def transcribe(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,
    ) -> Transcript:
        """Transcribe mono float32 audio with an optional Whisper initial prompt."""

        prior_prompt = None
        if initial_prompt is not None:
            if self._accepts_per_call_prompt:
                result = self._recognizer.transcribe(audio, initial_prompt=initial_prompt)
            else:
                cfg = getattr(self._recognizer, "_config", None)
                if isinstance(cfg, dict):
                    cfg.setdefault("asr", {})
                    prior_prompt = cfg["asr"].get("mlx_whisper_initial_prompt")
                    cfg["asr"]["mlx_whisper_initial_prompt"] = initial_prompt
                try:
                    result = self._recognizer.transcribe(audio)
                finally:
                    if isinstance(cfg, dict) and prior_prompt is not None:
                        cfg["asr"]["mlx_whisper_initial_prompt"] = prior_prompt
        else:
            result = self._recognizer.transcribe(audio)

        text = str(getattr(result, "text", "") or "")
        if initial_prompt:
            text = _PROMPT_ECHO_RE.sub("", text, count=1)
        return Transcript(
            text=text.strip(),
            language=str(getattr(result, "language", "") or "unknown"),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
        )
