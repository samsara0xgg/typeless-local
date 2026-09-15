"""First-launch setup: persisting the API key and skipping the prompt."""

import os
import stat

import pytest

from typeless_local import first_run
from typeless_local.config import load_env_file
from typeless_local.refine import MissingAPIKey, RefineConfig, TextRefiner


def test_write_env_value_creates_the_file_and_is_readable_back(tmp_path) -> None:
    env = tmp_path / "env"

    first_run.write_env_value(env, "OPENAI_API_KEY", "sk-first")

    assert env.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-first\n"
    os.environ.pop("OPENAI_API_KEY", None)
    load_env_file(env)
    assert os.environ["OPENAI_API_KEY"] == "sk-first"
    os.environ.pop("OPENAI_API_KEY", None)


def test_write_env_value_replaces_only_its_own_key(tmp_path) -> None:
    env = tmp_path / "env"
    env.write_text(
        "# a comment\nOPENAI_API_KEY=sk-old\nDEEPSEEK_API_KEY=ds-keep\n",
        encoding="utf-8",
    )

    first_run.write_env_value(env, "OPENAI_API_KEY", "sk-new")

    lines = env.read_text(encoding="utf-8").splitlines()
    assert "OPENAI_API_KEY=sk-new" in lines
    assert "OPENAI_API_KEY=sk-old" not in lines
    assert "DEEPSEEK_API_KEY=ds-keep" in lines
    assert "# a comment" in lines


def test_write_env_value_keeps_the_key_off_other_accounts(tmp_path) -> None:
    """The file holds a secret, so it must not be group- or world-readable."""

    env = tmp_path / "env"

    first_run.write_env_value(env, "OPENAI_API_KEY", "sk-secret")

    mode = stat.S_IMODE(env.stat().st_mode)
    assert mode == 0o600


def test_ensure_api_key_does_not_prompt_when_one_is_already_set(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-present")
    monkeypatch.setattr(
        first_run,
        "prompt_for_api_key",
        lambda *a, **k: pytest.fail("prompted despite a key being set"),
    )

    assert first_run.ensure_api_key("OPENAI_API_KEY", "gpt-5.4-mini", tmp_path / "env") is True


def test_ensure_api_key_stores_what_the_user_types(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(first_run, "prompt_for_api_key", lambda *a, **k: "sk-typed")
    env = tmp_path / "env"

    assert first_run.ensure_api_key("OPENAI_API_KEY", "gpt-5.4-mini", env) is True
    assert os.environ["OPENAI_API_KEY"] == "sk-typed"
    assert "OPENAI_API_KEY=sk-typed" in env.read_text(encoding="utf-8")


def test_ensure_api_key_reports_a_cancelled_prompt(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(first_run, "prompt_for_api_key", lambda *a, **k: None)
    env = tmp_path / "env"

    assert first_run.ensure_api_key("OPENAI_API_KEY", "gpt-5.4-mini", env) is False
    assert not env.exists()


def test_refiner_raises_a_typed_error_when_the_key_is_missing(monkeypatch) -> None:
    """app.py tells the user 'No API key' off this type, not a blind retry."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    refiner = TextRefiner(
        RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128)
    )

    with pytest.raises(MissingAPIKey):
        refiner.refine("hello")
