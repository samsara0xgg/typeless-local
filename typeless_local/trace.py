"""SQLite-backed per-session trace for Typlus."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import logging
import sqlite3
import time
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL NOT NULL,
  ended_at REAL NOT NULL,
  audio_duration_s REAL,
  audio_rms REAL,
  audio_sample_rate INTEGER,
  raw_asr_text TEXT,
  raw_asr_language TEXT,
  raw_asr_confidence REAL,
  refined_text TEXT,
  focus_app TEXT,
  focus_window TEXT,
  was_pasted INTEGER,
  vocab_terms_used TEXT,
  hotwords_count INTEGER,
  latency_asr_ms INTEGER,
  latency_refine_ms INTEGER,
  latency_total_ms INTEGER,
  asr_model TEXT,
  refine_model TEXT,
  app_version TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_started_at ON sessions(started_at);

"""


def changed_terms(before: str, after: str) -> list[tuple[str, str]]:
    """The fragments that actually differ, as ``(before, after)`` pairs.

    Compared character by character, because the text is mostly Chinese and has
    no spaces to split words on. A word the recogniser got wrong comes out as
    one pair; a single wrong character inside a right word comes out as that
    character. An insertion has an empty before, a deletion an empty after.

    ``autojunk`` is off: it treats characters appearing in more than 1% of a
    long text as noise, which for Chinese is most of the common ones, and the
    diff then drifts far from what was actually edited.

    ponytail: raw difflib opcodes, no word segmentation and no merging of edits
    that sit next to each other. Counting them is the reader's job; reach for a
    segmenter only if the single characters prove too noisy to aggregate.
    """

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return [
        (before[i1:i2], after[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]

SCHEMA_VERSION = 1


@dataclass
class SessionRecord:
    started_at: float
    ended_at: float = 0.0
    audio_duration_s: float = 0.0
    audio_rms: float = 0.0
    audio_sample_rate: int = 0
    raw_asr_text: str = ""
    raw_asr_language: str = ""
    raw_asr_confidence: float = 0.0
    refined_text: str = ""
    focus_app: str = ""
    focus_window: str = ""
    was_pasted: bool = False
    vocab_terms_used: str = ""
    hotwords_count: int = 0
    latency_asr_ms: int = 0
    latency_refine_ms: int = 0
    latency_total_ms: int = 0
    asr_model: str = ""
    refine_model: str = ""
    app_version: str = ""
    error: str | None = None


_INSERT_SQL = """
INSERT INTO sessions (
  started_at, ended_at, audio_duration_s, audio_rms, audio_sample_rate,
  raw_asr_text, raw_asr_language, raw_asr_confidence,
  refined_text, focus_app, focus_window, was_pasted,
  vocab_terms_used, hotwords_count,
  latency_asr_ms, latency_refine_ms, latency_total_ms,
  asr_model, refine_model, app_version, error
) VALUES (
  :started_at, :ended_at, :audio_duration_s, :audio_rms, :audio_sample_rate,
  :raw_asr_text, :raw_asr_language, :raw_asr_confidence,
  :refined_text, :focus_app, :focus_window, :was_pasted,
  :vocab_terms_used, :hotwords_count,
  :latency_asr_ms, :latency_refine_ms, :latency_total_ms,
  :asr_model, :refine_model, :app_version, :error
)
"""


class DictationTrace:
    """Append-only per-session log. Never raises from ``log()``."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._initialized = False

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("PRAGMA journal_mode = WAL")
        finally:
            conn.close()
        self._initialized = True

    def log(self, record: SessionRecord) -> int | None:
        """Append one session. Returns its row id, or None when the write failed."""

        try:
            self._ensure_schema()
            params = {
                **record.__dict__,
                "was_pasted": 1 if record.was_pasted else 0,
            }
            conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            try:
                return int(conn.execute(_INSERT_SQL, params).lastrowid)
            finally:
                conn.close()
        except Exception:
            LOGGER.warning(
                "Trace log failed for session started_at=%s",
                getattr(record, "started_at", "?"),
                exc_info=True,
            )
            return None

    def close(self) -> None:  # no-op; connections are per-call
        return None


CORRECTIONS_HEADER = """\
# Corrections you made in the overlay, newest last.
#
# Edit or delete entries freely: nothing reads this file automatically, it is
# raw material for tuning vocab.yaml and the refine prompt, so a test run that
# was not a real correction should just be deleted. `session` joins back to the
# sessions table in trace.db, which holds the raw ASR text for that dictation.
"""


def append_correction(
    path: Path, session_id: int | None, before: str, after: str
) -> None:
    """Append one hand edit to the corrections log. Never raises.

    A file rather than a table because the value of this record is in being
    curated: entries made while testing are not real corrections and have to be
    removable by hand, which sqlite does not invite.
    """

    if before == after:
        return
    entry = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session": session_id,
        "before": before,
        "after": after,
        "terms": [
            {"wrong": wrong, "right": right}
            for wrong, right in changed_terms(before, after)
        ],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write(CORRECTIONS_HEADER)
            handle.write(
                yaml.safe_dump(
                    [entry],
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
            )
    except Exception:
        LOGGER.warning("Correction log failed for session %s", session_id, exc_info=True)


def load_corrections(path: Path) -> list[dict]:
    """Every entry still in the log, or [] when there is none or it is broken."""

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.warning("Could not read corrections log at %s", path, exc_info=True)
        return []
    return [entry for entry in (loaded or []) if isinstance(entry, dict)]
