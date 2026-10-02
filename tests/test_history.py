from __future__ import annotations

import time

from typeless_local import history
from typeless_local.trace import DictationTrace, SessionRecord


def _log(trace, **fields):
    record = SessionRecord(started_at=fields.pop("started_at", time.time()), **fields)
    return trace.log(record)


def test_recent_sessions_are_newest_first_and_skip_empty_ones(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    _log(trace, started_at=now - 60, raw_asr_text="first", refined_text="First.", focus_app="Notes")
    _log(trace, started_at=now - 30, raw_asr_text="", refined_text="", error="dropped: low quality")
    _log(
        trace,
        started_at=now - 10,
        raw_asr_text="second",
        refined_text="second",
        error="refine failed, pasted raw transcript: APITimeoutError('Request timed out.')",
    )

    rows = history.recent_sessions(db)

    assert [row["raw"] for row in rows] == ["second", "first"]
    assert rows[0]["fallback"] == "timeout"
    assert rows[1]["text"] == "First." and rows[1]["app"] == "Notes"


def test_retention_only_deletes_when_a_limit_is_chosen(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    _log(trace, started_at=now - 40 * history.DAY_S, raw_asr_text="old", refined_text="Old.")
    _log(trace, started_at=now, raw_asr_text="new", refined_text="New.")

    assert history.purge_older_than(db, 0) == 0
    assert history.count_sessions(db) == 2
    assert history.count_sessions(db, older_than_days=30) == 1
    assert history.purge_older_than(db, 30) == 1
    assert [row["raw"] for row in history.recent_sessions(db)] == ["new"]


def test_delete_and_clear(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    first = _log(trace, raw_asr_text="a", refined_text="A.")
    _log(trace, raw_asr_text="b", refined_text="B.")

    assert history.delete_session(db, first)
    assert history.count_sessions(db) == 1
    assert history.clear_history(db) == 1
    assert history.recent_sessions(db) == []


def test_median_latency_ignores_fallbacks_and_other_models(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    for ms in (900, 1100, 1300):
        _log(trace, raw_asr_text="x", refined_text="X.", refine_model="gpt-5.6-terra", latency_refine_ms=ms)
    _log(trace, raw_asr_text="x", refined_text="x", refine_model="gpt-5.6-terra", latency_refine_ms=8000, error="refine failed")
    _log(trace, raw_asr_text="x", refined_text="X.", refine_model="gpt-5.6-luna", latency_refine_ms=300)

    assert history.median_refine_ms(db, "gpt-5.6-terra") == 1100
    assert history.median_refine_ms(db, "deepseek-flash") is None


def test_missing_database_reads_as_empty(tmp_path) -> None:
    db = tmp_path / "none.db"
    assert history.recent_sessions(db) == []
    assert history.count_sessions(db) == 0
    assert history.term_counts(db, ["Typlus"]) == {"Typlus": 0}


def test_term_counts_are_case_insensitive(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    _log(trace, raw_asr_text="x", refined_text="Ship the PyObjC fix.")
    _log(trace, raw_asr_text="x", refined_text="pyobjc again")

    _log(trace, raw_asr_text="x", refined_text="ask Jarvis, 用 Jev")
    assert history.term_counts(db, ["PyObjC", "Whisper", "Ja", "Jev"]) == {"PyObjC": 2, "Whisper": 0, "Ja": 0, "Jev": 1}


def test_the_sent_text_is_stored_and_read_back(tmp_path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    row = _log(trace, raw_asr_text="明天四点", refined_text="明天四点开会。", was_pasted=True)
    assert history.recent_sessions(db)[0]["sent"] == ""
    assert history.set_sent_text(db, row, "明天三点开会。") is True
    assert history.recent_sessions(db)[0]["sent"] == "明天三点开会。"
    assert history.set_sent_text(tmp_path / "missing.db", row, "x") is False
