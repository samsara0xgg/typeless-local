from __future__ import annotations

from pathlib import Path

import pytest

from typeless_local import vocab


def test_load_vocab_missing_file_returns_empty_list(tmp_path: Path) -> None:
    result = vocab.load_vocab(tmp_path / "missing.yaml")
    assert result == []


def test_load_vocab_combines_user_and_auto_with_user_first(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\n  - Typeless\n"
        "auto:\n  - Hermes Aging\n  - PyObjC\n",
        encoding="utf-8",
    )
    result = vocab.load_vocab(path)
    assert result == ["Jarvis", "Typeless", "Hermes Aging", "PyObjC"]


def test_load_vocab_dedups_term_in_both_user_and_auto(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\nauto:\n  - Jarvis\n  - Typeless\n",
        encoding="utf-8",
    )
    result = vocab.load_vocab(path)
    assert result == ["Jarvis", "Typeless"]


def test_load_vocab_malformed_yaml_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text("not: valid: yaml: [", encoding="utf-8")
    result = vocab.load_vocab(path)
    assert result == []


def test_as_initial_prompt_empty_returns_empty_string() -> None:
    assert vocab.as_initial_prompt([]) == ""


def test_as_initial_prompt_renders_comma_separated() -> None:
    result = vocab.as_initial_prompt(["Jarvis", "Typeless"])
    assert result == "Common terms: Jarvis, Typeless."


def test_as_initial_prompt_truncates_at_term_boundary() -> None:
    terms = ["A" * 100 for _ in range(20)]
    out = vocab.as_initial_prompt(terms, max_chars=300)
    # Should fit under budget and end with '.'
    assert len(out) <= 300
    assert out.endswith(".")
    # First term must always be present.
    assert "A" * 100 in out


def test_save_auto_terms_preserves_user_section(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    path.write_text(
        "user:\n  - Jarvis\n  - Typeless\nauto:\n  - Old\n",
        encoding="utf-8",
    )
    vocab.save_auto_terms(path, ["NewTerm", "AnotherTerm"])
    loaded = vocab.load_vocab(path)
    assert loaded == ["Jarvis", "Typeless", "NewTerm", "AnotherTerm"]


def test_save_auto_terms_creates_file_if_missing(tmp_path: Path) -> None:
    path = tmp_path / "vocab.yaml"
    vocab.save_auto_terms(path, ["Term1"])
    loaded = vocab.load_vocab(path)
    assert loaded == ["Term1"]
