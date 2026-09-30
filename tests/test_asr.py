from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np

import typeless_local.asr as asr_module


def _fake_mlx_whisper(monkeypatch, text: str = "hello") -> list[dict]:
    """Install a fake ``mlx_whisper`` so the real vendored recognizer runs."""

    calls: list[dict] = []
    module = ModuleType("mlx_whisper")

    def transcribe(audio, **kwargs):
        calls.append(kwargs)
        return {"text": text, "language": "en", "segments": []}

    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    return calls


def _mlx_config(**asr) -> dict:
    return {"asr": {"provider": "mlx_whisper", "mlx_whisper_initial_prompt": "", "language": "", **asr}}


def test_vocab_prompt_reaches_the_vendored_recognizer(monkeypatch, tmp_path: Path) -> None:
    """The recognizer reads its prompt once at construction; the per-call
    prompt used to be written to a config dict it never had, so it was lost."""

    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1, initial_prompt="Common terms: Jarvis, Typeless.")
    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1)

    assert calls[0]["initial_prompt"] == "Common terms: Jarvis, Typeless."
    assert calls[1]["initial_prompt"] is None


def test_vocab_prompt_follows_the_configured_base_prompt(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config(mlx_whisper_initial_prompt="以下是简体中文。"))

    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1, initial_prompt="Common terms: Jarvis.")

    assert calls[0]["initial_prompt"] == "以下是简体中文。 Common terms: Jarvis."
    assert j._recognizer._mlx_whisper_initial_prompt == "以下是简体中文。"


def test_prompted_whisper_does_not_condition_on_its_own_output(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1, initial_prompt="Common terms: Jarvis.")

    assert calls[0]["condition_on_previous_text"] is False


def test_a_looping_prompted_chunk_is_heard_again_without_the_word_list(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []
    module = ModuleType("mlx_whisper")

    def transcribe(audio, **kwargs):
        calls.append(kwargs)
        text = "我都知道,我都知道,我都知道,我都知道" if len(calls) == 1 else "我都知道了"
        return {"text": text, "language": "zh", "segments": []}

    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    result = j.transcribe(np.ones(16000, dtype=np.float32) * 0.1, initial_prompt="Common terms: Jarvis.")

    assert result.text == "我都知道了"
    assert calls[1]["initial_prompt"] is None


def test_a_run_of_ellipses_counts_as_a_loop() -> None:
    assert asr_module._looks_looped("交互太傻了,你得" + "…" * 200 + "点开来点")
    assert not asr_module._looks_looped("就目前还是感觉这个印象部分……哎呀")


def test_configured_model_is_the_one_loaded_and_reported(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config(mlx_whisper_model="mlx-community/whisper-large-v3"))

    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1)

    assert calls[0]["path_or_hf_repo"] == "mlx-community/whisper-large-v3"
    assert j.model_name == "mlx_whisper:mlx-community/whisper-large-v3"


def test_mlx_whisper_repo_defaults_and_accepts_both_keys() -> None:
    assert asr_module.mlx_whisper_repo({}) == asr_module.DEFAULT_MLX_WHISPER_REPO
    assert asr_module.mlx_whisper_repo({"mlx_whisper_repo": "a/b"}) == "a/b"
    assert asr_module.mlx_whisper_repo({"mlx_whisper_model": "c/d", "mlx_whisper_repo": "a/b"}) == "c/d"


def test_warmup_runs_one_silent_pass(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    j.warmup()

    assert len(calls) == 1


def test_transcribe_passes_prompt_to_backends_that_take_it(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class FakeRecognizer:
        provider = "fake"

        def __init__(self, config):
            pass

        def transcribe(self, audio, initial_prompt=None):
            captured["initial_prompt"] = initial_prompt
            return SimpleNamespace(text="hello", language="en", confidence=0.9)

    fake_module = SimpleNamespace(SpeechRecognizer=FakeRecognizer)
    monkeypatch.setitem(sys.modules, "typeless_local._vendor.jarvis_core.speech_recognizer", fake_module)

    j = asr_module.JarvisASR(tmp_path, {"asr": {"provider": "fake"}})
    j.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="Common terms: Jarvis, Typeless.")

    assert captured["initial_prompt"] == "Common terms: Jarvis, Typeless."


def test_transcribe_strips_prompt_echo(monkeypatch, tmp_path: Path) -> None:
    for echoed, expected in (
        ("Common terms: Jarvis, Typeless.\nhello", "hello"),
        ("Common terms: Jarvis, Typeless. hello", "hello"),
        ("Common terms: Jarvis, Typeless.", ""),
    ):
        _fake_mlx_whisper(monkeypatch, text=echoed)
        j = asr_module.JarvisASR(tmp_path, _mlx_config())

        result = j.transcribe(np.ones(16000, dtype=np.float32) * 0.1, initial_prompt="Common terms: Jarvis, Typeless.")

        assert result.text == expected


def test_set_language_applies_from_the_next_chunk(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_mlx_whisper(monkeypatch)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    j.set_language("zh")
    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1)
    j.set_language("")
    j.transcribe(np.ones(16000, dtype=np.float32) * 0.1)

    assert calls[0]["language"] == "zh"
    assert calls[1]["language"] is None


def test_a_looping_chunk_is_heard_again_with_temperature_fallback(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []
    module = ModuleType("mlx_whisper")

    def transcribe(audio, **kwargs):
        calls.append(kwargs)
        text = "目前是" + "Turbo V3加上" * 30 if len(calls) == 1 else "模型是Turbo V3加上terra"
        return {"text": text, "language": "zh", "segments": []}

    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    j = asr_module.JarvisASR(tmp_path, _mlx_config())

    result = j.transcribe(np.ones(16000, dtype=np.float32) * 0.1)

    assert result.text == "模型是Turbo V3加上terra"
    assert isinstance(calls[1]["temperature"], tuple)
