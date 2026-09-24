"""
Resume ingestion pipeline

file -> extracted text -> ATS parsability check -> entity extraction
-> stored in Postgres (resumes + resume_entities)

Usage:
    python -m src.ingestion.pipeline path/to/resume.pdf
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from src.ingestion.ats_parsability import check_parsability
from src.ingestion.extract_text import clean_text, extract_text
from src.ingestion.preview import render_first_page
from src.nlp.extract_entities import extract_all
from psycopg2.extras import execute_values

import psycopg2

from src.utils.db import get_connection


def build_entity_rows(resume_id: int, entities) -> list[tuple]:
    """resume_entities rows for one resume, shared with scripts/reextract_entities.py"""
    rows = []
    for skill in entities.skills:
        rows.append((resume_id, "skill", skill.matched_text, skill.skill_id, None))
    for title in entities.titles:
        rows.append((resume_id, "title", title, None, None))
    for edu in entities.education:
        rows.append((resume_id, "education", edu, None, None))
    for years in entities.years_experience:
        rows.append((resume_id, "years_experience", str(years), None, None))
    return rows


def run(file_path: str, session_token: str | None = None) -> int:
    if not os.path.exists(file_path):
        sys.exit(f"File not found: {file_path}")

    raw_text = extract_text(file_path)
    if not raw_text.strip():
        sys.exit(
            f"No text extracted from {file_path} — check it isn't a scanned "
            "image PDF (those need OCR, which is out of scope for Phase 1)."
        )

    cleaned = clean_text(raw_text)
    parsability = check_parsability(file_path)
    preview = render_first_page(file_path)
    entities = extract_all(cleaned)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO resumes (
            file_name, raw_text, cleaned_text,
            has_tables, has_multi_column, has_images, has_headers_footers,
            parsability_score, parsability_flags, session_token, preview_png
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING resume_id
        """,
        (
            os.path.basename(file_path),
            raw_text,
            cleaned,
            parsability.has_tables,
            parsability.has_multi_column,
            parsability.has_images,
            parsability.has_headers_footers,
            parsability.score,
            json.dumps(parsability.flags),
            session_token,
            psycopg2.Binary(preview) if preview else None,
        ),
    )
    resume_id = cur.fetchone()[0]

    entity_rows = build_entity_rows(resume_id, entities)

    if entity_rows:
        # execute_values sends one statement; executemany sends one round
        # trip per row, which against a hosted database meant ~17s to store
        # the 30-odd entities extracted from a single posting
        execute_values(
            cur,
            "INSERT INTO resume_entities (resume_id, entity_type, entity_value, skill_id, confidence) VALUES %s",
            entity_rows,
        )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Stored resume_id={resume_id}")
    print(f"  Parsability score: {parsability.score}/100 — flags: {parsability.flags or 'none'}")
    print(f"  Skills matched: {len(entities.skills)}")
    print(f"  Titles found: {entities.titles}")
    print(f"  Education found: {entities.education}")
    print(f"  Years experience candidates: {entities.years_experience}")

    return resume_id


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 ingestion on a single resume file.")
    parser.add_argument("file_path", help="Path to a .pdf or .docx resume")
    args = parser.parse_args()
    run(args.file_path)


if __name__ == "__main__":
    main()
