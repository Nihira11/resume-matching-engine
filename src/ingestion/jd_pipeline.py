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
from src.utils.db import get_connection


def run(
    jd_text: str,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    source: str = "manual_paste",
    source_url: str | None = None,
) -> int:
    cleaned = jd_text.strip()
    entities = extract_all(cleaned)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO job_descriptions (source, source_url, title, company, location, raw_text, cleaned_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING jd_id
        """,
        (source, source_url, title, company, location, jd_text, cleaned),
    )
    jd_id = cur.fetchone()[0]

    entity_rows = []
    for skill in entities.skills:
        entity_rows.append((jd_id, "skill", skill.matched_text, skill.skill_id, True))
    for t in entities.titles:
        entity_rows.append((jd_id, "title", t, None, True))
    for edu in entities.education:
        entity_rows.append((jd_id, "education_requirement", edu, None, True))
    for years in entities.years_experience:
        entity_rows.append((jd_id, "min_years_experience", str(years), None, True))

    if entity_rows:
        cur.executemany(
            """
            INSERT INTO jd_entities (jd_id, entity_type, entity_value, skill_id, is_required)
            VALUES (%s, %s, %s, %s, %s)
            """,
            entity_rows,
        )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Stored jd_id={jd_id}, {len(entity_rows)} entities extracted")
    return jd_id
