"""Jarvis ASR adapter used by the standalone app."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
import inspect
import logging
import re
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np

LOGGER = logging.getLogger(__name__)


def _without_word_timestamps() -> None:
    """Let mlx_whisper import without numba and scipy.

    The app bundle leaves both out (with llvmlite, about 200 MB): mlx_whisper
    imports them only for word timestamps, which are never asked for. A stand-in
    for its timing module takes their place when they are missing.
    """

    if importlib.util.find_spec("numba") and importlib.util.find_spec("scipy"):
        return

    def add_word_timestamps(*_args, **_kwargs):
        raise RuntimeError("word timestamps are not part of this build")

    timing = ModuleType("mlx_whisper.timing")
    timing.add_word_timestamps = add_word_timestamps
    sys.modules.setdefault("mlx_whisper.timing", timing)


_without_word_timestamps()

_PROMPT_ECHO_RE = re.compile(r"^\s*Common terms:[^\n]*\n", re.IGNORECASE)
_LOOP_RE = re.compile(r"(.{2,16})\1{2,}")
_RUN_RE = re.compile(r"(\S)\1{7,}")
_FALLBACK_TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
# What Whisper says to silence or room noise: video-subtitle credits from its
# training data. Only a transcript that is nothing but one of these is dropped.
_SILENCE_PHRASE_RE = re.compile(
    r"^(优优独播剧场.*|字幕.{0,20}(提供|制作|by.*)|.*请不吝点赞.*|明镜与点点栏目|(谢谢|感谢)(大家)?(收看|观看)"
    r"|thanks? (you )?(so much )?for watching|subtitles by.*)$",
    re.IGNORECASE,
)
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
        language: str | None = None,
    ) -> Transcript:
        """Transcribe mono float32 audio with an optional Whisper initial prompt.

        ``language`` forces the language for this call only.
        """

        effective_prompt = initial_prompt
        with self._prompt_lock, self._language_for_call(language):
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
            if _looks_looped(str(getattr(result, "text", "") or "")) and (
                getattr(self._recognizer, "provider", "") == "mlx_whisper"
            ):
                result = self._rehear_looped(audio)

        text = str(getattr(result, "text", "") or "")
        if initial_prompt:
            text = _strip_prompt_echo(text, effective_prompt or initial_prompt, initial_prompt)
        if _SILENCE_PHRASE_RE.match(re.sub(r"[\s\W_]+$|^[\s\W_]+", "", text)):
            LOGGER.info("Dropping Whisper's silence phrase %r", text[:80])
            text = ""
        return Transcript(
            text=full_width_punctuation(text.strip()),
            language=str(getattr(result, "language", "") or "unknown"),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
        )

    @contextmanager
    def _language_for_call(self, language: str | None):
        """Under the prompt lock: ``language`` for one call, then the user's setting again."""

        if not language:
            yield
            return
        kept = self._recognizer.language
        self._recognizer.language = language
        try:
            yield
        finally:
            self._recognizer.language = kept

    def detect_language(self, audio: np.ndarray) -> dict[str, float]:
        """Whisper's probability for each language it knows, from the first 30 s of ``audio``.

        The same steps mlx_whisper.transcribe takes when no language is set,
        on the model and dtype the recognizer already loaded.
        """

        import mlx.core as mx  # noqa: PLC0415
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim  # noqa: PLC0415
        from mlx_whisper.transcribe import ModelHolder  # noqa: PLC0415

        rec = self._recognizer
        dtype = mx.float16 if rec._mlx_whisper_fp16 else mx.float32
        with self._prompt_lock:
            model = ModelHolder.get_model(rec._mlx_whisper_repo, dtype)
            if not model.is_multilingual:
                return {}
            mel = log_mel_spectrogram(rec._normalize_audio(audio), n_mels=model.dims.n_mels, padding=N_SAMPLES)
            _, probs = model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(dtype))
        return {lang: float(p) for lang, p in probs.items()}

    def _rehear_looped(self, audio: np.ndarray):
        """Decode a looped chunk again with Whisper's temperature fallback.

        At a fixed temperature of 0 greedy decoding can repeat one phrase for the
        whole window; with a temperature schedule mlx_whisper re-samples any
        segment whose compression ratio shows it repeating.
        """

        rec = self._recognizer
        LOGGER.info("Whisper looped; hearing the chunk again with temperature fallback")
        out = rec._load_mlx_whisper().transcribe(
            rec._normalize_audio(audio),
            path_or_hf_repo=rec._mlx_whisper_repo,
            fp16=rec._mlx_whisper_fp16,
            temperature=_FALLBACK_TEMPERATURES,
            language=rec.language,
            initial_prompt=rec._mlx_whisper_initial_prompt,
            condition_on_previous_text=False,
            verbose=False,
        )
        language = str(out.get("language") or rec.language or "unknown")
        return SimpleNamespace(text=str(out.get("text", "")).strip(), language=language, confidence=rec._estimate_confidence(out))

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


_CJK = r"\u3400-\u9fff\uf900-\ufaff"
_HALF_PUNCT = re.compile(rf"(?<=[{_CJK}])\s*([,?!:;])\s*")
_FULL = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}


def full_width_punctuation(text: str) -> str:
    """Whisper often ends a Chinese clause with "," or "?"; Chinese text wants "，" and "？".

    Only after a Chinese character, so "3,000" and English inside stay as they are.
    """

    return _HALF_PUNCT.sub(lambda m: _FULL[m.group(1)], text)


def _looks_looped(text: str) -> bool:
    """A 2-16 character unit repeated three times in a row (我都知道,我都知道,我都知道),
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

