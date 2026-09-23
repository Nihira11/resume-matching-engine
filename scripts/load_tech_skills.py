"""
Load the curated tech skills (src/nlp/tech_skills.py) into skills_taxonomy.

    python -m scripts.load_tech_skills

Idempotent: re-running updates aliases and category for curated rows. A
name that already exists as an ESCO skill is skipped and reported rather
than overwritten -- ESCO rows are referenced by existing entity rows and
the ESCO loader owns them.

Stored entities keep the skill_id they were extracted with, so re-run
extraction afterwards for anything already in the database:

    python -m scripts.reextract_entities
"""
from __future__ import annotations

from src.nlp.skill_matcher import CURATED_SOURCE
from src.nlp.taxonomy_cache import clear_cache
from src.nlp.tech_skills import TECH_SKILLS
from src.utils.db import get_connection


def load() -> None:
    conn = get_connection()
    cur = conn.cursor()
    inserted = updated = 0
    skipped: list[str] = []

    for name, category, aliases in TECH_SKILLS:
        cur.execute(
            "SELECT skill_id, source FROM skills_taxonomy WHERE lower(skill_name) = lower(%s)",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO skills_taxonomy (skill_name, skill_category, source, aliases) "
                "VALUES (%s, %s, %s, %s)",
                (name, category, CURATED_SOURCE, aliases),
            )
            inserted += 1
        elif row[1] == CURATED_SOURCE:
            cur.execute(
                "UPDATE skills_taxonomy SET skill_category = %s, aliases = %s WHERE skill_id = %s",
                (category, aliases, row[0]),
            )
            updated += 1
        else:
            skipped.append(f"{name} (already a {row[1]} skill)")

    conn.commit()
    cur.close()
    conn.close()

    clear_cache()  # the matcher's local taxonomy copy is now out of date
    print(f"curated skills: {inserted} inserted, {updated} updated, {len(skipped)} skipped")
    for item in skipped:
        print(f"  skipped {item}")


if __name__ == "__main__":
    load()
