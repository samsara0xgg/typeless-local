"""Typeless Local — standalone macOS dictation app."""

from __future__ import annotations

import subprocess
from pathlib import Path


def app_version() -> str:
    """Return the running build's version string.

    Resolution order:
    1. ``typeless_local._version.VERSION`` baked by the build script.
    2. ``git rev-parse --short HEAD`` from the repo (dev mode).
    3. ``"unknown"``.
    """

    try:
        from typeless_local._version import VERSION

        if VERSION:
            return str(VERSION)
    except Exception:
        pass
    try:
        repo = Path(__file__).resolve().parent.parent
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True, timeout=2
        ).strip()
        if out:
            return f"0.2.0+{out}"
    except Exception:
        pass
    return "unknown"
