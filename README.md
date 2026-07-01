# Resume–Job Matching System

An NLP-powered resume-to-job-description matcher that mirrors how real ATS (Applicant Tracking System) engines actually screen resumes not a toy keyword cloud demo.

**Core idea:** score = weighted blend of hard skill/keyword overlap (highest weight, mirrors real ATS behavior) + title/seniority match + experience match + semantic similarity (secondary signal) — plus an **ATS parsability check** that flags formatting issues (tables, columns, images, headers/footers) that cause real ATS engines to drop content entirely, independent of what the resume says.

Validated against real job postings (via the Adzuna API) and my own resume, not synthetic data. See `docs/VALIDATION.md` for results.

## Stack
- **DB:** PostgreSQL + pgvector
- **NLP:** spaCy (NER) + sentence-transformers (semantic embeddings) + BM25 (keyword)
- **UI:** Reflex (pure Python, compiles to React)
- **LLM features:** Anthropic API (tailored rewrite suggestions)
- **Job data:** Adzuna API (live postings) + Reed API

## Project structure
```
resume-job-matcher/
├── app/                  # Reflex UI
│   └── resume_matcher/
│       ├── pages/         # multi-page routes
│       ├── components/    # reusable UI components
│       ├── state.py        # app state
│       └── resume_matcher.py  # entrypoint
├── src/
│   ├── ingestion/          # PDF/DOCX parsing, ATS parsability checks
│   ├── nlp/                # NER, embeddings, taxonomy loading
│   ├── matching/            # scoring engine
│   └── utils/                # shared helpers
├── db/
│   ├── init_pgvector.sql
│   └── schema.sql
├── data/
│   ├── raw/                 # gitignored — Kaggle bulk data, real resumes
│   ├── processed/            # gitignored
│   └── taxonomy/              # ESCO/O*NET skills CSVs
├── notebooks/                 # exploration notebooks per phase
├── docs/                       # DATASETS.md, VALIDATION.md, ARCHITECTURE.md
├── tests/
└── requirements.txt
```

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg

cp .env.example .env   # fill in DATABASE_URL, ADZUNA_APP_ID/KEY, ANTHROPIC_API_KEY

# DB
psql $DATABASE_URL -f db/init_pgvector.sql
psql $DATABASE_URL -f db/schema.sql

# Run UI (from app/ directory)
cd app && reflex init && reflex run
```

See `docs/DATASETS.md` for exactly where each dataset comes from and how to fetch it
