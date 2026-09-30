"""The app's names, in one place.

言字 is the name people see on a Chinese system and throughout the UI copy,
which is written in Chinese. The English name names the .app file and is what
Finder, the Dock and the login-item list show everywhere else.

The bundle ID and the ~/.typlus data folder keep the old name on purpose:
macOS ties the microphone and Accessibility permissions it has granted to the
bundle ID, and the folder holds the user's API key, words and history.
"""

from __future__ import annotations

import unicodedata

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


def quit_label(name: str = DISPLAY_NAME) -> str:
    return join("退出", name)
