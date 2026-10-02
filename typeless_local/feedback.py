"""A feedback message sent to the free-trial Worker, with diagnostics only when asked.

The fixed fields are the app version, macOS version, Mac model and the two
language settings; never any dictated text. The optional diagnostics are the
settings summary and the tail of app.log with API keys cut out (the log can
quote a few recognised words, which is why they are opt-in).
"""

from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess

from typeless_local import diagnostics
from typeless_local.stats import _post

post = _post  # urllib with a timeout, raises on non-2xx; a name tests can replace
MAX_MESSAGE = 4000
MAX_DIAGNOSTICS_BYTES = 48_000  # the Worker refuses more
LOG_LINES = 200


def mac_model() -> str:
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=3)
        return out.stdout.strip()
    except Exception:
        return ""


def diagnostics_text(summary: dict, log_path: Path, secrets: list[str]) -> str:
    """The summary and the last log lines, redacted and cut to fit; the log goes first when cutting."""

    head = diagnostics.redact(json.dumps(summary, ensure_ascii=False, indent=2, default=str), secrets)
    log = diagnostics.redact("\n".join(diagnostics._tail(log_path, 200_000).splitlines()[-LOG_LINES:]), secrets)
    room = MAX_DIAGNOSTICS_BYTES - len(head.encode("utf-8")) - 100
    # Keep the newest end of the log; a summary that alone is too big is cut at its end.
    log = log.encode("utf-8")[-room:].decode("utf-8", errors="ignore") if room > 0 else ""
    text = f"{head}\n\n--- app.log (last {LOG_LINES} lines) ---\n{log}"
    return text.encode("utf-8")[:MAX_DIAGNOSTICS_BYTES].decode("utf-8", errors="ignore")


def build(message: str, email: str, *, version: str, spoken_language: str, ui_language: str, extra: str | None = None) -> dict:
    body = {
        "message": message.strip()[:MAX_MESSAGE],
        "email": email.strip()[:200],
        "version": version,
        "macos": platform.mac_ver()[0],
        "model": mac_model(),
        "spoken_language": spoken_language or "auto",
        "ui_language": ui_language,
    }
    if extra is not None:
        body["diagnostics"] = extra
    return body

