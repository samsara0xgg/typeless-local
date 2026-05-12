"""User-managed vocabulary store for Whisper hotwords and refine prompts."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)

_STARTER_HEADER = """# Typeless Local vocabulary.
# Edit `user:` freely — those terms are never overwritten.
# `auto:` is rewritten by `scripts/extract_hotwords.py`; don't hand-edit it.
"""


def _read_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        LOGGER.warning("Failed to read vocab at %s: %s", path, exc)
        return {}
    if not isinstance(loaded, dict):
        LOGGER.warning("Vocab at %s is not a mapping; ignoring", path)
        return {}
    return loaded


def _coerce_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
    return out


def load_vocab(path: Path) -> list[str]:
    """Return deduplicated terms: user first, then auto. Missing/malformed → []."""

    path = Path(path)
    if not path.exists():
        return []
    data = _read_yaml(path)
    user_terms = _coerce_list(data.get("user"))
    auto_terms = _coerce_list(data.get("auto"))
    seen: set[str] = set()
    result: list[str] = []
    for term in user_terms + auto_terms:
        if term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def as_initial_prompt(terms: list[str], max_chars: int = 600) -> str:
    """Render terms as a single-line Whisper initial prompt.

    Terms are joined comma-separated under a 'Common terms:' prefix. The
    output is truncated at term boundaries to stay under ``max_chars``. The
    first term is always preserved; subsequent terms are added until adding
    one more would exceed the budget.
    """

    if not terms:
        return ""
    prefix = "Common terms: "
    suffix = "."
    budget = max_chars - len(prefix) - len(suffix)
    kept: list[str] = []
    used = 0
    for term in terms:
        addition = (", " if kept else "") + term
        if kept and used + len(addition) > budget:
            break
        kept.append(term)
        used += len(addition)
    return prefix + ", ".join(kept) + suffix


def save_auto_terms(path: Path, terms: list[str]) -> None:
    """Atomically rewrite `auto:` section. Preserves `user:` section."""

    path = Path(path)
    if path.exists():
        data = _read_yaml(path)
        user_terms = _coerce_list(data.get("user"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        user_terms = []

    payload = {
        "user": user_terms,
        "auto": [t for t in terms if t.strip()],
    }
    rendered = _STARTER_HEADER + yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=".vocab-", suffix=".yaml.tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def write_starter_file(path: Path) -> None:
    """Create a starter vocab.yaml with empty lists and a header comment."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text(
        _STARTER_HEADER + "user: []\nauto: []\n",
        encoding="utf-8",
    )
