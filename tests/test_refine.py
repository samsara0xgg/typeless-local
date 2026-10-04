from __future__ import annotations

from types import SimpleNamespace

from typeless_local.config import RefineConfig
from typeless_local.mac_integration import FocusContext
from typeless_local.refine import ENGLISH_PRACTICE_PROMPT, SYSTEM_PROMPT, TextRefiner


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


def test_a_refused_trial_raises_trial_unavailable_with_the_reason() -> None:
    from typeless_local.refine import MissingAPIKey, TrialUnavailable

    class _Refused(Exception):
        status_code = 402
        body = {"error": {"code": "trial_used_up", "message": "The free trial on this Mac is used up."}}

    class _Completions:
        def create(self, **kwargs):
            raise _Refused()

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    refiner = TextRefiner(
        RefineConfig(model="gpt-5.6-terra", base_url="https://yana.example.workers.dev/v1", api_key_env="YANA_TRIAL_TOKEN", max_tokens=64),
        client=client,
    )
    try:
        refiner.refine("hello")
    except TrialUnavailable as exc:
        assert exc.code == "trial_used_up"
        assert isinstance(exc, MissingAPIKey)
    else:
        raise AssertionError("a 402 from the trial server must raise TrialUnavailable")


def test_prompt_keeps_the_spoken_language() -> None:
    """An English speaker must never get Chinese back: the prompt assumes no
    language, follows the one spoken, and forbids translating."""

    from typeless_local.refine import SYSTEM_PROMPT

    assert SYSTEM_PROMPT.startswith("You are the auto-editing layer of a system-wide dictation app")
    assert "Write in the language the user spoke" in SYSTEM_PROMPT
    assert "Never translate" in SYSTEM_PROMPT
    assert "always write Simplified Chinese" in SYSTEM_PROMPT
    # No language is assumed for the speaker.
    assert "speaks Chinese" not in SYSTEM_PROMPT
    assert "Users speak" not in SYSTEM_PROMPT


def test_refiner_passes_the_recognizer_language_guess() -> None:
    fake = _FakeClient()
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        client=fake,
    )

    refiner.refine("um can we meet friday", language="en")
    user_prompt = fake.completions.kwargs["messages"][1]["content"]
    assert user_prompt.startswith("Raw transcript:\n<transcript>um can we meet friday</transcript>\n")
    assert "Recognizer's language guess: en" in user_prompt

    refiner.refine("hello", language="unknown")
    assert "language guess" not in fake.completions.kwargs["messages"][1]["content"]
    refiner.refine("hello")
    assert "language guess" not in fake.completions.kwargs["messages"][1]["content"]


# ---- English practice -------------------------------------------------------


def _stream(*pieces, finish="stop", usage=None):
    """Chunks as the SDK yields them; the log records what was read so far."""

    def chunks(log):
        for piece in pieces:
            log.append(piece)
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=piece), finish_reason=None)], usage=None
            )
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish)], usage=None)
        yield SimpleNamespace(choices=[], usage=usage)

    return chunks


def _practice(fake, pieces, **kw):
    log, heard = [], []
    stream = _stream(*pieces, **kw)
    fake.completions.create = lambda **kwargs: (setattr(fake.completions, "kwargs", kwargs), stream(log))[1]
    result = _refiner(fake).refine("你好", english=True, on_text=lambda text: heard.append((text, len(log))))
    return result, heard, log


def test_english_marker_pastes_before_the_english_arrives() -> None:
    usage = SimpleNamespace(prompt_tokens=1500, completion_tokens=90, prompt_tokens_details=SimpleNamespace(cached_tokens=0))
    pieces = ["你好，", "世界。\n<<<", "EN>>>\n", '{"en": "Hello, ', 'world.", "phrases": [{"en": "Hello", "zh": "你好"}]}']
    fake = _FakeClient()

    result, heard, log = _practice(fake, pieces, usage=usage)

    assert heard == [("你好，世界。", 3)]  # fired once, before the JSON was read
    assert result.text == "你好，世界。"
    assert result.english == {"en": "Hello, world.", "phrases": [{"en": "Hello", "zh": "你好"}]}
    assert result.prompt_tokens == 1500
    kwargs = fake.completions.kwargs
    assert kwargs["stream"] is True and kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["max_completion_tokens"] == 128 + 300
    system = kwargs["messages"][0]["content"]
    assert system.startswith(SYSTEM_PROMPT) and system.endswith(ENGLISH_PRACTICE_PROMPT)


def test_english_without_a_marker_is_just_the_refined_text() -> None:
    result, heard, _ = _practice(_FakeClient(), ["你好，", "世界。"])
    assert heard == [("你好，世界。", 2)] and result.text == "你好，世界。" and result.english is None


def test_english_with_bad_json_keeps_the_text_and_drops_the_english() -> None:
    result, heard, _ = _practice(_FakeClient(), ["好的。\n<<<EN>>>\n", '```json\n{"en": ', "oops"])
    assert [h[0] for h in heard] == ["好的。"] and result.text == "好的。" and result.english is None


def test_english_tolerates_code_fences() -> None:
    result, _, _ = _practice(_FakeClient(), ['好的。\n<<<EN>>>\n```json\n{"en": "OK.", "phrases": []}\n```'])
    assert result.english == {"en": "OK.", "phrases": []}


def test_english_cut_off_before_the_marker_falls_back_without_pasting() -> None:
    result, heard, _ = _practice(_FakeClient(), ["前半段"], finish="length")
    assert heard == [] and result.fallback == "truncated" and result.text == "你好"


def test_english_stream_error_after_the_paste_is_not_retried() -> None:
    fake = _FakeClient()
    heard = []

    def broken(**kwargs):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="好的。\n<<<EN>>>"), finish_reason=None)], usage=None)
        raise RuntimeError("reset")

    fake.completions.create = broken
    result = _refiner(fake).refine("好的", english=True, on_text=heard.append)
    assert heard == ["好的。"] and result.text == "好的。" and result.english is None


def test_english_off_stays_non_streaming_and_the_trial_proxy_never_gets_the_instruction() -> None:
    fake = _FakeClient()
    _refiner(fake).refine("hello", english=False, on_text=lambda text: None)
    assert "stream" not in fake.completions.kwargs
    assert ENGLISH_PRACTICE_PROMPT not in fake.completions.kwargs["messages"][0]["content"]

    trial = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://x.example/v1", "YANA_TRIAL_TOKEN", 128, preset="free-trial"), client=fake
    )
    trial.refine("hello", english=True, on_text=lambda text: None)
    assert "stream" not in fake.completions.kwargs
    assert ENGLISH_PRACTICE_PROMPT not in fake.completions.kwargs["messages"][0]["content"]


def test_define_uses_the_cheap_model_on_openai_and_skips_the_trial() -> None:
    fake = _FakeClient()
    openai = RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128)
    assert TextRefiner(openai, client=fake).define("meeting", "A meeting.") == "This is the refined text."
    assert fake.completions.kwargs["model"] == "gpt-5.6-luna"
    other = RefineConfig("deepseek-chat", "https://api.deepseek.com", "DEEPSEEK_API_KEY", 128)
    TextRefiner(other, client=fake).define("meeting", "A meeting.")
    assert fake.completions.kwargs["model"] == "deepseek-chat"
    fake.completions.kwargs = None
    trial_cfg = RefineConfig("m", "https://x", "K", 128, preset="free-trial")
    assert TextRefiner(trial_cfg, client=fake).define("meeting", "A meeting.") is None
    assert fake.completions.kwargs is None
