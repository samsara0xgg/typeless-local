"""The language the app speaks: Chinese or English.

Every string a person reads is written where it is used, as a pair:
``t("设置", "Settings")``. The pages in web/ do the same with ``kit.L()``, and
learn the language from the ``env`` message Python sends them. Nothing reads
the language at import time, so switching it redraws everything in place.
"""

from __future__ import annotations

LANGUAGES = ("zh", "en")
# What Settings offers; "auto" follows the Mac's own language.
CHOICES = ("auto", "zh", "en")

_current = "zh"


def system_language() -> str:
    """"zh" when the Mac's first preferred language is Chinese, "en" otherwise."""

    try:
        from Foundation import NSLocale  # noqa: PLC0415

        preferred = NSLocale.preferredLanguages()
        first = preferred[0] if preferred is not None and len(preferred) else ""
    except Exception:
        first = ""
    if not isinstance(first, str) or not first:
        return "zh"
    return "zh" if first.lower().startswith("zh") else "en"


def use(preference: str) -> str:
    """Speak ``preference`` ("zh", "en", or "auto"); returns the language now in use."""

    global _current
    _current = preference if preference in LANGUAGES else system_language()
    return _current


def current() -> str:
    return _current


def t(zh: str, en: str) -> str:
    """``zh`` or ``en``, whichever the app is speaking."""

    return en if _current == "en" else zh
