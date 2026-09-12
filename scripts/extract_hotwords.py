"""Mine the trace DB for likely-hotword candidates and write them to vocab.yaml."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Allow running as both `python scripts/extract_hotwords.py` and `python -m scripts.extract_hotwords`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typeless_local.vocab import (  # noqa: E402
    load_rejected,
    load_vocab,
    reject_term,
    save_auto_terms,
)

_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}")
_CJK_RUN = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """Return likely-hotword candidates from text.

    English: alphanumeric tokens (≥ 2 chars, hyphens kept).
    CJK: overlapping 2-, 3-, and 4-character sliding windows across each
    contiguous run of CJK characters. Overlapping windows give the
    set-difference in ``extract_candidates`` enough granularity to surface
    multi-character terms regardless of where they fall in a longer string.
    """

    if not text:
        return []
    out: list[str] = []
    out.extend(_EN_TOKEN.findall(text))
    for run in _CJK_RUN.findall(text):
        length = len(run)
        for i in range(length):
            for size in (2, 3, 4):
                end = i + size
                if end > length:
                    break
                out.append(run[i:end])
    return out


def load_stopwords(stopwords_dir: Path) -> set[str]:
    stops: set[str] = set()
    for name in ("stopwords-en.txt", "stopwords-zh.txt"):
        path = stopwords_dir / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            term = line.strip()
            if term:
                stops.add(term)
    return stops


def extract_candidates(
    db_path: Path,
    days: int,
    min_count: int,
    user_terms: set[str],
    stopwords: set[str],
    rejected_terms: set[str] | None = None,
) -> list[tuple[str, int]]:
    cutoff = time.time() - days * 86400.0
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT raw_asr_text, refined_text FROM sessions WHERE started_at >= ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    user_lower = {t.lower() for t in user_terms}
    stops_lower = {t.lower() for t in stopwords}
    rejected_lower = {t.lower() for t in (rejected_terms or set())}
    counter: Counter[str] = Counter()
    for raw, refined in rows:
        raw_tokens = set(tokenize(raw or ""))
        ref_tokens = tokenize(refined or "")
        added = [t for t in ref_tokens if t not in raw_tokens]
        for term in added:
            if len(term) < 2:
                continue
            term_lower = term.lower()
            if term_lower in user_lower:
                continue
            if term_lower in stops_lower:
                continue
            if term_lower in rejected_lower:
                continue
            counter[term] += 1

    return [(t, c) for t, c in counter.most_common() if c >= min_count]


def find_sample_for_term(
    db_path: Path, term: str, days: int
) -> tuple[str, str] | None:
    """Return one (raw, refined) row where ``term`` appears in either field.

    Used by ``validate_candidates`` to feed the LLM enough context to judge
    whether a candidate is a deliberate term or an ASR mishear.
    """

    cutoff = time.time() - days * 86400.0
    like = f"%{term}%"
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT raw_asr_text, refined_text FROM sessions"
            " WHERE started_at >= ?"
            " AND (raw_asr_text LIKE ? OR refined_text LIKE ?)"
            " ORDER BY started_at DESC LIMIT 1",
            (cutoff, like, like),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return (row[0] or "", row[1] or "")


_VALIDATE_SYSTEM_PROMPT = (
    "You decide whether a candidate term in a dictation transcript is a real, "
    "intentional word the user said, or a mishear / ASR artifact. "
    "Answer with exactly one word: 'real' or 'mishear'."
)


def validate_candidate(
    client,
    model: str,
    candidate: str,
    raw: str,
    refined: str,
) -> bool:
    """Ask an OpenAI-compatible LLM whether ``candidate`` is real or a mishear.

    Returns True when the model answers 'real' (or anything starting with it);
    False on 'mishear' or any other answer. Any exception from the SDK is
    swallowed and treated as 'real' so a transient API failure doesn't silently
    drop a candidate the user might want.
    """

    user_prompt = (
        f"Raw transcript: {raw or '(empty)'}\n"
        f"Refined output: {refined or '(empty)'}\n"
        f"Candidate term: {candidate}\n\n"
        "Real or mishear?"
    )
    token_key = (
        "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _VALIDATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            **{token_key: 8},
        )
        answer = str(response.choices[0].message.content or "").strip().lower()
    except Exception as exc:
        LOGGER.warning("LLM validation failed for %r: %s; keeping term", candidate, exc)
        return True
    return answer.startswith("real")


def validate_candidates(
    candidates: list[tuple[str, int]],
    *,
    db_path: Path,
    days: int,
    client,
    model: str,
) -> list[tuple[str, int]]:
    """Filter ``candidates`` by querying the LLM with one trace row per term."""

    kept: list[tuple[str, int]] = []
    for term, count in candidates:
        sample = find_sample_for_term(db_path, term, days)
        if sample is None:
            kept.append((term, count))
            continue
        raw, refined = sample
        if validate_candidate(client, model, term, raw, refined):
            kept.append((term, count))
        else:
            LOGGER.info("LLM rejected candidate %r as mishear", term)
    return kept


def _build_openai_client():
    """Construct an OpenAI client from env vars; return None if unavailable."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI(api_key=api_key)


def run(
    db_path: Path,
    vocab_path: Path,
    stopwords_dir: Path,
    days: int,
    min_count: int,
    top_k: int,
    dry_run: bool,
    llm_validate: bool = False,
    llm_client: object | None = None,
    llm_model: str = "gpt-5.4-mini",
) -> None:
    existing = load_vocab(vocab_path)
    rejected = load_rejected(vocab_path)
    candidates = extract_candidates(
        db_path=db_path,
        days=days,
        min_count=min_count,
        user_terms=set(existing),
        stopwords=load_stopwords(stopwords_dir),
        rejected_terms=set(rejected),
    )
    top_candidates = candidates[:top_k]

    if llm_validate:
        client = llm_client or _build_openai_client()
        if client is None:
            print(
                "llm-validate requested but no OpenAI client available;"
                " skipping validation",
            )
        else:
            top_candidates = validate_candidates(
                top_candidates,
                db_path=db_path,
                days=days,
                client=client,
                model=llm_model,
            )

    top = [t for t, _c in top_candidates]
    print(f"sessions scanned (last {days}d), candidates kept: {len(top)}")
    for term, count in top_candidates:
        print(f"  {count:4d}  {term}")

    if dry_run:
        print("dry-run: not writing vocab.yaml")
        return
    save_auto_terms(vocab_path, top)
    print(f"updated {vocab_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract auto-hotwords from trace.db")
    home_dir = Path.home() / ".typeless-local"
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--db", type=Path, default=home_dir / "trace.db")
    parser.add_argument("--vocab", type=Path, default=home_dir / "vocab.yaml")
    parser.add_argument("--stopwords-dir", type=Path, default=repo_root / "assets")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--min-count", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reject",
        type=str,
        default=None,
        help=(
            "Move TERM out of auto: and into rejected: in vocab.yaml,"
            " then exit without re-running extraction."
        ),
    )
    parser.add_argument(
        "--llm-validate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Use gpt-5.4-mini to verify each candidate is a real term, not"
            " an ASR mishear. Requires OPENAI_API_KEY. Defaults on."
        ),
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="gpt-5.4-mini",
        help="Model used by --llm-validate.",
    )
    args = parser.parse_args(argv)

    if args.reject:
        reject_term(args.vocab, args.reject)
        print(f"rejected {args.reject!r}; rewrote {args.vocab}")
        return 0

    if not args.db.exists():
        print(f"trace db not found: {args.db}", file=sys.stderr)
        return 2

    run(
        db_path=args.db,
        vocab_path=args.vocab,
        stopwords_dir=args.stopwords_dir,
        days=args.days,
        min_count=args.min_count,
        top_k=args.top_k,
        dry_run=args.dry_run,
        llm_validate=args.llm_validate,
        llm_model=args.llm_model,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
