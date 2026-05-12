from __future__ import annotations

from types import SimpleNamespace

from typeless_local.config import RefineConfig
from typeless_local.mac_integration import FocusContext
from typeless_local.refine import TextRefiner


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="This is the refined text.")
                )
            ]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_refiner_sends_gpt54_mini_and_returns_only_content() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig(
            model="gpt-5.4-mini",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            max_tokens=128,
        ),
        client=fake,
    )

    result = refiner.refine(
        "uh this is this is the raw text",
        FocusContext(app_name="TextEdit", window_title="Untitled"),
    )

    assert result.text == "This is the refined text."
    assert fake.completions.kwargs["model"] == "gpt-5.4-mini"
    assert fake.completions.kwargs["max_completion_tokens"] == 128
    assert fake.completions.kwargs["prompt_cache_retention"] == "24h"
    assert "Raw transcript" in fake.completions.kwargs["messages"][1]["content"]
    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "Resolve self-corrections" in system_prompt
    assert "Adapt style to the focused app" in system_prompt
    assert "selected text" in system_prompt


def test_refiner_skips_empty_text() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    result = refiner.refine("  ")

    assert result.text == ""
    assert fake.completions.kwargs is None


def test_refiner_appends_vocab_section_when_provided() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine(
        "tell jarvas to start",
        FocusContext(app_name="Slack", window_title="#general"),
        vocab=["Jarvis", "Typeless"],
    )

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" in system_prompt
    assert "Jarvis, Typeless" in system_prompt
    assert "only correct fragments" in system_prompt


def test_refiner_omits_vocab_section_when_empty() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("hello world", vocab=[])

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" not in system_prompt


def test_refiner_omits_vocab_section_when_none() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("hello world")

    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "User vocabulary" not in system_prompt
