"""The app's names, in one place.

言字 is the name the Chinese interface uses, Yana the English one. The English
name also names the .app file and is what Finder, the Dock and the login-item
list show on a non-Chinese system.

The bundle ID and the ~/.typlus data folder keep the old name on purpose:
macOS ties the microphone and Accessibility permissions it has granted to the
bundle ID, and the folder holds the user's API key, words and history.
"""

from __future__ import annotations

import unicodedata

from typeless_local.i18n import t

DISPLAY_NAME = "言字"
# Placeholder until the English name is chosen; everything else follows it.
ENGLISH_NAME = "Yana"
BUNDLE_ID = "com.alllllenshi.typlus"
# Service name for the API keys kept in the login keychain.
KEYCHAIN_SERVICE = BUNDLE_ID


def _is_cjk(char: str) -> bool:
    if not char:
        return False
    name = unicodedata.name(char, "")
    return name.startswith(("CJK", "HIRAGANA", "KATAKANA", "HANGUL")) or "　" <= char <= "〿" or (
        "＀" <= char <= "￯"
    )


def join(*parts: str) -> str:
    """Join UI words the way Chinese copy spaces them.

    No space between two CJK characters, one space between CJK and Latin:
    ``join("退出", "言字")`` is "退出言字", ``join("退出", "Yana")`` is
    "退出 Yana".
    """

    out = ""
    for part in parts:
        part = str(part or "").strip()
        if not part:
            continue
        if out and not (_is_cjk(out[-1]) and _is_cjk(part[0])):
            out += " "
        out += part
    return out


def display_name() -> str:
    """The app's name in the language it is speaking."""

    return t(DISPLAY_NAME, ENGLISH_NAME)


def quit_label(name: str | None = None) -> str:
    return join(t("退出", "Quit"), name or display_name())


# The author's details live here and nowhere else; the About pane shows what is filled in.
AUTHOR_NAME = "yilun"
AUTHOR_GITHUB = "https://github.com/samsara0xgg"
AUTHOR_EMAIL = ""  # not in the public repo: the build bakes the address in as _version.CONTACT_EMAIL
AUTHOR_LINKS: tuple[tuple[str, str], ...] = ()  # (label, url) pairs
REPO_URL = "https://github.com/samsara0xgg/typeless-local"
RELEASES_URL = f"{REPO_URL}/releases/latest"


def author_email() -> str:
    """The contact address: the one above, else what the build baked into _version.py."""

    if AUTHOR_EMAIL:
        return AUTHOR_EMAIL
    try:
        from typeless_local._version import CONTACT_EMAIL  # noqa: PLC0415

        return str(CONTACT_EMAIL or "")
    except ImportError:
        return ""
