"""One zip a friend can send along with a bug report.

It holds what the log and settings say about the problem and nothing a
person would mind sharing: API keys are cut out wherever they appear, and the
dictation history (trace.db) is never included.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
import zipfile

# Keys that were never stored here but might still be pasted into a log line.
_KEY_PATTERN = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{12,}|\b[0-9a-f]{32}\.[A-Za-z0-9]{12,}\b")
REDACTED = "[key removed]"
README = """\
Diagnostics from {name} {version}, {when}.

summary.json  this Mac, the app's settings and permissions; which API keys are
              set, never the keys themselves
config.yaml   the settings changed from the defaults
app.log       the app's log; it can quote a few words it recognised, but no
              dictation history is included
"""


def redact(text: str, secrets: list[str]) -> str:
    """``text`` with every secret, and anything shaped like an API key, cut out."""

    for secret in sorted({s for s in secrets if s and len(s) >= 8}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _KEY_PATTERN.sub(REDACTED, text)


def _tail(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        return handle.read().decode("utf-8", errors="replace")


def export(
    dest_dir: Path,
    *,
    name: str,
    version: str,
    summary: dict,
    log_path: Path,
    user_config_path: Path,
    secrets: list[str],
    log_limit: int = 2_000_000,
) -> Path:
    """Write the zip into ``dest_dir`` and return its path."""

    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{name}-diagnostics-{stamp}.zip"
    # The rotated log first, so the newest lines end the file.
    log = _tail(log_path.with_name(log_path.name + ".1"), log_limit // 2) + _tail(log_path, log_limit)
    config = user_config_path.read_text(encoding="utf-8", errors="replace") if user_config_path.exists() else ""
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(name=name, version=version, when=time.strftime("%Y-%m-%d %H:%M")))
        archive.writestr("summary.json", redact(json.dumps(summary, ensure_ascii=False, indent=2, default=str), secrets))
        archive.writestr("config.yaml", redact(config, secrets))
        archive.writestr("app.log", redact(log, secrets))
    return target
