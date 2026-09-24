"""
Re-run entity extraction for every stored resume and JD.

    python -m scripts.reextract_entities
    python -m scripts.reextract_entities --jds-only

Needed after anything that changes what extraction produces -- the
taxonomy (scripts/load_tech_skills.py), the skill matcher, or the title /
education / years patterns. Stored entities otherwise keep whatever the
extractor produced at ingestion time.

Reads the stored cleaned_text, so no files are needed. Replaces each
document's entity rows in one transaction per document. JD is_required
flags are reset to TRUE, same as fresh ingestion; the matching pipeline
re-derives them from section headings before scoring.
"""
from __future__ import annotations

import argparse

from src.ingestion import jd_pipeline, pipeline
from src.nlp.extract_entities import extract_all
from psycopg2.extras import execute_values

from src.utils.db import get_connection


def reextract(table: str, id_column: str, entity_table: str, build_rows, columns: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT {id_column}, COALESCE(cleaned_text, raw_text) FROM {table} ORDER BY {id_column}")
    docs = cur.fetchall()

    for doc_id, text in docs:
        cur.execute(f"SELECT count(*) FROM {entity_table} WHERE {id_column} = %s", (doc_id,))
        before = cur.fetchone()[0]
        rows = build_rows(doc_id, extract_all(text or ""))
        cur.execute(f"DELETE FROM {entity_table} WHERE {id_column} = %s", (doc_id,))
        if rows:
            execute_values(cur, f"INSERT INTO {entity_table} ({columns}) VALUES %s", rows)
        conn.commit()
        print(f"  {table} {doc_id}: {before} -> {len(rows)} entities")

    cur.close()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run entity extraction on stored documents.")
    parser.add_argument("--jds-only", action="store_true")
    parser.add_argument("--resumes-only", action="store_true")
    args = parser.parse_args()

    if not args.jds_only:
        reextract(
            "resumes", "resume_id", "resume_entities", pipeline.build_entity_rows,
            "resume_id, entity_type, entity_value, skill_id, confidence",
        )
    if not args.resumes_only:
        reextract(
            "job_descriptions", "jd_id", "jd_entities", jd_pipeline.build_entity_rows,
            "jd_id, entity_type, entity_value, skill_id, is_required",
        )


if __name__ == "__main__":
    main()
