"""Mine the trace DB for likely-hotword candidates and write them to vocab.yaml."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

# Allow running as both `python scripts/extract_hotwords.py` and `python -m scripts.extract_hotwords`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typeless_local.vocab import load_vocab, save_auto_terms  # noqa: E402

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
    counter: Counter[str] = Counter()
    for raw, refined in rows:
        raw_tokens = set(tokenize(raw or ""))
        ref_tokens = tokenize(refined or "")
        added = [t for t in ref_tokens if t not in raw_tokens]
        for term in added:
            if len(term) < 2:
                continue
            if term.lower() in user_lower:
                continue
            if term.lower() in stops_lower:
                continue
            counter[term] += 1

    return [(t, c) for t, c in counter.most_common() if c >= min_count]


def run(
    db_path: Path,
    vocab_path: Path,
    stopwords_dir: Path,
    days: int,
    min_count: int,
    top_k: int,
    dry_run: bool,
) -> None:
    existing = load_vocab(vocab_path)
    candidates = extract_candidates(
        db_path=db_path,
        days=days,
        min_count=min_count,
        user_terms=set(existing),
        stopwords=load_stopwords(stopwords_dir),
    )
    top = [t for t, _c in candidates[:top_k]]

    print(f"sessions scanned (last {days}d), candidates kept: {len(top)}")
    for term, count in candidates[:top_k]:
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
    args = parser.parse_args(argv)

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
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
