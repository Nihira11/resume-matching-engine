"""
Loads the ESCO skills taxonomy (data/taxonomy/esco_skills.csv) into the skills_taxonomy table

Source: official ESCO download (https://esco.ec.europa.eu/en/use-esco/download), ESCO dataset v1.2.1 / Classification / csv / en 
This service uses the ESCO classification of the European Commission

Usage:
    python src/nlp/load_taxonomy.py

Requires DATABASE_URL in .env and db/schema.sql already applied
"""
import csv
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "taxonomy", "esco_skills.csv"
)

# ESCO's skillType values map roughly onto the simpler category field used here
SKILLTYPE_TO_CATEGORY = {
    "skill/competence": "technical",
    "knowledge": "technical",
    "language skill and knowledge": "soft",
    "transversal skill and competence": "soft",
    "attitudes and values": "soft",
}


def load(csv_path: str = CSV_PATH, limit: int | None = None) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL not set — copy .env.example to .env and fill it in.")

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    inserted = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if limit and inserted >= limit:
                break

            name = (row.get("preferredLabel") or "").strip()
            if not name:
                continue

            # altLabels is newline-separated in the official ESCO export
            aliases_raw = row.get("altLabels", "") or ""
            aliases = [a.strip() for a in aliases_raw.split("\n") if a.strip()]

            category = SKILLTYPE_TO_CATEGORY.get(
                (row.get("skillType") or "").strip(), "technical"
            )

            cur.execute(
                """
                INSERT INTO skills_taxonomy (skill_name, skill_category, source, aliases)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (skill_name) DO NOTHING
                """,
                (name, category, "ESCO", aliases),
            )
            inserted += 1

            if inserted % 2000 == 0:
                conn.commit()
                print(f"  ...{inserted} skills inserted")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done. Inserted (or skipped duplicates for) {inserted} skills.")


if __name__ == "__main__":
    # pass a limit for a quick test run, e.g.: python load_taxonomy.py 500
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    load(limit=limit)