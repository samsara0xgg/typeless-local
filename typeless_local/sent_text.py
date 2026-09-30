"""What a dictation finally went out as, after the user fixed it by hand.

After a paste, the text field it landed in is read every so often. When the
field empties (a chat box clears on Enter) or the user moves to another app,
the last reading is the message as sent, and it is stored next to the refined
text so the two can be compared later. Only small fields are watched: a
document is not a message, and its contents are not ours to keep.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

LOGGER = logging.getLogger(__name__)

POLL_S = 0.4
# Long enough to reread and fix a paragraph before sending it.
WATCH_S = 600.0
# The pasted text must show up in the field this soon, or the field cannot be read.
FIND_S = 2.5
# Bigger than this is a document, not a message.
MAX_CHARS = 4000
# A field that drops below this share of its last length was sent (or cleared).
SENT_RATIO = 0.3


def _squash(text: str) -> str:
    return " ".join(str(text or "").split())


class SentTextWatcher:
    """Watches one pasted dictation at a time; a new one ends the previous watch.

    ``read(pid)`` returns the focused text field's value in that process, or
    None when there is none to read; ``front()`` returns the frontmost process.
    ``on_sent(row_id, text)`` is called at most once per watch, from the
    watcher's thread.
    """

    def __init__(
        self,
        read: Callable[[int], str | None],
        front: Callable[[], int],
        on_sent: Callable[[int, str], None],
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read = read
        self._front = front
        self._on_sent = on_sent
        self._sleep = sleep
        self._clock = clock
        self._token = 0
        self._lock = threading.Lock()

    def watch(self, row_id: int | None, pasted: str, pid: int, background: bool = True) -> None:
        if not row_id or not pid or not _squash(pasted):
            return
        with self._lock:
            self._token += 1
            token = self._token
        if background:
            threading.Thread(target=self._run, args=(token, row_id, pasted, pid), name="sent-text", daemon=True).start()
        else:
            self._run(token, row_id, pasted, pid)

    def cancel(self) -> None:
        """A new dictation started: whatever the field holds now is not a sent message."""

        with self._lock:
            self._token += 1

    def _live(self, token: int) -> bool:
        return token == self._token

    def _run(self, token: int, row_id: int, pasted: str, pid: int) -> None:
        try:
            text = self._follow(token, pasted, pid)
        except Exception:
            LOGGER.debug("Stopped watching the pasted text", exc_info=True)
            return
        if text is not None and self._live(token):
            LOGGER.info("Dictation %s went out as %d characters", row_id, len(text))
            self._on_sent(row_id, text)

    def _follow(self, token: int, pasted: str, pid: int) -> str | None:
        start = self._clock()
        needle = _squash(pasted)
        last: str | None = None
        while self._live(token) and self._clock() - start < WATCH_S:
            self._sleep(POLL_S)
            if not self._live(token):
                return None
            if self._front() != pid:
                # Moved on to another app: the field holds what was kept, if
                # it was changed at all.
                return last if last is not None and _squash(last) != needle else None
            value = self._read(pid)
            if last is None:
                if value is not None and needle in _squash(value) and len(value) <= MAX_CHARS:
                    last = value
                elif self._clock() - start > FIND_S:
                    return None  # a field that cannot be read, or not where it went
                continue
            if value is None:
                continue  # focus is briefly elsewhere in the same app
            if len(value) > MAX_CHARS:
                return None
            if len(_squash(value)) < len(_squash(last)) * SENT_RATIO:
                return last
            last = value
        return None
