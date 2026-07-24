"""
One-time build of the BM25 background corpus statistics.

    python -m scripts.build_bm25_corpus
    python -m scripts.build_bm25_corpus --limit 400        # quick first pass

Walks data/raw/kaggle_resumes/, extracts text with the ingestion extractor,
and writes document frequencies + average document length to
data/processed/bm25_corpus_stats.json.

Why the resume corpus and not the JD CSV
----------------------------------------
BM25 scores a document against a query. Here the document is a resume, so
IDF should describe how rare a term is among resumes. The Kaggle JD CSV is
far cheaper to process (no PDF extraction) and would work as a rough
stand-in, but it answers a subtly different question -- "how rare is this
term in job ads" -- and job ads and resumes have noticeably different term
distributions. Use the JD CSV as a fallback if the PDF pass is painful,
and note the substitution if you do.

Only document frequencies and average length are stored, never the corpus
text. The Kaggle resumes contain real named individuals and stay local and
gitignored; the stats file is aggregate counts and is safe to commit.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.ingestion.extract_text import clean_text, extract_text
from src.matching.bm25_scorer import tokenize
from src.matching.config import BM25_CORPUS_STATS_PATH

DEFAULT_CORPUS_DIR = Path("data/raw/kaggle_resumes")


def build(corpus_dir: Path, output_path: Path, limit: int | None = None) -> dict:
    files = sorted(
        p for p in corpus_dir.rglob("*")
        if p.suffix.lower() in (".pdf", ".docx", ".txt")
    )
    if limit:
        files = files[:limit]
    if not files:
        raise SystemExit(f"no resume files found under {corpus_dir}")

    df: Counter[str] = Counter()
    total_length = 0
    processed = 0
    failed = 0

    for index, path in enumerate(files, start=1):
        try:
            text = clean_text(extract_text(str(path)))
        except Exception as exc:  # noqa: BLE001 - corpus build is best-effort
            failed += 1
            print(f"  skipped {path.name}: {type(exc).__name__}: {exc}")
            continue

        tokens = tokenize(text)
        if not tokens:
            failed += 1
            continue

        # Document frequency counts DOCUMENTS containing the term, not
        # total occurrences -- hence the set().
        df.update(set(tokens))
        total_length += len(tokens)
        processed += 1

        if index % 100 == 0:
            print(f"  {index}/{len(files)} files, {processed} usable")

    if processed == 0:
        raise SystemExit("no documents could be processed")

    stats = {
        "n_docs": processed,
        "avgdl": total_length / processed,
        "df": dict(df),
        "source_dir": str(corpus_dir),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(stats))
    print(
        f"\nwrote {output_path}: {processed} documents, "
        f"{len(df)} vocabulary terms, avgdl {stats['avgdl']:.1f}, "
        f"{failed} skipped"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--output", type=Path, default=Path(BM25_CORPUS_STATS_PATH))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    build(args.corpus_dir, args.output, args.limit)


if __name__ == "__main__":
    main()