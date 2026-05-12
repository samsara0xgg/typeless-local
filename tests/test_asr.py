from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

import typeless_local.asr as asr_module


def test_transcribe_passes_initial_prompt_through(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class FakeRecognizer:
        def __init__(self, config):
            self._config = dict(config)
            self.provider = "fake"

        def transcribe(self, audio, **kwargs):
            captured["initial_prompt"] = kwargs.get(
                "initial_prompt",
                self._config.get("asr", {}).get("mlx_whisper_initial_prompt"),
            )
            return SimpleNamespace(text="hello", language="en", confidence=0.9)

    import sys

    fake_module = SimpleNamespace(SpeechRecognizer=FakeRecognizer)
    fake_pkg = SimpleNamespace(speech_recognizer=fake_module)
    monkeypatch.setitem(sys.modules, "core", fake_pkg)
    monkeypatch.setitem(sys.modules, "core.speech_recognizer", fake_module)

    j = asr_module.JarvisASR(tmp_path, {"asr": {"provider": "fake"}})
    audio = np.zeros(16000, dtype=np.float32)
    j.transcribe(audio, initial_prompt="Common terms: Jarvis, Typeless.")

    # The wrapper must either pass per-call OR mutate config; check both possible paths
    assert captured["initial_prompt"] == "Common terms: Jarvis, Typeless." or \
           j._recognizer._config["asr"]["mlx_whisper_initial_prompt"] == "Common terms: Jarvis, Typeless."


def test_transcribe_strips_prompt_echo_from_short_outputs(monkeypatch, tmp_path: Path) -> None:
    class FakeRecognizer:
        def __init__(self, config):
            self._config = dict(config)
            self.provider = "fake"

        def transcribe(self, audio, **kwargs):
            return SimpleNamespace(
                text="Common terms: Jarvis, Typeless.\nhello",
                language="en",
                confidence=0.9,
            )

    import sys

    fake_module = SimpleNamespace(SpeechRecognizer=FakeRecognizer)
    fake_pkg = SimpleNamespace(speech_recognizer=fake_module)
    monkeypatch.setitem(sys.modules, "core", fake_pkg)
    monkeypatch.setitem(sys.modules, "core.speech_recognizer", fake_module)

    j = asr_module.JarvisASR(tmp_path, {"asr": {"provider": "fake"}})
    audio = np.zeros(16000, dtype=np.float32)
    result = j.transcribe(audio, initial_prompt="Common terms: Jarvis, Typeless.")

    assert result.text == "hello"
