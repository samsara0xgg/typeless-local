"""Typeless-style dictation refinement."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol

from typeless_local.config import RefineConfig
from typeless_local.mac_integration import FocusContext

LOGGER = logging.getLogger(__name__)


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
        self._client = OpenAI(api_key=api_key, base_url=self.config.base_url)
        return self._client

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
        kwargs = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            token_key: self.config.max_tokens,
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
        response = self._get_client().chat.completions.create(**kwargs)
        text = str(response.choices[0].message.content or "").strip()
        return RefineResult(text=text, raw_text=raw_text, model=self.config.model)
