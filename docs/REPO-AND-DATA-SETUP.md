# Repo Scaffold, Database & Dataset Sourcing

Status: complete.

## Repo structure

Created the base project layout: `app/` (Reflex UI), `src/` (ingestion, nlp, matching, utils modules), `db/` (schema files), `data/` (raw, processed, taxonomy – gitignored), `docs/`, `notebooks/`, `tests/`.

Reflex skeleton set up with `rxconfig.py`, `state.py`, and a placeholder `resume_matcher.py` entrypoint – confirms `reflex run` works before any real pages exist.

`.gitignore` covers: `.env`, virtual environments, Python cache files, Reflex build artifacts, `data/raw/*`, `data/processed/*`, `data/taxonomy/*` (large reference files, reproducible via scripts rather than committed).

`requirements.txt` covers: Reflex, psycopg2 + pgvector + SQLAlchemy, pdfplumber + python-docx + PyMuPDF, spaCy + sentence-transformers + rank-bm25 + scikit-learn, pandas/numpy/requests/python-dotenv, the Anthropic
SDK, and pytest.

## Database

PostgreSQL hosted on Supabase (free tier, Sydney region, project name `resume-matching-engine`).

Direct connection host (`db.xxxx.supabase.co`) is IPv6-only and failed to resolve on the local network. Switched to the session/transaction pooler connection string instead (found under Connect → ORM tab in the Supabase dashboard):

```
postgresql://postgres.[project-ref]:[password]@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres
```
Database password contained `&`, which had to be URL-encoded as `%26` for the connection string to parse correctly.

Free-tier projects pause after ~7 days of inactivity – kept alive with a scheduled GitHub Action pinging the DB twice a week rather than manually restoring it each time.

Schema applied via:
```bash
psql "$DATABASE_URL" -f db/init_pgvector.sql
psql "$DATABASE_URL" -f db/schema.sql
```
Result: pgvector extension enabled, 6 tables created (`skills_taxonomy`, `resumes`, `resume_entities`, `job_descriptions`, `jd_entities`, `match_results`), 4 indexes created.

## Skills taxonomy – ESCO

Downloaded from the official source (https://esco.ec.europa.eu/en/use-esco/download): ESCO dataset v1.2.1 / Classification / en / csv. Requested via their download form (organisation type: Other; intended use: Integration into application/services), delivered by email link within minutes.

Attribution required by ESCO's terms of reuse, included in the README:
> This service uses the ESCO classification of the European Commission.

From the full 17-file package, three CSVs kept:
- `skills_en.csv` → `data/taxonomy/esco_skills.csv`
- `skillGroups_en.csv` → `data/taxonomy/esco_skill_groups.csv`
- `occupationSkillRelations_en.csv` → `data/taxonomy/esco_occupation_skill_relations.csv`

Loaded into the `skills_taxonomy` table via `src/nlp/load_taxonomy.py`, which parses `preferredLabel`, splits `altLabels` (newline-separated) into an alias array, and maps `skillType` to a simplified `technical`/`soft` category.

Result: 13,939 unique skills loaded (21 duplicate `preferredLabel` values skipped via `ON CONFLICT DO NOTHING`).

## Bulk resume/JD data – Kaggle

Downloaded manually from Kaggle (Resume Dataset, Resume Entities for NER, Job Description Dataset) and staged under `data/raw/`:
```
data/raw/
├── kaggle_resumes/              PDF resumes organized by category folder
├── kaggle_resume_entities/      resume_entities.json (labelled NER ground truth)
└── kaggle_jds/                  job_dataset.csv
```
Gitignored – contains real named individuals' resume content, kept local only, for pipeline testing rather than the live demo.

`resume_entities.json` turned out to be JSONL (one JSON object per line) despite the `.json` extension – noted here since it trips up JSON linters/ editors expecting a single document, and matters for anything that reads the file later.

Full detail on all three datasets in `docs/DATASETS.md`.

## Live job postings – Adzuna

Registered at https://developer.adzuna.com. Signup details: organisation type Other, average monthly visitors 0-5000, primary market Australia/NZ, primary industry Technology. `app_id` and `app_key` issued immediately, stored in `.env` as `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`.

Tested against the AU search endpoint and confirmed working – returned real, current Sydney data analyst listings with title, company, description, salary, and redirect URL fields.

## NLP dependency

Installed spaCy's large English model:
```bash
python -m spacy download en_core_web_lg
```

## Version control

Repo created on GitHub, cloned locally, initial commit pushed with the full scaffold.

## Outcome

Database live and schema applied. All three data sources connected and verified working: ESCO taxonomy loaded, Kaggle bulk data staged, Adzuna API tested against real listings. Environment and dependencies fully installed. 
Ready to begin parsing & extraction.
