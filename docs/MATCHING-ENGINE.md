# Matching Engine

Status: implemented, not yet calibrated. Calibration comes later, against
real job postings.

## Shape

One resume + one JD in, one `match_results` row out:

```bash
python -m src.matching.match_pipeline --resume-id 1 --jd-id 3 --refresh-embeddings
```

Five scoring components, blended:

| Component | Weight | Module | What it answers |
|---|---|---|---|
| Skill overlap | 0.40 | `skill_overlap.py` | Does the resume have the ESCO skills the JD names? |
| Keyword BM25 | 0.15 | `bm25_scorer.py` | Does it have the JD terms ESCO doesn't cover? |
| Title / seniority | 0.15 | `title_match.py` | Right kind of job, right rung? |
| Experience | 0.10 | `experience_match.py` | Enough years? |
| Semantic | 0.20 | `semantic.py` | Broadly the right field? |

Every weight and threshold lives in `src/matching/config.py`. Nothing else
holds a magic number, because calibration rewrites all of them and a
calibration pass that means editing six files is a calibration pass that
doesn't happen.

## Schema changes

`db/migrations/002_matching_engine.sql`, idempotent:

- `match_results.skill_overlap_score` – the original schema has four score
  columns for five components. `keyword_score` is re-scoped to mean the
  BM25 signal specifically, and hard skill overlap gets its own column.
  They answer different questions and the UI shows them separately.
- `match_results.score_breakdown JSONB` – full per-component detail,
  matched/missing skills split by required vs preferred, top
  BM25-contributing terms, gap analysis. Computed at match time because
  the explainability panel needs it and recomputing in the UI
  layer means loading spaCy and a transformer per page render.
- `match_results.weights_used JSONB` – weights are **not** constant across
  rows (see "no signal" below), so without this an old score is
  irreproducible.
- `resume_chunks` / `jd_chunks` – per-section embeddings. See semantic.

## Components

### Skill overlap

Set arithmetic over ESCO `skill_id`, not surface strings, so "Python" and
"Python (computer programming)" unify through the taxonomy. Required
misses weighted 1.0, preferred misses 0.4 – otherwise a JD with a long
wishlist makes every resume look bad.

**This partly mitigates the known extraction limitation.** The
documented problem was that ESCO contains bare generic terms (`"plan"`,
`"design"`, `"call"`) that match ordinary prose. Intersection suppresses
much of that: a spurious `"plan"` in the resume only inflates the score if
the JD *independently* produced the same spurious match, and two
independent false positives colliding on the same term is much rarer than
either alone. The limitation is still real and still documented – it just
degrades this component considerably less than the raw extraction precision
figure suggests.

### Keyword BM25

Implemented directly rather than via `rank_bm25`, for two reasons.

BM25's entire value is IDF – it's what makes "Snowflake" outweigh
"communication" – and IDF is a property of a *corpus*. Handing `rank_bm25`
a two-document collection of one resume and one JD gives every term a
near-identical IDF and produces an expensive word counter wearing a BM25
label. IDF here comes from the ~2.4k staged Kaggle resumes instead
(`scripts/build_bm25_corpus.py`), which is the population the scored
document is drawn from. `rank_bm25` also has no clean way to score a
document absent from the corpus at index time, which is exactly the
requirement: fixed background population, new resume.

Only aggregate document frequencies and average length are persisted,
never corpus text – the Kaggle resumes contain real named individuals and
stay local and gitignored. The stats file is safe to commit.

Raw BM25 is unbounded and can't enter a weighted blend, so scores are
divided by the score of a reference document containing each query term
once at average length (which works out to exactly the sum of query IDFs)
and clipped to [0, 1].

**Known:** absolute values read low. Out-of-vocabulary JD terms get
maximum IDF and inflate the reference denominator even when they're
boilerplate. This is correct behaviour for genuinely rare technical terms
and slightly unfair for unusual filler. Rank ordering is unaffected;
Calibration should consider percentile scoring against the corpus rather
than treating the absolute number as meaningful.

### Title / seniority

Split into role family and seniority level, scored separately, because
"right job, wrong level" and "wrong job entirely" are different pieces of
advice and a single blended title score hides which one happened.

Family uses **asymmetric containment**, not Jaccard. The ingestion layer's
`extract_titles` keeps the whole line a title keyword appeared on, so
resume titles are routinely `"Data Analyst | Acme Corp | 2023-2024"`.
Jaccard punishes that extra context despite a perfect match; dividing by
the JD token count only asks how much of the advertised role the line
covers.

Seniority detection takes the **lowest** level mentioned, not the highest
– JDs routinely name-drop levels they aren't advertising ("reporting to
the Director", "mentored by senior engineers"), and the advertised level
is nearly always the most junior named.

`"associate"` is deliberately absent from the ladder. It sits at wildly
different levels by context ("Associate Director" vs "Sales Associate")
and already caused a false-positive bug in the degree regex. A
weak signal that's wrong half the time is worse than no signal.

Penalties are asymmetric: 0.30 per rung underqualified, 0.08 per rung
over. Being a rung below the advertised level is the failure mode a screen
exists to catch; a rung above is a mild mismatch that often still gets a
call.

### Experience

`max()` across the resume's stored years; the JD side is **re-extracted
from text**, not read from `jd_entities` at all.

The reason is a data-loss issue worth stating precisely, because the first
version of this got it wrong. `extract_years_experience`
takes the **upper** bound of a range, so `"3-5 years"` is stored as `[5]`
– the 3 is discarded inside the extractor, before anything is written to
the database. That's defensible on a resume (a rough proxy for career
length) and inverts the meaning on a JD, where the advertised bar is 3 and
scoring against 5 penalises every candidate sitting exactly at the stated
minimum.

The initial fix here was `min()` across the JD's stored values, on the
assumption that the lower bound was still recoverable. It isn't – `min([5])`
is 5. `profiles.extract_jd_min_years()` re-reads
`job_descriptions.cleaned_text` instead, keeping the lower bound of ranges,
and prefers figures sitting near explicit minimum language ("minimum 4
years", "at least 2 years of SQL") over incidental ones. Falls back to the
smallest figure in the posting when there's no cue.

Done in the matching layer rather than by changing
`extract_years_experience()`, which is behaving correctly for the input it
was designed for. This is a JD-specific reading of the same text, not a
bug fix to the extractor.

Shortfall is superlinear (`ratio ** 1.5`): 80% of the requirement scores
0.72, 30% scores 0.16. A linear ratio treats those as proportionally
different when they're qualitatively different.

Overqualification isn't penalised. Real ATS keyword screens don't filter
on too much experience; human reviewers sometimes do, but that isn't what
this tool claims to model.

### Semantic

Chunked, not whole-document. Embedding a 3-page resume as one vector
averages to a generic "this is a professional CV" direction and every pair
lands within a few points of the same cosine – the component contributes
noise, not signal. Chunks are packed to ~600 characters on blank-line
boundaries, which works because the ingestion `clean_text()` deliberately
preserves line structure, so section boundaries come for free without a
heading classifier.

Pooling is asymmetric: for each JD chunk take the best-matching resume
chunk, then average across JD chunks. That asks "is everything this job
wants covered somewhere in the resume?", which is the screening question.
The reverse would penalise a strong candidate for having a hobbies
section.

Document-level vectors are still written to `resumes.embedding` /
`job_descriptions.embedding` – cheap whole-document retrieval is exactly
what batch leaderboard scoring needs. They just aren't what the semantic
score reads.

Raw MiniLM cosine between two pieces of professional English rarely leaves
[0.25, 0.75], so it's rescaled across that band. **Those bounds are the
most provisional numbers in the engine** – estimated, not measured. Calibration
should replace them with the observed distribution across real postings.

## Missing signals drop out; they don't score zero

The rule the blend is built on. If a JD states no minimum experience, that
component is removed and the remaining weights renormalised to sum to 1 –
it stops having an opinion rather than dragging every candidate down. Same
for a JD with no extractable skills, or a pair with no stored embeddings.
`weights_used` records what was actually applied.

One deliberate exception: a resume that states no years at all scores
**neutral (0.5)**, not zero and not dropped. Most student and early-career
resumes never write "N years of experience" anywhere. That's a
resume-writing gap worth surfacing in gap analysis, not evidence of zero
experience – and scoring it as zero would make the tool useless for
exactly the people most likely to use it.

## Canonical skill labels and mention counts

`jd_entities.entity_value` / `resume_entities.entity_value` store
`SkillMatch.matched_text` – the surface form exactly as it appeared, so an
alias or a lowercase mention is recorded verbatim. That's the right thing
to store, and it's what `refresh_is_required` searches the raw text for.
It's the wrong thing to compare or display: ESCO adjacency keys on
`preferredLabel`, so an alias never resolves, and a UI reading "missing:
pyhton" in the employer's casing looks broken. Both loaders `LEFT JOIN
skills_taxonomy` and prefer the canonical `skill_name`, falling back to the
surface form when the join misses.

The matcher emits one entity row per occurrence, so a JD naming Python five
times inserts five rows. Counting rows per `skill_id` gives an exact
mention count for free – used to rank gaps by employer emphasis. This
replaced an earlier BM25 token-frequency proxy, which mis-counted
multi-word skills and alias forms.

## Required vs preferred

`jd_pipeline` defaults `jd_entities.is_required` to TRUE for everything and
explicitly deferred the distinction to here. `profiles.refresh_is_required()`
re-derives it by splitting JD text on headings and carrying a
required/preferred mode forward until a heading changes it – sections are
how JDs actually signal this, not per-sentence hedging. A skill is
downgraded to preferred only when *every* occurrence falls in a preferred
block; something listed under both "Required" and "Nice to have" stays
required, which is the stricter reading an ATS would take.

Called automatically by `match_pipeline` before scoring.

## Gap analysis

`esco_occupation_skill_relations.csv` was downloaded during setup and has
sat unused since. This is what it's for: it maps occupations to their
skills, so for any missing skill it can answer "which occupations need
this, and what else do those occupations need that this candidate already
has?" – turning "you're missing Airflow" into "you're missing Airflow, but
you list Luigi and cron-based scheduling, so lead with those."

Gaps rank required-first, then by how often the JD repeats the term.
Repetition is a rough proxy for how much the employer cares; a skill named
once in a wishlist and one named in the title, the summary and three
bullets aren't equally important, and an alphabetical list buries that.

The join goes through `preferredLabel` rather than URI, because
`skills_taxonomy` has no `esco_uri` column. Lossy on the 21 duplicate
labels dropped by `ON CONFLICT DO NOTHING` during the taxonomy load –
acceptable for a suggestion feature, where a missing suggestion costs
nothing and a wrong score would. The migration to fix it properly is in
`002_matching_engine.sql`, commented out, since it needs `load_taxonomy.py`
re-run with URI capture.

Degrades to empty if the CSVs aren't present locally; nothing else breaks.

## ATS parsability stays out of the blend

It rides along in `score_breakdown` for the UI warnings panel but
doesn't affect the final number. It's a separate axis by design – a resume
can score 90 on content and still be shredded by a real parser, and
averaging the two together would hide exactly that case, which is the one
most worth telling someone about.

## Testing

`tests/test_matching.py` – 30 tests, no DB and no model load. Every scorer
is a pure function over the profile dataclasses.

**Assertions are on ordering, not values.** Perfect pair > partial pair >
mismatch; underqualified penalised more than overqualified; rare-term
match beats common-term match. Calibration rewrites every weight in
`config.py`, and a test asserting `score == 73.4` breaks the moment that
happens – which trains you to edit the test until it passes, which is
worse than having no test at all. Monotonicity survives recalibration and
is the property actually being relied on.

Plus regressions for the specific decisions above: `"associate"` is not a
seniority signal; IDF never goes negative; missing components renormalise
rather than zero; a long extracted title line isn't penalised against a
clean one; semantic pooling is JD-directed.

## Known limitations

- **Title seniority is generous when the resume has no detectable level.**
  Falls back to family score alone, so a candidate with an undetectable
  level gets full title credit against a senior role. Deriving a level
  from years-of-experience bands would help, but the bands are arbitrary
  and would need calibrating. Left for calibration rather than guessed
  at now.
- **BM25 absolute values read low** – see above. Ordering is sound;
  the number isn't meaningful on its own yet.
- **Semantic rescale bounds are estimated, not measured.** The single
  biggest source of miscalibration in the current blend.
- **All weights are reasoned, not evidenced.** That is the entire point of
  calibration, and the README should say so rather than implying the numbers
  were derived from anything.
- **ESCO/common-word ambiguity from extraction persists**, though intersection
  mitigates it considerably (see skill overlap above).
- **Connection churn.** `get_connection()` opens a fresh psycopg2
  connection per call and the matching engine makes six or seven per
  match. Fine for one-at-a-time scoring against the Supabase pooler; it
  will not survive batch leaderboard scoring, which should either thread
  one connection through a scoring run or move `get_connection()` to a
  pool.

## Outcome

Five-component blend with transparent per-component breakdown, gap
analysis with ESCO-based adjacency suggestions, required-vs-preferred
backfill, chunked embeddings via pgvector, and 30 ordering-based
regression tests. Weights are provisional by design. Ready for the Reflex
UI, which reads `score_breakdown` and needs no recomputation.