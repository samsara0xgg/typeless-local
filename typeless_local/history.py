"""Read and prune the dictation history in trace.db, for the History and Settings windows.

The trace module only ever appends. Everything that reads the table back, or
removes rows at the user's request, lives here.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import statistics
import time

LOGGER = logging.getLogger(__name__)

DAY_S = 86400.0
_COLUMNS = (
    "id, started_at, ended_at, audio_duration_s, raw_asr_text, raw_asr_language, refined_text, "
    "focus_app, focus_window, was_pasted, latency_asr_ms, latency_refine_ms, latency_total_ms, "
    "refine_model, error"
)
# Read only when the column exists: databases from before it keep working.
_OPTIONAL = ("sent_text",)


def _connect(db_path: Path) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()
    return row is not None


def _fallback(error: str) -> str:
    """Why the raw transcript went out instead of the refined text, if it did."""

    error = error or ""
    if not error.startswith("refine"):
        return ""
    if "MissingAPIKey" in error:
        return "key"
    if "Timeout" in error or "timed out" in error:
        return "timeout"
    for kind in ("truncated", "empty"):
        if f"refine {kind}" in error:
            return kind
    return "error"


def recent_sessions(db_path: Path, limit: int = 200) -> list[dict]:
    """The newest sessions that produced text, newest first."""

    try:
        conn = _connect(db_path)
        if conn is None:
            return []
        try:
            if not _has_table(conn):
                return []
            have = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            columns = ", ".join([_COLUMNS, *(name for name in _OPTIONAL if name in have)])
            rows = conn.execute(
                f"SELECT {columns} FROM sessions "
                "WHERE COALESCE(refined_text, '') != '' OR COALESCE(raw_asr_text, '') != '' "
                "ORDER BY started_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        LOGGER.warning("Could not read the history from %s", db_path, exc_info=True)
        return []
    out = []
    for row in rows:
        raw = row["raw_asr_text"] or ""
        refined = row["refined_text"] or ""
        error = row["error"] or ""
        dropped = error.startswith("dropped")
        out.append(
            {
                "id": int(row["id"]),
                "at": float(row["started_at"] or 0.0),
                "app": row["focus_app"] or "",
                "window": row["focus_window"] or "",
                "raw": raw,
                "text": "" if dropped else (refined or raw),
                "pasted": bool(row["was_pasted"]),
                "audio_s": float(row["audio_duration_s"] or 0.0),
                "asr_ms": int(row["latency_asr_ms"] or 0),
                "refine_ms": int(row["latency_refine_ms"] or 0),
                "total_ms": int(row["latency_total_ms"] or 0),
                "model": row["refine_model"] or "",
                "language": row["raw_asr_language"] or "",
                "fallback": _fallback(error),
                "dropped": dropped,
                "sent": (row["sent_text"] or "") if "sent_text" in row.keys() else "",
            }
        )
    return out


def set_sent_text(db_path: Path, session_id: int, text: str) -> bool:
    """Record what dictation ``session_id`` was finally sent as."""

    try:
        conn = _connect(db_path)
        if conn is None:
            return False
        try:
            return conn.execute("UPDATE sessions SET sent_text = ? WHERE id = ?", (text, int(session_id))).rowcount > 0
        finally:
            conn.close()
    except Exception:
        LOGGER.warning("Could not store the sent text of session %s", session_id, exc_info=True)
        return False


def count_sessions(db_path: Path, older_than_days: int = 0) -> int:
    try:
        conn = _connect(db_path)
        if conn is None:
            return 0
        try:
            if not _has_table(conn):
                return 0
            if older_than_days > 0:
                cutoff = time.time() - older_than_days * DAY_S
                row = conn.execute("SELECT COUNT(*) FROM sessions WHERE started_at < ?", (cutoff,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
            return int(row[0])
        finally:
            conn.close()
    except sqlite3.Error:
        LOGGER.warning("Could not count sessions in %s", db_path, exc_info=True)
        return 0


def delete_session(db_path: Path, session_id: int) -> bool:
    try:
        conn = _connect(db_path)
        if conn is None:
            return False
        try:
            if not _has_table(conn):
                return False
            return conn.execute("DELETE FROM sessions WHERE id = ?", (int(session_id),)).rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error:
        LOGGER.warning("Could not delete session %s", session_id, exc_info=True)
        return False


def clear_history(db_path: Path) -> int:
    """Delete every session. Returns how many went."""

    return _delete_where(db_path, "1 = 1", ())


def purge_older_than(db_path: Path, days: int) -> int:
    """Delete sessions older than ``days``; 0 or less deletes nothing."""

    if days <= 0:
        return 0
    return _delete_where(db_path, "started_at < ?", (time.time() - days * DAY_S,))


def _delete_where(db_path: Path, where: str, params: tuple) -> int:
    try:
        conn = _connect(db_path)
        if conn is None:
            return 0
        try:
            if not _has_table(conn):
                return 0
            deleted = conn.execute(f"DELETE FROM sessions WHERE {where}", params).rowcount
            if deleted:
                conn.execute("VACUUM")
            return int(deleted)
        finally:
            conn.close()
    except sqlite3.Error:
        LOGGER.warning("Could not delete history rows from %s", db_path, exc_info=True)
        return 0


def median_refine_ms(db_path: Path, model: str, last: int = 50) -> int | None:
    """Median refine latency over the model's last ``last`` successful refines."""

    try:
        conn = _connect(db_path)
        if conn is None:
            return None
        try:
            if not _has_table(conn):
                return None
            rows = conn.execute(
                "SELECT latency_refine_ms FROM sessions WHERE refine_model = ? AND latency_refine_ms > 0 "
                "AND COALESCE(error, '') = '' ORDER BY started_at DESC LIMIT ?",
                (model, int(last)),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    values = [int(row[0]) for row in rows]
    return int(statistics.median(values)) if values else None


def term_counts(db_path: Path, terms: list[str], days: int = 30) -> dict[str, int]:
    """How many recent dictations used each term, case-insensitively."""

    counts = {term: 0 for term in terms}
    if not terms:
        return counts
    try:
        conn = _connect(db_path)
        if conn is None:
            return counts
        try:
            if not _has_table(conn):
                return counts
            cutoff = time.time() - days * DAY_S
            texts = [
                str(row[0] or "").lower()
                for row in conn.execute(
                    "SELECT refined_text FROM sessions WHERE started_at >= ? AND COALESCE(refined_text, '') != ''",
                    (cutoff,),
                )
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        return counts
    for term in terms:
        needle = term.lower()
        counts[term] = sum(1 for text in texts if needle in text)
    return counts
