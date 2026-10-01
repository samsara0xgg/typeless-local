"""Anonymous daily usage counts, sent once a day when the user leaves it on.

What is kept and sent, per local day: how many dictations, how many characters
they came to, and what the free trial spent. With a random id for this Mac and
the app version. Never any text, app name or window title. Counted here rather
than read from trace.db, so it still works with history turned off.
"""

from __future__ import annotations

from datetime import date
import json
import logging
from pathlib import Path
import secrets
import ssl
import threading
import urllib.request

LOGGER = logging.getLogger(__name__)

TIMEOUT_S = 10.0
KEEP_DAYS = 14  # unsent days older than this are dropped rather than piling up


class DailyStats:
    def __init__(self, path: Path, version: str) -> None:
        self.path = path
        self.version = version
        self._lock = threading.Lock()
        # Cleared by forget(): a send already under way then neither posts
        # another day nor writes the file back.
        self.enabled = True

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("days"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"id": secrets.token_urlsafe(24), "days": {}}

    def _save(self, data: dict) -> None:
        try:
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            LOGGER.debug("Could not write %s", self.path, exc_info=True)

    def record(self, dictations: int = 0, chars: int = 0, trial_spend: float = 0.0, today: date | None = None) -> None:
        """Add to today's counts; with nothing to add it only marks the app as used today."""

        day = (today or date.today()).isoformat()
        with self._lock:
            if not self.enabled:
                return
            data = self._load()
            counts = data["days"].setdefault(day, {"dictations": 0, "chars": 0, "trial_spend": 0.0})
            counts["dictations"] += dictations
            counts["chars"] += chars
            counts["trial_spend"] = round(counts["trial_spend"] + trial_spend, 6)
            self._save(data)

    def send(self, url: str, today: date | None = None, post=None) -> int:
        """Send every finished day not sent yet; returns how many went out."""

        today = today or date.today()
        with self._lock:
            data = self._load()
        sent = 0
        for day in sorted(data["days"]):
            if day >= today.isoformat():
                continue
            if not self.enabled:
                break
            if (today - date.fromisoformat(day)).days <= KEEP_DAYS:
                counts = data["days"][day]
                payload = {"id": data["id"], "day": day, "version": self.version, **counts}
                try:
                    (post or _post)(url, payload)
                except Exception as exc:
                    LOGGER.info("Usage stats not sent (%s); trying again later", exc)
                    break
                sent += 1
            with self._lock:
                if not self.enabled:
                    break
                current = self._load()
                current["days"].pop(day, None)
                self._save(current)
        return sent

    def forget(self) -> None:
        """Turned off: drop the counts not sent yet."""

        with self._lock:
            self.enabled = False
            try:
                self.path.unlink()
            except OSError:
                pass


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    import certifi  # noqa: PLC0415  (the bundled Python has no system CA store)

    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=context):
        pass  # any non-2xx raises
