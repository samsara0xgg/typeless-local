from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from typeless_local import keychain


class _FakeSecurity:
    """A login keychain behind a fake /usr/bin/security."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.argvs: list[list[str]] = []

    def run(self, argv, input=None, **kwargs):  # noqa: A002
        self.argvs.append(list(argv))
        if argv[1:] == ["-i"]:
            words = input.split()
            assert words[0] == "add-generic-password"
            account = words[words.index("-a") + 1]
            service = words[words.index("-s") + 1]
            self.items[(account, service)] = words[words.index("-w") + 1]
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        account = argv[argv.index("-a") + 1]
        service = argv[argv.index("-s") + 1]
        if argv[1] == "find-generic-password":
            value = self.items.get((account, service))
            if value is None:
                return SimpleNamespace(returncode=44, stdout="", stderr="not found")
            return SimpleNamespace(returncode=0, stdout=value + "\n", stderr="")
        if argv[1] == "delete-generic-password":
            found = self.items.pop((account, service), None)
            return SimpleNamespace(returncode=0 if found else 44, stdout="", stderr="")
        raise AssertionError(argv)


@pytest.fixture
def security(monkeypatch):
    fake = _FakeSecurity()
    monkeypatch.setattr(keychain, "available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", fake.run)
    return fake


def test_key_is_written_over_stdin_never_in_argv(security) -> None:
    assert keychain.store_key("OPENAI_API_KEY", "sk-test-1234567890")

    assert all("sk-test-1234567890" not in " ".join(argv) for argv in security.argvs)
    assert keychain.read_key("OPENAI_API_KEY") == "sk-test-1234567890"


def test_values_that_would_break_the_command_line_are_refused(security) -> None:
    for bad in ("sk test", 'sk"1234567890', "short", "sk-1234567890\\n"):
        with pytest.raises(ValueError):
            keychain.store_key("OPENAI_API_KEY", bad)
    assert security.items == {}


def test_fill_environ_never_overrides_a_set_variable(security, monkeypatch) -> None:
    security.items[("OPENAI_API_KEY", keychain.KEYCHAIN_SERVICE)] = "sk-from-keychain"
    security.items[("DEEPSEEK_API_KEY", keychain.KEYCHAIN_SERVICE)] = "sk-deepseek-key"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    filled = keychain.fill_environ(["OPENAI_API_KEY", "DEEPSEEK_API_KEY"])

    assert filled == ["DEEPSEEK_API_KEY"]
    assert os.environ["OPENAI_API_KEY"] == "sk-from-shell"
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-deepseek-key"


def test_env_file_keys_move_only_after_the_keychain_reads_them_back(security, tmp_path) -> None:
    env = tmp_path / "env"
    env.write_text("OPENAI_API_KEY=sk-moved-1234567890\nOTHER=keep me\n", encoding="utf-8")

    moved = keychain.migrate_env_file(env, ["OPENAI_API_KEY", "DEEPSEEK_API_KEY"])

    assert moved == ["OPENAI_API_KEY"]
    assert keychain.read_key("OPENAI_API_KEY") == "sk-moved-1234567890"
    text = env.read_text(encoding="utf-8")
    assert "sk-moved" not in text
    assert "OTHER=keep me" in text
    assert oct(env.stat().st_mode & 0o777) == "0o600"


def test_env_file_is_untouched_when_the_keychain_write_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(keychain, "available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        lambda argv, **kw: SimpleNamespace(returncode=44 if "find-generic-password" in argv else 0, stdout="", stderr=""),
    )
    env = tmp_path / "env"
    env.write_text("OPENAI_API_KEY=sk-stays-1234567890\n", encoding="utf-8")

    assert keychain.migrate_env_file(env, ["OPENAI_API_KEY"]) == []
    assert env.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-stays-1234567890\n"


def test_timeouts_read_as_no_key(monkeypatch) -> None:
    monkeypatch.setattr(keychain, "available", lambda: True)

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired("security", 5)

    monkeypatch.setattr(keychain.subprocess, "run", hang)
    assert keychain.read_key("OPENAI_API_KEY") is None


def test_masked_shows_only_the_ends() -> None:
    assert keychain.masked("sk-abcdefghijkla1F") == "sk-…a1F"
    assert keychain.masked("") == ""
