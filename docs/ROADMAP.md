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
- Validated against the Kaggle labelled entity dataset, then against 13 real job postings – six extraction bugs found and fixed between them, including ESCO's gaps on modern tooling (covered by a curated 124-skill list) and generic-alias false positives
- Store structured extraction results in Postgres

Full detail in `docs/PARSING-AND-EXTRACTION.md`.

## Matching engine

- Hard skill/keyword overlap scoring (BM25), weighted highest – mirrors real ATS behavior
- Title/seniority match logic
- Years-of-experience match
- Semantic similarity via sentence-transformers embeddings, stored via pgvector – secondary signal, not primary
- Blended final score with a transparent breakdown (never a black-box number)
- Gap analysis: skills present in the JD but missing from the resume
- Run end-to-end against real postings – three engine bugs found and fixed that every unit test missed (title zeroed for resumes with no title line, BM25 querying employer boilerplate, resumes embedded as one truncated chunk)

Full detail in `docs/MATCHING-ENGINE.md`; the real-posting run is in `docs/validation-results.md`.

## UI build (Reflex)

- Upload resume or pick a parsed one; paste a posting or pick a stored one
- Score breakdown per component, with weights and contributions shown
- Matched/missing skills, gap analysis table, suggestions
- ATS parsability panel, kept separate from the match score
- Leaderboard: one resume against every stored posting, filling in as rows land
- Not wired: Adzuna search (its API truncates descriptions at 500 characters, too little to score against — postings are pasted instead)

Full detail in `docs/UI.md`.

## Validation against real postings

- Run the tool against real job postings, not just Kaggle bulk data — 40 postings, 27 pulled straight from company job boards, scored against 6 resumes
- Sanity-check against the candidate's own judgement — no posting labelled a good fit is rejected, none ruled out passes
- Calibrate verdict thresholds (70/45 → 37/30) and test 162 weightings; weights kept, for reasons recorded
- Measure the semantic rescale bounds from the observed distribution ([0.25, 0.75] → [0.15, 0.45])
- Known weakness, measured and documented: domain discrimination is weak (structural AUC 0.68)

Full detail in `docs/CALIBRATION.md`.

## Polish & deployment

- README rewritten around measured results, with a Mermaid architecture diagram
- Dependencies pinned to what is actually imported; BM25 corpus statistics now ship with the repo
- Data paths resolved from the repo root — the dashboard had been silently scoring without the keyword component
- Deployment assessed and documented (`docs/DEPLOYMENT.md`): a Dockerfile exists, and the blocker is that the app has no authentication while holding real resumes
- Outstanding: screenshots, and the access-model decision before any public deploy

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
