"""Jarvis ASR adapter used by the standalone app."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

LOGGER = logging.getLogger(__name__)

_PROMPT_ECHO_RE = re.compile(r"^\s*Common terms:[^\n]*\n", re.IGNORECASE)
_LOOP_RE = re.compile(r"(.{2,8})\1{2,}")
_RUN_RE = re.compile(r"(\S)\1{7,}")
DEFAULT_MLX_WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"


def mlx_whisper_repo(asr_config: dict) -> str:
    """The Whisper weights the recognizer will load for this ``asr`` section.

    Typlus' config names the key ``mlx_whisper_model`` while the vendored
    recognizer reads ``mlx_whisper_repo``. Both are accepted, ours first, so the
    model that is prefetched, loaded, and recorded in the trace is one model.
    """

    return str(
        asr_config.get("mlx_whisper_model")
        or asr_config.get("mlx_whisper_repo")
        or DEFAULT_MLX_WHISPER_REPO
    ).strip()


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

        config = dict(config)
        asr_config = dict(config.get("asr") or {})
        asr_config["mlx_whisper_repo"] = mlx_whisper_repo(asr_config)
        config["asr"] = asr_config
        self._asr_config = asr_config

        self._recognizer = SpeechRecognizer(config)
        self._accepts_per_call_prompt = self._detect_per_call_prompt()
        # The prompt swap below mutates the recognizer, so two transcriptions
        # (a warm-up and a dictation) must never overlap it.
        self._prompt_lock = threading.Lock()
        LOGGER.info(
            "ASR provider: %s (per-call prompt: %s)",
            self._recognizer.provider,
            self._accepts_per_call_prompt,
        )

    @property
    def model_name(self) -> str:
        provider = str(getattr(self._recognizer, "provider", "unknown"))
        if provider == "mlx_whisper":
            model = str(getattr(self._recognizer, "_mlx_whisper_repo", "") or "")
        else:
            model = str(self._asr_config.get(f"{provider}_model") or self._asr_config.get("model") or "")
        return f"{provider}:{model}" if model else provider

    def set_language(self, language: str) -> None:
        """Recognise ``language`` ("" detects it) from the next chunk on.

        Taken under the prompt lock so a transcription already running keeps
        the language it started with.
        """

        with self._prompt_lock:
            self._recognizer.language = language or None
            self._asr_config["language"] = language or ""

    def _detect_per_call_prompt(self) -> bool:
        try:
            sig = inspect.signature(self._recognizer.transcribe)
            return "initial_prompt" in sig.parameters
        except (TypeError, ValueError):
            return False

    def warmup(self) -> None:
        """Load the weights and run one pass now, so the first dictation doesn't.

        MLX loads the model and compiles on the first transcribe; paying that
        at launch keeps it out of the wait after the user's first dictation.
        """

        started = time.monotonic()
        try:
            with self._prompt_lock:
                self._recognizer.transcribe(np.zeros(16000, dtype=np.float32))
        except Exception:
            LOGGER.warning("ASR warm-up failed; the first dictation will load the model", exc_info=True)
            return
        LOGGER.info("ASR warm-up done in %.2fs", time.monotonic() - started)

    def transcribe(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,
    ) -> Transcript:
        """Transcribe mono float32 audio with an optional Whisper initial prompt."""

        effective_prompt = initial_prompt
        with self._prompt_lock:
            if not initial_prompt:
                result = self._recognizer.transcribe(audio)
            elif self._accepts_per_call_prompt:
                result = self._recognizer.transcribe(audio, initial_prompt=initial_prompt)
            elif getattr(self._recognizer, "provider", "") == "mlx_whisper":
                effective_prompt = " ".join(
                    p for p in (self._recognizer._mlx_whisper_initial_prompt, initial_prompt) if p
                )
                result = self._transcribe_mlx_with_prompt(audio, effective_prompt)
            else:
                LOGGER.warning("ASR backend takes no initial prompt; vocabulary not applied")
                result = self._recognizer.transcribe(audio)

        text = str(getattr(result, "text", "") or "")
        if initial_prompt:
            text = _strip_prompt_echo(text, effective_prompt or initial_prompt, initial_prompt)
        return Transcript(
            text=text.strip(),
            language=str(getattr(result, "language", "") or "unknown"),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
        )

    def _transcribe_mlx_with_prompt(self, audio: np.ndarray, prompt: str):
        """Whisper with the word list in its prompt, falling back to none if it loops.

        The vendored recognizer takes no per-call prompt and is kept verbatim,
        so mlx_whisper is called here. condition_on_previous_text=False stops
        one window's output from feeding the next; with the list in the prompt
        Whisper still sometimes repeats a phrase on noisy audio, and then the
        chunk is heard again without it.
        """

        rec = self._recognizer
        out = rec._load_mlx_whisper().transcribe(
            rec._normalize_audio(audio),
            path_or_hf_repo=rec._mlx_whisper_repo,
            fp16=rec._mlx_whisper_fp16,
            temperature=rec._mlx_whisper_temperature,
            language=rec.language,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            verbose=False,
        )
        text = str(out.get("text", "")).strip()
        if _looks_looped(text):
            LOGGER.info("Whisper looped with the word list (%r); hearing the chunk without it", text[:80])
            return rec.transcribe(audio)
        language = str(out.get("language") or rec.language or "unknown")
        return SimpleNamespace(text=text, language=language, confidence=rec._estimate_confidence(out))


def _looks_looped(text: str) -> bool:
    """A 2-8 character unit repeated three times in a row (我都知道,我都知道,我都知道),
    or one character, punctuation included, eight times (……… by the hundred)."""

    return bool(_LOOP_RE.search(re.sub(r"[\s\W_]+", "", text)) or _RUN_RE.search(text))


def _strip_prompt_echo(text: str, *prompts: str) -> str:
    """Remove a leading copy of the prompt, which Whisper emits on near-silence."""

    stripped = text.lstrip()
    for prompt in prompts:
        prompt = (prompt or "").strip()
        if prompt and stripped.startswith(prompt):
            return stripped[len(prompt):]
    return _PROMPT_ECHO_RE.sub("", text, count=1)

