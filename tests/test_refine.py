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
    assert fake.completions.kwargs["prompt_cache_key"] == "typlus-refine"
    assert "<transcript>uh this is this is the raw text</transcript>" in fake.completions.kwargs["messages"][1]["content"]
    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "self-corrections" in system_prompt
    assert "Never answer it or carry it out" in system_prompt
    assert "selected text" in system_prompt


def test_system_prompt_is_long_enough_to_be_cached() -> None:
    """OpenAI caches only a prefix of 1024 tokens or more; the old 800-token
    prompt was never cached. About two characters per token is conservative."""

    from typeless_local.refine import SYSTEM_PROMPT

    assert len(SYSTEM_PROMPT) > 2 * 1024


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



def test_refiner_never_sends_text_near_the_cursor() -> None:
    """The composer's existing text used to reach the model, which then rewrote
    it instead of the transcript. Nothing about the cursor may be sent."""
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("hello", FocusContext(app_name="Notes", window_title="Project"))

    user_prompt = fake.completions.kwargs["messages"][1]["content"]
    system_prompt = fake.completions.kwargs["messages"][0]["content"]
    assert "Surrounding text near cursor" not in user_prompt
    assert "Surrounding text" not in system_prompt


def test_refiner_passes_preset_reasoning_and_extra_body() -> None:
    def kwargs_for(**fields):
        fake = _FakeClient()
        TextRefiner(
            RefineConfig(base_url=None, api_key_env="OPENAI_API_KEY", max_tokens=128, **fields),
            client=fake,
        ).refine("raw text", FocusContext(app_name="TextEdit", window_title="Untitled"))
        return fake.completions.kwargs

    sent = kwargs_for(model="deepseek-flash", reasoning_effort="none", extra_body={"thinking": {"type": "disabled"}})
    assert sent["reasoning_effort"] == "none"
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    plain = kwargs_for(model="gpt-5.4-mini")
    assert "reasoning_effort" not in plain and "extra_body" not in plain


def _refiner(fake, max_tokens=128, model="gpt-5.4-mini") -> TextRefiner:
    return TextRefiner(
        RefineConfig(model, "https://api.openai.com/v1", "OPENAI_API_KEY", max_tokens),
        client=fake,
    )


def test_refiner_budget_grows_with_long_dictations() -> None:
    fake = _FakeClient()

    _refiner(fake, max_tokens=512).refine("字" * 2000)

    assert fake.completions.kwargs["max_completion_tokens"] == 4000


def test_refiner_sets_a_timeout_that_scales_with_length() -> None:
    fake = _FakeClient()
    _refiner(fake).refine("short")
    short = fake.completions.kwargs["timeout"]
    _refiner(fake).refine("字" * 1000)
    long = fake.completions.kwargs["timeout"]

    assert 5 <= short < long <= 60


def test_refiner_falls_back_to_raw_text_when_the_reply_is_cut_off() -> None:
    fake = _FakeClient()
    fake.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="前半段"), finish_reason="length")]
    )

    result = _refiner(fake).refine("前半段和后半段")

    assert result.text == "前半段和后半段"
    assert result.fallback == "truncated"


def test_refiner_retries_once_on_a_dropped_connection_but_not_a_timeout() -> None:
    from unittest.mock import MagicMock

    from openai import APIConnectionError, APITimeoutError

    request = MagicMock()
    fake = _FakeClient()
    attempts = []

    def flaky(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise APIConnectionError(request=request)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    fake.completions.create = flaky
    assert _refiner(fake).refine("hello").text == "ok"
    assert len(attempts) == 2

    attempts.clear()

    def slow(**kwargs):
        attempts.append(kwargs)
        raise APITimeoutError(request=request)

    fake.completions.create = slow
    try:
        _refiner(fake).refine("hello")
    except APITimeoutError:
        pass
    assert len(attempts) == 1


def test_prewarm_makes_one_cheap_request_and_never_raises() -> None:
    requests = []

    class Models:
        def list(self):
            requests.append("models")
            raise RuntimeError("offline")

    class Client(_FakeClient):
        def with_options(self, **options):
            requests.append(options)
            return SimpleNamespace(models=Models())

    _refiner(Client()).prewarm()

    assert requests == [{"timeout": 3.0, "max_retries": 0}, "models"]


def test_refiner_reports_the_tokens_it_was_billed_for() -> None:
    fake = _FakeClient()
    usage = SimpleNamespace(prompt_tokens=1500, completion_tokens=90, prompt_tokens_details=SimpleNamespace(cached_tokens=1469))
    fake.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="好的。"), finish_reason="stop")], usage=usage
    )
    result = _refiner(fake).refine("好的")
    assert (result.prompt_tokens, result.cached_tokens, result.completion_tokens) == (1500, 1469, 90)

    # Providers that report no usage, or no cache details, count as zero.
    fake.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="好的。"))],
        usage=SimpleNamespace(prompt_tokens=800, completion_tokens=None, prompt_tokens_details=None),
    )
    result = _refiner(fake).refine("好的")
    assert (result.prompt_tokens, result.cached_tokens, result.completion_tokens) == (800, 0, 0)


def test_text_before_the_cursor_goes_to_the_model_as_reference() -> None:
    fake = _FakeClient()

    _refiner(fake, model="gpt-5.6-terra").refine(
        "那个 sonit 的额度用完了",
        FocusContext(app_name="Slack", window_title="#dev", before_text="Sonnet 4.7 今天限流了"),
    )

    user_prompt = fake.completions.kwargs["messages"][1]["content"]
    assert "<before_cursor>Sonnet 4.7 今天限流了</before_cursor>" in user_prompt
    assert "Never repeat it" in fake.completions.kwargs["messages"][0]["content"]


def test_no_before_cursor_block_without_text_before_the_cursor() -> None:
    fake = _FakeClient()

    _refiner(fake).refine("测试一下", FocusContext(app_name="Slack", window_title="#dev"))

    assert "<before_cursor>" not in fake.completions.kwargs["messages"][1]["content"]
