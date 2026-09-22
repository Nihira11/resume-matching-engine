"""
Load job descriptions from plain text files.

    python -m scripts.add_jd data/jds/*.txt
    python -m scripts.add_jd data/jds/analyst.txt --company "Acme" --source adzuna

Convention: the FIRST non-empty line of each file is used as the job
title, and the full text (including that line) is stored as the body.
Keeping the title in the body matters -- the title line usually repeats
the core skill terms, and dropping it would lose them from extraction.

Override with --title when loading a single file.

To capture a posting: copy the whole thing from the browser, paste into a
text file, put the job title on line 1. Keep the requirements and
nice-to-have headings intact -- the required-vs-preferred logic reads
those headings, and stripping them makes every wishlist item look
mandatory.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.ingestion.jd_pipeline import run as ingest_jd
from src.utils.db import get_connection


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return "Untitled"


def summarise(jd_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT entity_type, count(*) FROM jd_entities WHERE jd_id = %s "
        "GROUP BY entity_type ORDER BY entity_type",
        (jd_id,),
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT count(DISTINCT skill_id) FROM jd_entities "
        "WHERE jd_id = %s AND entity_type = 'skill' AND skill_id IS NOT NULL",
        (jd_id,),
    )
    unique_skills = cur.fetchone()[0]
    cur.close()
    conn.close()

    detail = ", ".join(f"{kind}={count}" for kind, count in rows) or "none"
    print(f"    entities: {detail}  ({unique_skills} distinct linked skills)")
    if not unique_skills:
        print("    WARNING: no skills linked to the taxonomy — skill overlap "
              "will have nothing to compare for this posting")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load JDs from text files.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--title", help="override; only sensible for one file")
    parser.add_argument("--company")
    parser.add_argument("--location")
    parser.add_argument("--source", default="manual_paste")
    parser.add_argument("--url")
    args = parser.parse_args()

    if args.title and len(args.files) > 1:
        parser.error("--title with multiple files would label them all the same")

    for path in args.files:
        if not path.exists():
            print(f"  skipped {path}: not found")
            continue
        text = path.read_text(encoding="utf-8").strip()
        if len(text) < 200:
            print(f"  skipped {path}: only {len(text)} chars — looks truncated")
            continue

        title = args.title or first_line(text)
        print(f"\n{path.name}  ->  {title}")
        jd_id = ingest_jd(
            text,
            title=title,
            company=args.company,
            location=args.location,
            source=args.source,
            source_url=args.url,
        )
        summarise(jd_id)


if __name__ == "__main__":
    main()