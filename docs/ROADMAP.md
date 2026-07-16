# Resume–Job Matching System – Roadmap

An NLP-powered resume-to-job-description matcher built to mirror how real ATS (Applicant Tracking System) engines actually screen resumes, validated against real job postings rather than synthetic data.

**Stack:** PostgreSQL + pgvector · spaCy + sentence-transformers · BM25 · Reflex (UI) · Anthropic API (LLM rewrite suggestions) · Adzuna API (live jobs)

**Core scoring model:** weighted blend of hard skill/keyword overlap (highest weight, mirrors real ATS behavior) + title/seniority match + experience match + semantic similarity (secondary signal), plus a standalone ATS parsability check that flags formatting issues (tables, columns, images, headers/footers) independent of resume content.

---

## Repo scaffold, database, dataset sourcing

- Project structure (`app/`, `src/`, `db/`, `data/`, `docs/`)
- PostgreSQL (Supabase, pgvector enabled) provisioned and schema applied
- ESCO skills taxonomy downloaded and loaded (13,939 skills)
- Kaggle bulk resume/JD/NER data staged for pipeline testing
- Adzuna API connected and tested against live Sydney job postings
- Reflex skeleton, environment, dependencies installed

Full detail in `docs/REPO-AND-DATA-SETUP.md`.

## Parsing & extraction

- PDF/DOCX text extraction (`pdfplumber`, `python-docx`)
- ATS parsability scoring: detect tables, multi-column layout, images, headers/footers – flag formatting that causes real ATS engines to drop or scramble content, independent of what the resume says
- spaCy NER: extract skills, job titles, education, years of experience
- Skill matching against the ESCO taxonomy (including alias matching)
- Validated against the Kaggle labelled entity dataset – found and fixed three real extraction bugs, documented two known limitations
- Store structured extraction results in Postgres

Full detail in `docs/PARSING-AND-EXTRACTION.md`.

## Matching engine

- Hard skill/keyword overlap scoring (BM25), weighted highest – mirrors real ATS behavior
- Title/seniority match logic
- Years-of-experience match
- Semantic similarity via sentence-transformers embeddings, stored via pgvector – secondary signal, not primary
- Blended final score with a transparent breakdown (never a black-box number)
- Gap analysis: skills present in the JD but missing from the resume

## UI build (Reflex)

- Multi-page layout: upload resume + paste/fetch JD, score breakdown, matched/missing skills visual, ATS parsability warnings panel
- Live JD input via Adzuna search, or raw paste as fallback
- Score explainability: show which keywords/sections drove the score

## Validation against real postings

- Run the tool against real job postings applied to personally, not just Kaggle bulk data
- Sanity-check: does the tool's verdict match actual intuition about fit
- Calibrate scoring weights based on this validation
- Document results in `docs/validation-results.md` – the credibility piece for the README ("validated against N real postings," not "tested on synthetic data")

## Polish & deployment

- README, screenshots, architecture diagram
- GitHub Pages write-up of methodology
- Deploy the Reflex app

## Stretch: LLM resume rewrite suggestions

- Anthropic API call fed with resume text + JD text + the gap analysis already computed in the matching engine step
- Constrained prompt: rewrite specific bullets to include missing keywords truthfully, not free-form rewriting (avoids inventing experience that doesn't exist)

## Stretch: ATS keyword density checker

- Frequency count of JD keywords found in the resume vs. missing, displayed as a density percentage with a simple bar chart
- Reuses JD keyword extraction already built in the parsing step – cheap to add

## Stretch: multi-resume batch scoring + leaderboard

- Batch upload flow for multiple resumes against one JD (or vice versa)
- Loop each pair through the matching pipeline
- Sortable leaderboard UI page showing ranked results

---
