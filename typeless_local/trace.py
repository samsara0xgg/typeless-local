"""SQLite-backed per-session trace for typeless-local."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3
from pathlib import Path

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

    def log(self, record: SessionRecord) -> None:
        try:
            self._ensure_schema()
            params = {
                **record.__dict__,
                "was_pasted": 1 if record.was_pasted else 0,
            }
            conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            try:
                conn.execute(_INSERT_SQL, params)
            finally:
                conn.close()
        except Exception:
            LOGGER.warning(
                "Trace log failed for session started_at=%s",
                getattr(record, "started_at", "?"),
                exc_info=True,
            )

    def close(self) -> None:  # no-op; connections are per-call
        return None
