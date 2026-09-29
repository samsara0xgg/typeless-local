"""Typeless-style dictation refinement."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol

from typeless_local.config import RefineConfig
from typeless_local.mac_integration import FocusContext

LOGGER = logging.getLogger(__name__)

# The SDK default is a 600 s timeout with two retries, which leaves a dictation
# on "Thinking" for minutes when the network stalls. The app pastes the raw
# transcript when refinement fails, so failing fast is the better outcome. The
# allowance grows with the transcript because the reply takes longer to write.
REFINE_TIMEOUT_BASE_S = 6.0
REFINE_TIMEOUT_PER_CHAR_S = 0.02
REFINE_TIMEOUT_MAX_S = 60.0
PREWARM_TIMEOUT_S = 3.0


class ChatCompletionsClient(Protocol):
    """Protocol for tests and OpenAI-compatible clients."""

    chat: Any


class MissingAPIKey(RuntimeError):
    """The preset's API key variable is unset, so no request can be made.

    Typed so the UI can say that rather than offering a pointless retry.
    """


@dataclass(frozen=True)
class RefineResult:
    """Final text produced by the refinement pass."""

    text: str
    raw_text: str
    model: str
    # Why ``text`` is the raw transcript rather than the model's output ("" when
    # the model's output was used).
    fallback: str = ""


SYSTEM_PROMPT = """You are the AI auto-editing layer of a system-wide dictation app.
The user speaks naturally; you return only the final text that should be inserted
or replace the selected text in the focused app.

Core behavior:
- Preserve the user's language, including mixed-language phrases.
- When the output is in Chinese, always use Simplified Chinese (简体中文).
  Mixed English is fine, but never output Traditional Chinese characters.
- Remove filler words, false starts, repeated starts, stutters, and verbal hesitation.
- Resolve self-corrections by keeping the final intended wording.
- Add punctuation, capitalization, paragraph breaks, and light formatting.
- Convert clearly spoken structure into text structure: lists, numbered steps,
  short paragraphs, headings, or line breaks when appropriate.
- Preserve names, domain terms, product names, URLs, file paths, code identifiers,
  commands, and uncommon vocabulary exactly when they appear intentional.
- Keep the user's meaning. Improve clarity and flow without adding new facts.

Context awareness:
- Adapt style to the focused app and window.
- Chat apps: concise, natural, send-ready.
- Email/work docs: polished, complete sentences, professional by default.
- Notes/docs: structured and readable, using bullets or paragraphs when useful.
- Code editors/terminals: preserve technical wording and avoid decorative prose.
- If selected text is provided and the transcript is an editing instruction
  (for example: make this shorter, translate this, fix grammar, rewrite as an email),
  return the replacement text for that selection.

Strict output:
- Return only the insertable/replacement text.
- Do not answer as an assistant unless the user's dictated content asks for text to insert.
- Do not include explanations, markdown fences, labels, or surrounding quotes.
"""


class TextRefiner:
    """OpenAI-compatible gpt-5.4-mini refinement client."""

    def __init__(self, config: RefineConfig, client: ChatCompletionsClient | None = None) -> None:
        self.config = config
        self._client = client

    def _get_client(self) -> ChatCompletionsClient:
        if self._client is not None:
            return self._client

        from openai import OpenAI

        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise MissingAPIKey(
                f"{self.config.api_key_env} is required for refinement with {self.config.model}."
            )
        # Retries are done in refine(), only for the errors worth retrying.
        self._client = OpenAI(api_key=api_key, base_url=self.config.base_url, max_retries=0)
        return self._client

    def prewarm(self) -> None:
        """Open a connection to the API now so refine() doesn't pay the handshake.

        Called while the recognizer is still working. The HTTP client only keeps
        an idle connection for a few seconds, so between dictations it is
        almost always gone, and a fresh TCP + TLS setup would otherwise sit in
        front of every refinement. Best-effort: any failure is left for
        refine() to meet and report.
        """

        try:
            client = self._get_client()
            with_options = getattr(client, "with_options", None)
            if with_options is None:
                return
            with_options(timeout=PREWARM_TIMEOUT_S, max_retries=0).models.list()
        except Exception as exc:
            LOGGER.debug("Refine connection prewarm failed: %s", exc)

    def refine(
        self,
        raw_text: str,
        context: FocusContext | None = None,
        vocab: list[str] | None = None,
    ) -> RefineResult:
        """Refine raw ASR text into insertable dictation text."""

        stripped = raw_text.strip()
        if not stripped:
            return RefineResult(text="", raw_text=raw_text, model=self.config.model)

        focus = context or FocusContext(app_name="", window_title="", selected_text="")
        user_prompt = (
            "Raw transcript:\n"
            f"{stripped}\n\n"
            "Focused app context:\n"
            f"- app: {focus.app_name or 'unknown'}\n"
            f"- window: {focus.window_title or 'unknown'}\n"
            f"- selected text: {focus.selected_text or '(none)'}\n"
        )
        system_prompt = SYSTEM_PROMPT
        if vocab:
            joined = ", ".join(vocab)
            system_prompt = (
                SYSTEM_PROMPT
                + "\n\nUser vocabulary (high-confidence terms used frequently by this user):\n"
                + joined
                + "\n\n"
                "Where the raw transcript contains short fragments that are plausibly "
                "mishears of these specific terms (homophones, fuzzy phonetic matches), "
                "replace them with the correct term. Do not invent occurrences — only "
                "correct fragments that already seem to be attempts at one of these terms.\n"
            )
        token_key = "max_completion_tokens" if self.config.model.startswith("gpt-5") else "max_tokens"
        # The configured budget is a floor: a fixed 512 tokens cut anything past
        # about three minutes of Chinese dictation. Two tokens per input
        # character covers Chinese at worst and English with room to spare, and
        # only the tokens actually generated are billed.
        max_tokens = max(self.config.max_tokens, 2 * len(stripped))
        kwargs = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            token_key: max_tokens,
            "timeout": min(
                REFINE_TIMEOUT_MAX_S,
                REFINE_TIMEOUT_BASE_S + REFINE_TIMEOUT_PER_CHAR_S * len(stripped),
            ),
        }
        if self.config.model.startswith("gpt-5.4") and (
            not self.config.base_url or "api.openai.com" in self.config.base_url
        ):
            kwargs["prompt_cache_retention"] = "24h"
        # Per-preset knobs: gpt-5.6 needs reasoning_effort=none and DeepSeek needs
        # thinking disabled, or the whole token budget goes to reasoning and the
        # reply is empty.
        if self.config.reasoning_effort:
            kwargs["reasoning_effort"] = self.config.reasoning_effort
        if self.config.extra_body:
            kwargs["extra_body"] = dict(self.config.extra_body)

        LOGGER.info("Refining transcript with %s", self.config.model)
        client = self._get_client()
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            if not _is_retryable_connection_error(exc):
                raise
            # Typically a pooled connection the server had already closed; a
            # second attempt opens a new one. Timeouts are not retried.
            LOGGER.warning("Refine request failed to connect (%s); retrying once", exc)
            response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = str(choice.message.content or "").strip()
        if getattr(choice, "finish_reason", None) == "length":
            # A cut-off rewrite would silently drop the end of the dictation;
            # the unpolished transcript at least keeps all of it.
            LOGGER.warning("Refinement hit the %d-token limit; using the raw transcript", max_tokens)
            return RefineResult(text=stripped, raw_text=raw_text, model=self.config.model, fallback="truncated")
        if not text:
            return RefineResult(text=stripped, raw_text=raw_text, model=self.config.model, fallback="empty")
        return RefineResult(text=text, raw_text=raw_text, model=self.config.model)


def _is_retryable_connection_error(exc: Exception) -> bool:
    try:
        from openai import APIConnectionError, APITimeoutError
    except ImportError:
        return False
    return isinstance(exc, APIConnectionError) and not isinstance(exc, APITimeoutError)
