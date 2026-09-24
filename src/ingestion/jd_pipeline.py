"""
Stores a job description (plain text – from Adzuna or manual paste) using
the same entity extraction pipeline as resumes. No file parsing and no ATS
parsability check here: parsability is a resume-formatting concern only

NOTE: `is_required` is defaulted to TRUE for every extracted entity. Real
required-vs-nice-to-have detection (e.g. proximity to "preferred" / "bonus"
/ "nice to have" language) needs its own logic and is left for later,
alongside the weighted matching engine.

Usage:
    from src.ingestion.jd_pipeline import run
    run(jd_text, title="Data Analyst", company="Acme", source="adzuna", source_url="...")
"""
from __future__ import annotations

from src.nlp.extract_entities import extract_all
from psycopg2.extras import execute_values

from src.utils.db import get_connection


def build_entity_rows(jd_id: int, entities) -> list[tuple]:
    """jd_entities rows for one JD, shared with scripts/reextract_entities.py"""
    rows = []
    for skill in entities.skills:
        rows.append((jd_id, "skill", skill.matched_text, skill.skill_id, True))
    for t in entities.titles:
        rows.append((jd_id, "title", t, None, True))
    for edu in entities.education:
        rows.append((jd_id, "education_requirement", edu, None, True))
    for years in entities.years_experience:
        rows.append((jd_id, "min_years_experience", str(years), None, True))
    return rows


def run(
    jd_text: str,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    source: str = "manual_paste",
    source_url: str | None = None,
    session_token: str | None = None,
) -> int:
    cleaned = jd_text.strip()
    entities = extract_all(cleaned)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO job_descriptions (source, source_url, title, company, location, raw_text, cleaned_text, session_token)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING jd_id
        """,
        (source, source_url, title, company, location, jd_text, cleaned, session_token),
    )
    jd_id = cur.fetchone()[0]

    entity_rows = build_entity_rows(jd_id, entities)

    if entity_rows:
        # execute_values sends one statement; executemany sends one round
        # trip per row, which against a hosted database meant ~17s to store
        # the 30-odd entities extracted from a single posting
        execute_values(
            cur,
            "INSERT INTO jd_entities (jd_id, entity_type, entity_value, skill_id, is_required) VALUES %s",
            entity_rows,
        )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Stored jd_id={jd_id}, {len(entity_rows)} entities extracted")
    return jd_id
