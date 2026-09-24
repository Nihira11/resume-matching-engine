# Validation against real job postings

First end-to-end run of the whole pipeline on real data: one real resume
against 13 real Sydney job postings, collected 23 September 2026 across
data analyst, data scientist, AI/ML, business analyst and quant roles,
pasted in full from the original postings (LinkedIn, Seek and employer
career pages).

The postings themselves are not committed — they're employer copy, and
`data/jds/` is gitignored. The Adzuna API is used to *find* postings, not
to load them: it truncates every description at 500 characters, which is
mostly company blurb, and its listing pages return 403 to scripted
requests.

## Why this run mattered

Every component had passing unit tests, and the pipeline ran end to end
without erroring. It also returned `likely_reject` for all 13 postings,
including an explicitly graduate-level AI role that the resume fits well.
Five separate bugs were behind that, and **none of them was visible to the
77 unit tests** — each one only appears when a real PDF resume meets a
real posting.

| # | Bug | Why the tests missed it |
|---|---|---|
| 1 | Title scored 0 when the resume has no job-title line | Every test resume had titles. Student resumes don't. |
| 2 | BM25 query built from the rarest words in the posting | Test JDs were three words long, with no benefits or EEO sections |
| 3 | ESCO has no entry for most modern tools | Test taxonomy was hand-written: Python, SQL, Spark, Airflow, Tableau |
| 4 | Generic ESCO aliases matched ordinary prose | Same — no real 14k-term taxonomy in the tests |
| 5 | Resume embedded as a single chunk | Test chunks were synthetic vectors, never real PDF text |

Details of 3 and 4 are in `PARSING-AND-EXTRACTION.md`; 1, 2 and 5 are in
`MATCHING-ENGINE.md`. All five are covered by regression tests now.

## Before and after

Same resume, same 13 postings, same weights — only the five fixes differ.

| Rank | Posting | Before | After |
|---|---|---|---|
| 1 | Data Analyst — Iress | 15.8 | **40.7** |
| 2 | Applied AI Engineer — Mistral | 27.9 | 34.1 |
| 3 | Graduate Analyst — GloBird Energy | 18.5 | 30.8 |
| 4 | Data Scientist, AI & Analytics — Westpac | 18.7 | 30.3 |
| 5 | Options Quant Support Analyst — CMC Markets | 16.1 | 29.4 |
| 6 | Applied AI Engineer, Student or Graduate — Deloitte | 18.9 | 28.4 |
| 7 | ML Research Intern — IMC Trading | 20.6 | 28.1 |
| 8 | Associate Data Scientist — Culture Amp | 16.3 | 25.4 |
| 9 | Intern, Engineering/AI — FOBOH | 16.3 | 24.2 |
| 10 | Business Analyst — Wotton Kearney | 13.1 | 19.8 |
| 11 | Business Analyst — PropertyMe | 1.4 | 19.1 |
| 12 | AI Business Analyst — RBA | 4.8 | 17.5 |
| 13 | Business Analyst — Mirvac | 8.9 | 15.9 |

Per component, and what changed:

| Component | Before | After |
|---|---|---|
| skill_overlap | 0.0–60.0, built from noisy ESCO matches | 0.0–44.4, built from tool-level matches |
| keyword_bm25 | 3.5–9.8 (query was employer boilerplate) | 6.5–23.7 |
| title_seniority | 0.0 on all 13 | 50.0 (neutral) + a gap-analysis suggestion |
| semantic | 0.0 on 7 of 13; only the top of the resume embedded | 11.6–43.2 |

**The ordering is the result worth reading, not the absolute numbers.**
Data and analytics roles now sort above AI engineering roles, which sort
above business-analyst roles wanting 5+ years of BA-specific experience.
That matches an honest reading of the resume. Before the fixes the top
score was an AI engineering role at a frontier-model company, which it
reached on a 60% skill overlap drawn from four matched ESCO terms.

A useful sanity check, since one resume can't show discrimination on its
own: scored against the same postings, two unrelated Kaggle resumes (an HR
assistant and an accountant) land at 0.0–2.7 and 1.0–8.2 on the keyword
component where this resume lands at 6.5–23.7.

## What this run did not fix

**Every posting is still `likely_reject`** (the thresholds are 70 to pass,
45 for borderline). The thresholds and the component weights were both set
by reasoning before any real data existed, and nothing here has calibrated
them. A resume matching 8 of 18 required skills on a well-fitting posting
scores 44.4 on skill overlap; whether that should read as "likely reject"
is exactly the open question. This run produced the first real
distribution to calibrate against — 13 postings is enough to see ordering,
not enough to set a threshold.

Two components still carry no information across postings:

- **title_seniority** is 50.0 everywhere, because this resume has no title
  line at all. It will vary as soon as a resume with job titles is scored.
- **experience** is 50.0 on the 4 postings that state a minimum and is
  dropped on the other 9. The resume never states a total, which is itself
  the gap-analysis suggestion being raised.

Both are correct behaviour for this input, but they mean this run only
really exercised three of the five components.

## Reproducing

```bash
python -m scripts.add_jd data/jds/*.txt            # load postings
python -m src.ingestion.pipeline path/to/resume.pdf
python -m scripts.verify_matching --resume-id 5 --limit 13 --refresh-embeddings
python -m src.matching.match_pipeline --resume-id 5 --jd-id 1   # one pair, full breakdown
```

After any change to the taxonomy or the extractors, re-run extraction over
what's already stored — entity rows keep whatever the extractor produced
at ingestion time:

```bash
python -m scripts.load_tech_skills
python -m scripts.reextract_entities
```

The BM25 corpus statistics depend on the tokenizer, so changing it means
rebuilding them (~30 minutes over the 2,484 staged Kaggle resumes):

```bash
python -m scripts.build_bm25_corpus
```

## Next

Done, on 24 September 2026 — see `CALIBRATION.md`. The evaluation set grew
to 40 postings with negative controls, the thresholds were derived from
the data (70/45 → 37/30), the semantic bounds were measured rather than
guessed, and a resume with job titles was scored, which exercised the
title component and exposed the circularity in judging it.
