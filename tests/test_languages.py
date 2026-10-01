from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from typeless_local import languages


def _mac(monkeypatch, preferred, sources) -> None:
    foundation = ModuleType("Foundation")
    foundation.NSLocale = SimpleNamespace(preferredLanguages=lambda: preferred)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setattr(languages, "_input_source_languages", lambda: sources)
    monkeypatch.setattr(languages, "_system", None)


def test_system_languages_are_base_codes_whisper_knows(monkeypatch) -> None:
    _mac(monkeypatch, ["en-CA", "zh-Hans-CA"], ["en", "ja", "tlh"])

    assert languages.load_system() == {"en", "zh", "ja"}  # "tlh" (Klingon) is not a Whisper language


def test_a_failing_source_leaves_the_others(monkeypatch) -> None:
    _mac(monkeypatch, ["fr-FR"], [])
    monkeypatch.setattr(languages, "_input_source_languages", lambda: 1 / 0)

    assert languages.load_system() == {"fr"}


def test_allowed_adds_heard_languages_and_always_english(monkeypatch) -> None:
    _mac(monkeypatch, ["zh-Hans-CN"], [])
    languages.load_system()

    assert languages.allowed(["de", "xx"]) == {"en", "zh", "de"}
    monkeypatch.setattr(languages, "_system", None)  # not read yet: still English
    assert languages.allowed() == {"en"}


def test_pick_takes_the_likeliest_allowed_language() -> None:
    probs = {"is": 0.5, "zh": 0.3, "en": 0.2}

    assert languages.pick(probs, {"zh", "en"}) == "zh"
    assert languages.pick(probs, {"en"}) == "en"
    assert languages.pick(probs, {"de"}) is None
