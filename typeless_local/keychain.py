"""API keys in the login keychain, read and written through /usr/bin/security.

The command-line tool rather than the Security framework: a keychain item
trusts the program that created it, and an ad-hoc signed rebuild of this app is
a different program every time, so items it created itself would ask for the
login password after each update. /usr/bin/security is signed by Apple and
never changes, so an item it creates can be read back through it silently.

A key is written through ``security -i``, which reads its commands on stdin,
so the key never appears in a process argument list where ``ps`` could show it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess

from typeless_local.brand import KEYCHAIN_SERVICE

LOGGER = logging.getLogger(__name__)

SECURITY = "/usr/bin/security"
TIMEOUT_S = 5.0
# What an API key looks like: printable, no whitespace, nothing that would
# need escaping inside the quoted argument ``security -i`` parses.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=:@-]{8,512}$")
_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def available() -> bool:
    return os.path.exists(SECURITY)


def is_valid_key(value: str) -> bool:
    return bool(_KEY_PATTERN.match(value or ""))


def _check_name(name: str) -> None:
    if not _NAME_PATTERN.match(name or ""):
        raise ValueError(f"not an environment variable name: {name!r}")


def read_key(name: str, service: str = KEYCHAIN_SERVICE) -> str | None:
    """The stored key for ``name``, or None when there is none or it can't be read."""

    _check_name(name)
    if not available():
        return None
    try:
        result = subprocess.run(
            [SECURITY, "find-generic-password", "-a", name, "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.warning("Could not read %s from the keychain", name, exc_info=True)
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def store_key(name: str, value: str, service: str = KEYCHAIN_SERVICE) -> bool:
    """Create or replace the key for ``name``; True once it reads back the same."""

    _check_name(name)
    value = (value or "").strip()
    if not is_valid_key(value):
        raise ValueError("that does not look like an API key")
    if not available():
        return False
    # Unquoted on purpose: the pattern above rules out whitespace and quotes,
    # so the line splits the same way whatever quoting rules the tool applies.
    command = f"add-generic-password -U -a {name} -s {service} -w {value}\n"
    try:
        subprocess.run(
            [SECURITY, "-i"],
            input=command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.warning("Could not write %s to the keychain", name, exc_info=True)
        return False
    # ``security -i`` exits 0 whatever its commands did, so the read-back is
    # the only real answer.
    return read_key(name, service) == value


def delete_key(name: str, service: str = KEYCHAIN_SERVICE) -> bool:
    _check_name(name)
    if not available():
        return False
    try:
        result = subprocess.run(
            [SECURITY, "delete-generic-password", "-a", name, "-s", service],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def fill_environ(names: list[str] | tuple[str, ...]) -> list[str]:
    """Put stored keys into os.environ; a variable that is already set wins.

    Returns the names that were filled.
    """

    filled = []
    for name in dict.fromkeys(names):
        if not name or os.environ.get(name):
            continue
        try:
            value = read_key(name)
        except ValueError:
            continue
        if value:
            os.environ[name] = value
            filled.append(name)
    return filled


def migrate_env_file(env_path: Path, names: list[str] | tuple[str, ...]) -> list[str]:
    """Move keys for ``names`` out of the plain-text env file into the keychain.

    A line is only taken out of the file once the keychain returns exactly the
    same value, so a failed write leaves everything where it was. Returns the
    names that moved.
    """

    if not available() or not env_path.exists():
        return []
    wanted = set(names)
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    kept: list[str] = []
    moved: list[str] = []
    for line in lines:
        stripped = line.strip()
        key, sep, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if sep and key in wanted and value and is_valid_key(value):
            try:
                ok = store_key(key, value)
            except ValueError:
                ok = False
            if ok:
                moved.append(key)
                kept.append(f"# {key} is now in the login keychain (service {KEYCHAIN_SERVICE})")
                continue
        kept.append(line)
    if moved:
        tmp = env_path.with_suffix(".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
        LOGGER.info("Moved %s from %s to the keychain", ", ".join(moved), env_path)
    return moved


def masked(value: str | None) -> str:
    """``sk-…a1F`` style: enough to recognise a key without showing it."""

    if not value:
        return ""
    head = value[:3] if len(value) > 10 else ""
    return f"{head}…{value[-3:]}"
