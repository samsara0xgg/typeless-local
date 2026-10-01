"""The free trial: refinement on the owner's key for a new Mac with none of its own.

The app talks to worker/ exactly as to OpenAI, with a random per-Mac token as
the API key; the worker keeps the real key and the budget. See worker/src/index.js.
"""

from __future__ import annotations

import logging
import os
import secrets

from typeless_local import keychain

LOGGER = logging.getLogger(__name__)

PRESET = "free-trial"
TOKEN_ENV = "YANA_TRIAL_TOKEN"
OWN_KEY_PRESET = "gpt-5.6-terra"  # what saving an OpenAI key switches to
OWN_KEY_ENV = "OPENAI_API_KEY"
KEYS_URL = "https://platform.openai.com/api-keys"


def ensure_token() -> None:
    """Make sure this Mac has its trial token, in the keychain and the environment."""

    if os.environ.get(TOKEN_ENV):
        return
    token = keychain.read_key(TOKEN_ENV)
    if not token:
        token = secrets.token_urlsafe(32)
        try:
            keychain.store_key(TOKEN_ENV, token)
        except Exception:
            LOGGER.warning("Could not keep the trial token in the keychain", exc_info=True)
    os.environ[TOKEN_ENV] = token


def server(base_url: str | None) -> str:
    """The worker's origin, from the trial preset's ``.../v1`` base URL."""

    url = (base_url or "").rstrip("/")
    return url[: -len("/v1")] if url.endswith("/v1") else url
