from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from typeless_local.trace import (
    DictationTrace,
    SessionRecord,
    append_correction,
    changed_terms,
    load_corrections,
)


def _make_record(**overrides) -> SessionRecord:
    now = time.time()
    base = SessionRecord(
        started_at=now,
        ended_at=now + 1.0,
        audio_duration_s=2.5,
        audio_rms=0.05,
        audio_sample_rate=16000,
        raw_asr_text="hello jarvis",
        raw_asr_language="en",
        raw_asr_confidence=0.85,
        refined_text="Hello, Jarvis.",
        focus_app="TextEdit",
        focus_window="Untitled",
        was_pasted=True,
        vocab_terms_used="Jarvis, Typeless",
        hotwords_count=2,
        latency_asr_ms=900,
        latency_refine_ms=1100,
        latency_total_ms=2100,
        asr_model="mlx-whisper:large-v3-turbo",
        refine_model="gpt-5.4-mini",
        app_version="0.2.0+abc1234",
        error=None,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_initial_log_creates_db_and_schema(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    trace.log(_make_record())
    assert db.exists()

    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == 2
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_log_records_all_fields(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    record = _make_record(raw_asr_text="测试 jarvis", refined_text="测试 Jarvis")
    trace.log(record)

    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "SELECT raw_asr_text, refined_text, was_pasted, hotwords_count, error FROM sessions"
        )
        row = cur.fetchone()
        assert row == ("测试 jarvis", "测试 Jarvis", 1, 2, None)
    finally:
        conn.close()


def test_log_error_field(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    record = _make_record(error="dropped: low volume", refined_text="")
    trace.log(record)
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT error FROM sessions")
        assert cur.fetchone()[0] == "dropped: low volume"
    finally:
        conn.close()


def test_log_does_not_raise_on_io_error(tmp_path: Path) -> None:
    # DictationTrace creates a missing parent dir, so make the parent a file instead.
    blocker = tmp_path / "trace.db"
    blocker.write_text("not a db", encoding="utf-8")
    nested = blocker / "trace.db"
    trace = DictationTrace(nested)
    trace.log(_make_record())   # MUST NOT raise
    # No assertions on file contents — the contract is: never raise.


def test_log_is_atomic_per_call(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    for i in range(5):
        trace.log(_make_record(raw_asr_text=f"row {i}"))
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 5
    finally:
        conn.close()


def test_index_on_started_at_exists(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    trace.log(_make_record())
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_started_at'"
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()


def test_correction_records_the_fragments_that_changed(tmp_path: Path) -> None:
    """A correction stores the words that were wrong, not only the two texts.

    The fragments are what makes the log answerable: counting them says which
    terms the recogniser keeps getting wrong.
    """

    log = tmp_path / "corrections.yaml"
    append_correction(log, 473, "这个函数很好用", "这个方法很好用")

    entries = load_corrections(log)
    assert len(entries) == 1
    assert entries[0]["session"] == 473
    assert entries[0]["before"] == "这个函数很好用"
    assert entries[0]["after"] == "这个方法很好用"
    assert entries[0]["terms"] == [{"wrong": "函数", "right": "方法"}]


def test_corrections_log_is_appended_and_stays_loadable(tmp_path: Path) -> None:
    """Entries accumulate as one YAML list so a bad one can be deleted by hand."""

    log = tmp_path / "corrections.yaml"
    append_correction(log, 1, "第一次", "第一版")
    append_correction(log, 2, "第二次", "第二版")

    assert log.read_text(encoding="utf-8").startswith("#")
    assert [entry["session"] for entry in load_corrections(log)] == [1, 2]


def test_unchanged_correction_records_nothing(tmp_path: Path) -> None:
    log = tmp_path / "corrections.yaml"
    append_correction(log, 1, "一样的文字", "一样的文字")
    assert not log.exists()


def test_changed_terms_marks_insertions_and_deletions() -> None:
    assert changed_terms("能听见吗", "能听见吗67") == [("", "67")]
    assert changed_terms("二三四五六", "二三四") == [("五六", "")]


def test_token_usage_is_stored_and_old_databases_gain_the_columns(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL NOT NULL, ended_at REAL NOT NULL, refined_text TEXT)")
    conn.execute("INSERT INTO sessions (started_at, ended_at, refined_text) VALUES (1, 2, 'old')")
    conn.commit()
    conn.close()
    # The first release's full schema, minus the token columns.
    conn = sqlite3.connect(db)
    for name, kind in (("audio_duration_s", "REAL"), ("audio_rms", "REAL"), ("audio_sample_rate", "INTEGER"),
                       ("raw_asr_text", "TEXT"), ("raw_asr_language", "TEXT"), ("raw_asr_confidence", "REAL"),
                       ("focus_app", "TEXT"), ("focus_window", "TEXT"), ("was_pasted", "INTEGER"),
                       ("vocab_terms_used", "TEXT"), ("hotwords_count", "INTEGER"), ("latency_asr_ms", "INTEGER"),
                       ("latency_refine_ms", "INTEGER"), ("latency_total_ms", "INTEGER"), ("asr_model", "TEXT"),
                       ("refine_model", "TEXT"), ("app_version", "TEXT"), ("error", "TEXT")):
        conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {kind}")
    conn.commit()
    conn.close()

    assert DictationTrace(db).log(_make_record(prompt_tokens=1500, cached_tokens=1469, completion_tokens=90)) is not None
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT refined_text, prompt_tokens, cached_tokens, completion_tokens FROM sessions ORDER BY id").fetchall()
    finally:
        conn.close()
    assert rows[0] == ("old", None, None, None)
    assert rows[1][1:] == (1500, 1469, 90)
