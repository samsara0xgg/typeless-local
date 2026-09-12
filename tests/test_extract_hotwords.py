from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from scripts.extract_hotwords import (
    extract_candidates,
    find_sample_for_term,
    main,
    run,
    tokenize,
    validate_candidate,
    validate_candidates,
)
from typeless_local.trace import DictationTrace, SessionRecord
from typeless_local.vocab import load_rejected, load_vocab


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
    terms = load_vocab(vocab_path)
    assert "Jarvis" in terms


def test_extract_candidates_skips_rejected_terms(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="working on hermes aging",
            refined_text="Working on Hermes Aging project",
        ))

    candidates = extract_candidates(
        db_path=db, days=30, min_count=2,
        user_terms=set(), stopwords=set(),
        rejected_terms={"hermes aging"},
    )
    terms = [t for t, _c in candidates]
    assert "Hermes Aging" not in terms
    assert "Hermes" not in terms or "Hermes aging" not in terms  # nothing matching


def test_run_loads_rejected_from_vocab(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(
        "user: []\nauto: []\nrejected:\n  - Jarvis\n", encoding="utf-8"
    )
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="hello",
            refined_text="Hello Jarvis",
        ))

    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=1, top_k=10, dry_run=False, llm_validate=False,
    )
    assert "Jarvis" not in load_vocab(vocab_path)


def test_main_reject_flag_moves_term_into_rejected(tmp_path: Path) -> None:
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(
        "user: []\nauto:\n  - Hermes Aging\n  - PyObjC\nrejected: []\n",
        encoding="utf-8",
    )

    code = main(["--vocab", str(vocab_path), "--reject", "Hermes Aging"])

    assert code == 0
    assert load_rejected(vocab_path) == ["Hermes Aging"]
    assert load_vocab(vocab_path) == ["PyObjC"]


class _StubLLM:
    """Fake OpenAI-compatible client. Routes by candidate string."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[str] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        user_msg = kwargs["messages"][1]["content"]
        candidate = ""
        for line in user_msg.splitlines():
            if line.startswith("Candidate term:"):
                candidate = line.split(":", 1)[1].strip()
                break
        self.calls.append(candidate)
        answer = self.answers.get(candidate, "real")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
        )


def test_validate_candidate_real_returns_true() -> None:
    client = _StubLLM({"Jarvis": "real"})
    assert validate_candidate(client, "gpt-5.4-mini", "Jarvis", "tell jarvas", "Tell Jarvis") is True


def test_validate_candidate_mishear_returns_false() -> None:
    client = _StubLLM({"Hermes Aging": "mishear"})
    assert validate_candidate(
        client, "gpt-5.4-mini", "Hermes Aging", "hermes agent", "Hermes Aging"
    ) is False


def test_validate_candidate_keeps_term_on_api_failure() -> None:
    class BrokenClient:
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )

    assert validate_candidate(BrokenClient(), "gpt-5.4-mini", "Jarvis", "x", "y") is True


def test_validate_candidates_filters_mishears(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="tell jarvas", refined_text="Tell Jarvis",
    ))
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hermes agent", refined_text="Hermes Aging",
    ))

    client = _StubLLM({"Jarvis": "real", "Hermes Aging": "mishear"})
    result = validate_candidates(
        [("Jarvis", 3), ("Hermes Aging", 2)],
        db_path=db, days=30, client=client, model="gpt-5.4-mini",
    )
    assert result == [("Jarvis", 3)]
    assert set(client.calls) == {"Jarvis", "Hermes Aging"}


def test_validate_candidates_keeps_term_with_no_sample(tmp_path: Path) -> None:
    """If no trace row has the term, we can't ask the LLM — keep it.

    This shouldn't happen in normal flow (extract_candidates pulls from the
    same DB) but the function must not crash if it does.
    """

    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hello", refined_text="hello world",
    ))

    client = _StubLLM({})
    result = validate_candidates(
        [("Ghost", 5)],
        db_path=db, days=30, client=client, model="gpt-5.4-mini",
    )
    assert result == [("Ghost", 5)]
    assert client.calls == []


def test_find_sample_for_term_returns_matching_row(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    trace = DictationTrace(db)
    now = time.time()
    trace.log(SessionRecord(
        started_at=now, ended_at=now + 1,
        raw_asr_text="hello world", refined_text="Hello world",
    ))
    trace.log(SessionRecord(
        started_at=now + 1, ended_at=now + 2,
        raw_asr_text="tell jarvas", refined_text="Tell Jarvis",
    ))

    sample = find_sample_for_term(db, "Jarvis", days=30)
    assert sample is not None
    raw, refined = sample
    assert "Jarvis" in refined


def test_run_llm_validate_filters_mishears(tmp_path: Path) -> None:
    db = tmp_path / "trace.db"
    vocab_path = tmp_path / "vocab.yaml"
    stopwords_dir = tmp_path / "stops"
    stopwords_dir.mkdir()
    (stopwords_dir / "stopwords-en.txt").write_text("", encoding="utf-8")
    (stopwords_dir / "stopwords-zh.txt").write_text("", encoding="utf-8")

    trace = DictationTrace(db)
    now = time.time()
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="tell jarvas", refined_text="Tell Jarvis",
        ))
    for _ in range(3):
        trace.log(SessionRecord(
            started_at=now, ended_at=now + 1,
            raw_asr_text="hermes agent", refined_text="Hermes Aging",
        ))

    client = _StubLLM({"Jarvis": "real", "Hermes": "real", "Hermes Aging": "mishear", "Aging": "mishear"})
    run(
        db_path=db, vocab_path=vocab_path, stopwords_dir=stopwords_dir,
        days=30, min_count=2, top_k=10, dry_run=False,
        llm_validate=True, llm_client=client,
    )
    terms = load_vocab(vocab_path)
    assert "Jarvis" in terms
    assert "Hermes Aging" not in terms
