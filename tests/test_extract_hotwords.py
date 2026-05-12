from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from scripts.extract_hotwords import (
    extract_candidates,
    tokenize,
    load_stopwords,
    run,
)
from typeless_local.trace import DictationTrace, SessionRecord


def test_tokenize_english() -> None:
    tokens = tokenize("Hello Jarvis, this is mlx-whisper running.")
    assert "Jarvis" in tokens
    assert "mlx-whisper" in tokens
    assert "Hello" in tokens
    assert "is" in tokens  # too short, but tokenize is dumb; filtering removes it


def test_tokenize_chinese() -> None:
    tokens = tokenize("启动贾维斯的语音模块")
    assert "贾维斯" in tokens or "维斯" in tokens or "贾维" in tokens


def test_extract_candidates_finds_added_terms(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="tell jarvas to start",
            refined_text="Tell Jarvis to start",
        ))

    candidates = extract_candidates(
        db_path=db, days=30, min_count=2,
        user_terms=set(), stopwords=set(),
    )
    counts = dict(candidates)
    assert counts.get("Jarvis", 0) >= 2


def test_extract_candidates_filters_stopwords(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hi", refined_text="The Jarvis the Jarvis",
    ))
    candidates = extract_candidates(
        db_path=db, days=30, min_count=1,
        user_terms=set(), stopwords={"the", "a"},
    )
    terms = [t for t, _c in candidates]
    assert "the" not in terms
    assert "The" not in terms


def test_extract_candidates_skips_user_terms_case_insensitive(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="", refined_text="Jarvis is great",
    ))
    candidates = extract_candidates(
        db_path=db, days=30, min_count=1,
        user_terms={"jarvis"}, stopwords=set(),
    )
    terms = [t for t, _c in candidates]
    assert "Jarvis" not in terms


def test_run_dry_run_does_not_write(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("the\nand\n", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("的\n了\n", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hello", refined_text="Hello Jarvis Jarvis",
    ))

    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=2, top_k=10, dry_run=True,
    )
    assert not vocab_path.exists()


def test_run_writes_auto_section(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("the\n", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("的\n", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="tell jarvas", refined_text="Tell Jarvis to go",
        ))

    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=2, top_k=10, dry_run=False,
    )
    from typeless_local.vocab import load_vocab
    terms = load_vocab(vocab_path)
    assert "Jarvis" in terms
