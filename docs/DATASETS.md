# Data Sources

This project uses three kinds of data, sourced differently on purpose:

1. **Skills taxonomy** – reference dictionary of known skills (structured, downloaded once)
2. **Bulk resumes/JDs** – for training/testing the NLP pipeline at scale (Kaggle)
3. **Live job postings** – for the actual demo of the app (Adzuna API, real & current)

Kaggle data is for bulk pipeline testing only, never the live demo

---

## 1. Skills taxonomy – ESCO (official download)

Source: https://esco.ec.europa.eu/en/use-esco/download – official EU skills classification

Selections used: **ESCO dataset v1.2.1 / Classification / csv / en**

Steps:
1. Go to the download page, select Version / Content / File type / Language as above
2. Click "Add to your package"
3. Complete the request form (email, organisation type: Other, intended use: Integration into application/services)
4. Accept the "Specific Conditions applying for the ESCO Service" checkboxes
5. Submit – a download link arrives by email within minutes
6. Unzip the package

Attribution required by ESCO's terms of reuse:
> This service uses the ESCO classification of the European Commission

From the full package (17 CSVs), only these three are used:
- `skills_en.csv` → `data/taxonomy/esco_skills.csv`
- `skillGroups_en.csv` → `data/taxonomy/esco_skill_groups.csv`
- `occupationSkillRelations_en.csv` → `data/taxonomy/esco_occupation_skill_relations.csv` (for title/seniority matching, later)

Column headers in the official export: `conceptType, conceptUri, skillType, reuseLevel, preferredLabel, altLabels, hiddenLabels, status, modifiedDate, scopeNote, definition, inScheme, description`

These CSVs are gitignored (`data/taxonomy/*`) – large reference files, easily re-downloaded, not committed to git history

Load into Postgres:
```bash
python src/nlp/load_taxonomy.py          # full load
python src/nlp/load_taxonomy.py 500      # quick test run, first 500 rows only
```
Loader reads `preferredLabel`, `altLabels` (newline-separated → alias array), and `skillType` (mapped to `technical`/`soft` category), inserting into the `skills_taxonomy` table with `ON CONFLICT DO NOTHING` for dedup

Result: 13,939 unique skills loaded

---

## 2. Bulk resume/JD data – Kaggle (pipeline testing only)

Datasets used:
- **Resume Dataset**: kaggle.com/datasets/snehaanbhawal/resume-dataset – PDF resumes organized by category folder (ACCOUNTANT, ADVOCATE, ENGINEERING, etc.)
- **Resume Entities for NER**: kaggle.com/datasets/dataturks/resume-entities-for-ner – JSON with labelled entities (Name, Skills, Degree, Companies worked at, etc.) for validating spaCy NER output
- **Job Description Dataset**: kaggle.com/datasets/ravindrasinghrana/job-description-dataset

Download manually via the Kaggle website Download button, or via CLI:
```bash
pip install kaggle
# kaggle.json API token from kaggle.com/settings → ~/.kaggle/kaggle.json
kaggle datasets download -d snehaanbhawal/resume-dataset -p data/raw/kaggle_resumes --unzip
kaggle datasets download -d ravindrasinghrana/job-description-dataset -p data/raw/kaggle_jds --unzip
```

Folder layout:
data/raw/
├── kaggle_resumes/              (PDFs by category, from the "archive" download)
├── kaggle_resume_entities/      (resume_entities.json)
└── kaggle_jds/                  (job_dataset.csv)

All gitignored (`data/raw/*`) – contains real named individuals' resume content, never committed or shown in the live demo/screenshots

---

## 3. Live job postings – Adzuna API

Source: https://developer.adzuna.com – free signup, `app_id`/`app_key` issued immediately

Signup details used: Organisation type – Other; Average Monthly Visitors – 0-5000; Primary Market – Australia/NZ; Primary Industry – Technology

Keys stored in `.env`:
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...

Endpoint for AU jobs:
GET https://api.adzuna.com/v1/api/jobs/au/search/1
?app_id={id}&app_key={key}&results_per_page=20&what=data%20analyst&where=sydney

Returns JSON with `title`, `company`, `description`, `redirect_url` (the real posting link), salary fields where available

Tested and confirmed working against live Sydney data analyst listings

**Why not scrape LinkedIn/Seek directly:** both prohibit scraping in their ToS and actively block it. Adzuna aggregates postings from multiple boards legitimately through its API

A "paste raw JD text" input should also exist in the UI as a fallback, for testing against a specific posting not in Adzuna's index

---

## Database

Postgres hosted on Supabase (free tier, Sydney region, pgvector enabled)

Direct connection (`db.xxxx.supabase.co`) is IPv6-only and fails on most home networks. Use the session/transaction pooler connection string instead (Connect → ORM tab in the Supabase dashboard), format:
postgresql://postgres.[project-ref]:[password]@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres

Passwords containing special characters (`&`, `@`, `%`, etc.) must be URL-encoded (`&` → `%26`).

Setup:
```bash
psql "$DATABASE_URL" -f db/init_pgvector.sql
psql "$DATABASE_URL" -f db/schema.sql
```

---

## Data flow summary

ESCO (official download)  ─────► skills_taxonomy table   (loaded, 13,939 rows)
Kaggle bulk data ──────────────► pipeline testing/validation only, not shown in UI
Adzuna API ─────────────────────► job_descriptions table   (live, powers the actual demo)
Own resume + real postings ────► validation case study for README