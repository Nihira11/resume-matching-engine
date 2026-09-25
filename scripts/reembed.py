"""
Re-chunk and re-embed every stored document.

    python -m scripts.reembed                # postings and resumes
    python -m scripts.reembed --jds-only
    python -m scripts.reembed --resumes-only

The companion to reextract_entities.py, and needed for the same reason:
chunks are written once at ingestion, so anything that changes what gets
embedded leaves the stored vectors describing text that is no longer what
the engine would produce. That covers the chunker (CHUNK_TARGET_CHARS,
chunk_text) and, for postings, strip_boilerplate -- a new boilerplate
marker removes a section from fresh ingests while the stored chunks keep
embedding it.

Reads cleaned_text, so no source files are needed. Slower than
re-extraction because every chunk goes through MiniLM: expect a couple of
minutes for ~60 postings on CPU, most of it model inference rather than
the database.
"""
from __future__ import annotations

import argparse
import time

from src.matching.embeddings import embed_and_store
from src.utils.db import connection


def reembed(kind: str) -> None:
    table = "resumes" if kind == "resume" else "job_descriptions"
    id_column = "resume_id" if kind == "resume" else "jd_id"
    chunk_table = "resume_chunks" if kind == "resume" else "jd_chunks"

    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {id_column}, COALESCE(cleaned_text, raw_text) FROM {table} "
            f"ORDER BY {id_column}"
        )
        docs = cur.fetchall()
        cur.execute(f"SELECT {id_column}, count(*) FROM {chunk_table} GROUP BY 1")
        before = dict(cur.fetchall())

    print(f"{table}: {len(docs)} documents")
    changed = 0
    start = time.time()
    for doc_id, text in docs:
        if not (text or "").strip():
            print(f"  {id_column} {doc_id}: no text, skipped")
            continue
        was = before.get(doc_id, 0)
        now = embed_and_store(kind, doc_id, text)
        # Chunks past the new end are removed by embed_and_store; a drop in
        # count is the normal outcome of a new boilerplate marker.
        flag = "" if now == was else f"  <- was {was}"
        if now != was:
            changed += 1
        print(f"  {id_column} {doc_id}: {now} chunks{flag}")

    print(f"{table}: {changed} of {len(docs)} documents changed chunk count "
          f"in {time.time() - start:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-chunk and re-embed stored documents.")
    parser.add_argument("--jds-only", action="store_true")
    parser.add_argument("--resumes-only", action="store_true")
    args = parser.parse_args()

    if not args.jds_only:
        reembed("resume")
    if not args.resumes_only:
        reembed("jd")


if __name__ == "__main__":
    main()
