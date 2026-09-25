# Calibration

Run 24 September 2026. The engine had never been calibrated: the weights
and the verdict thresholds were reasoned guesses made before any real
data existed, and the consequence was that **every real posting scored
"likely reject"**, including roles the candidate rated a good fit.

This is what was measured, what changed, and what is still wrong.

## The evaluation set

| | |
|---|---|
| Postings | 40, all full text |
| Sources | 13 pasted from LinkedIn/Seek earlier, 27 pulled from Greenhouse / Lever / Ashby job-board APIs |
| Spread | grad and intern through senior; quant, data, AI and finance through to nursing, sales and marketing |
| Resumes | 1 candidate resume + 5 deliberate mismatches from Kaggle (healthcare, sales, chef, finance director, IT director) |
| Pairs scored | 240 |

Postings came from company job boards rather than Adzuna because
Adzuna's API truncates every description at 500 characters, which is
mostly company blurb and contains none of the requirements the engine
scores against (`scripts/fetch_board_jds.py`).

The set is deliberately unbalanced towards things that should *not*
match. A set of plausible matches can only show that scores are high; it
cannot show the engine separates anything.

## Labels

The candidate labelled each posting `good` / `maybe` / `no` — "would you
apply, and would you have a shot". 7 good, 10 maybe, 23 no.

Two things to be honest about:

- **The sheet was pre-filled.** The assistant drafted a label for each
  posting and the candidate corrected it, rather than labelling from
  blank. That is weaker evidence than independent labelling, and it is
  the reason the title component's result below cannot be taken at face
  value.
- **8 of the 23 "no" labels were auto-filled** for unrelated fields
  (nursing, field sales, performance marketing). They are recorded with
  `label_source=auto` in `data/eval/labels.csv`, and the headline figures
  were checked with and without them (AUC 0.963 all, 0.971 on
  human-reviewed only).

## What the measurements showed

### Two real defects, both fixed

**1. Thin postings scored higher for having less content.** The top false
positive was a *Lead Talent Acquisition Partner* role at 28.1, above
several roles the candidate wanted. The extractor found 4 skills in it,
the resume matched 2, so skill overlap scored 50 — while a real data
analyst posting yielding 18 skills with 8 matched scored 39. The overlap
denominator is now floored at `SKILL_OVERLAP_MIN_EVIDENCE` (7 skills'
worth): a thin posting is weak evidence, not strong evidence. Matching
everything a substantial posting asks for still scores 1.0.

**2. The semantic rescale bounds were wrong.** `[0.25, 0.75]` was an
estimate. Measured across 268 stored matches, raw pooled MiniLM
similarity runs 0.11–0.51 (p5 0.19, median 0.32, p95 0.44). The ceiling
was above anything that occurs, so the component could never exceed ~0.5,
and a quarter of all pairs fell below the floor and clipped to exactly 0
— erasing the difference between "unrelated" and "very unrelated".
Bounds are now `[0.15, 0.45]`, just outside the observed range.

Effect of the two fixes, on the same 40 postings:

| | Before | After fix 1 | After both |
|---|---|---|---|
| Rank correlation with labels | 0.49 | 0.57 | **0.59** |
| good vs no (AUC) | 0.95 | 0.96 | **0.96** |
| Leave-one-out band accuracy | 55% | 55% | **70%** |
| Skill overlap on its own (AUC) | 0.82 | 0.88 | 0.88 |

Those are the figures as of the calibration pass. Two later bug fixes
(see "What is still wrong") moved rank correlation to 0.58 and left the
rest unchanged; `data/eval/scores.csv` holds the current numbers, and the
pre-fix ones are in its git history.

### Thresholds

Observed distribution under the calibrated engine: good 32–50, maybe
22–39, no 9–36.

`VERDICT_PASS_THRESHOLD` 70 → **37**, `VERDICT_BORDERLINE_THRESHOLD`
45 → **30**. At 37, 6 of 7 good postings clear the bar and none of the 23
"no" postings do. At 30, every good posting is at least borderline.

Resulting agreement:

| Candidate's label | likely_pass | borderline | likely_reject |
|---|---|---|---|
| good (7) | 5 | 2 | 0 |
| maybe (10) | 1 | 4 | 5 |
| no (23) | 0 | 9 | 14 |

**No posting the candidate called a good fit is rejected, and none they
ruled out passes.** The "maybe" band is where the disagreement lives,
which is what "maybe" is for.

### Weights: deliberately unchanged

A grid search over 162 weightings found a best candidate scoring 0.925
against the current 0.880 — but it got there by raising
`title_seniority` from 0.15 to 0.25, and that component's apparent
perfection is an artefact:

> **Title/seniority scores AUC 1.00 — and the number is circular.** The
> draft labels used "senior role → no" as a rule of thumb. The component
> measures seniority distance. It is predicting the labelling procedure,
> not the candidate's fit. Weighting it up would bake that rule into the
> product.

With title capped at its current weight, the best alternative beats the
current weights by 0.012 AUC — noise at n=40, and slightly *worse* on the
label-independent structural check. So the weights ship unchanged, and
the honest reason is recorded here rather than the tuned numbers being
presented as evidence.

Per-component, scored alone against the labels:

| Component | AUC | Read |
|---|---|---|
| title_seniority | 1.00 | circular, see above |
| skill_overlap | 0.88 | the real workhorse |
| semantic | 0.74 | a genuine secondary signal |
| keyword_bm25 | 0.61 | weak |
| experience | 0.50 | no signal — only 4 postings state a minimum |

## What is still wrong

**The structural AUC of 0.68 was misdiagnosed. Corrected below.**

The original entry here read: *"the likely cause is the generic tail of
ESCO — terms like 'communication', 'statistics' and 'project management'
are extracted from almost every posting and appear on almost every resume,
so every pair earns a floor of overlap regardless of field."* That was a
plausible guess, recorded as a likely cause and never measured. When
measured, it is wrong. It is kept here because the way it failed is the
useful part.

### What the generic tail actually does

Of the skills the candidate's resume shares with a posting, how many
postings in each labelled group ask for them (21 relevant, 8 unrelated):

| | matches on *relevant* postings | matches on *unrelated* postings |
|---|---|---|
| Python | 14/21 | 0/8 |
| machine learning | 9/21 | 0/8 |
| statistics | 7/21 | 1/8 |
| SQL | 3/21 | 0/8 |
| communication | 4/21 | 4/8 |

Only `communication` behaves the way the generic-tail story predicted, and
it is one term. Skill overlap is the *best* discriminating component here
(AUC 0.88 against the labels), not the source of the problem.

### The pooled number was hiding an inversion

Splitting the same comparison by the advertised level of the posting:

| | relevant vs unrelated |
|---|---|
| entry | n/a — no unrelated postings at this level |
| mid | **AUC 0.97** |
| senior | **AUC 0.33** — inverted |
| pooled | 0.68 |

Level and domain are not independent in this label set. The senior
postings are largely ones the candidate marked "no" *on grounds of
seniority*, so "unrelated" and "too senior" overlap, and the pooled figure
averages a strong signal with an inverted one. `scripts/evaluate.py` now
prints the stratified rows, because the pooled figure alone was read as an
engine weakness for longer than it should have been.

At senior level `senior/unrelated` averaged 29.6 against
`senior/relevant` 26.7 — the wrong way round, and inverted on the
semantic, skill and title components alike.

### Most of the remaining gap is the resume, not the engine

The same 40 postings, the same labels, three different resumes:

| resume | pooled | mid | senior | rho | good-vs-no |
|---|---|---|---|---|---|
| the candidate's | 0.68 | 0.97 | 0.33 | 0.59 | 0.96 |
| `avery_chen_clean.pdf` (data science graduate) | **0.86** | **1.00** | 0.43 | 0.70 | 0.98 |
| `jordan_blake_tables.pdf` (business analyst) | 0.73 | 0.80 | 0.57 | 0.41 | 0.77 |

The candidate's resume leads its skills section with *Customer Service*
and *Administration*, and its two extracted titles are **Retail Sales
Assistant** and **Data Entry Officer**. Its overlap with sales and service
postings is real content in the document. A chunk-level trace of the
worst offender — "Senior Account Executive, Mid Market", the highest
scoring unrelated posting — showed four of its seven chunks matching the
resume's customer-service block, the strongest at 0.53 for *"exceptional
communication and rapport-building skills"*.

So the engine is reporting what the document says. "Unrelated" in
`labels.csv` means *the candidate does not want this job*, which is not
the same claim as *this resume does not match this posting*, and the
structural control silently assumed they were.

### What was genuinely broken, and is now fixed

Two real bugs surfaced during the investigation. Neither was the generic
tail:

1. **Scam warnings and employer copy reaching the embedder** on 5 of 62
   postings. `strip_boilerplate` missed "APPLICANT SAFETY POLICY: FRAUD
   AND THIRD-PARTY RECRUITERS", "Application Guidelines" and "Meet our
   team", so ~460 characters about bank details and passport numbers
   became a JD chunk that no resume can cover. The markers added are
   deliberately specific: a bare `fraud` marker would have stripped the
   requirements of the genuine fraud-analytics and payments-risk roles in
   this corpus, which is the worse error.
2. **"Senior Account Executive, Mid Market" read as a mid-level role.**
   `detect_seniority` takes the *lowest* rung mentioned, which is right
   for body text ("reporting to the Director") and wrong when a market
   segment collides with a rung. A senior sales role therefore drew a
   smaller underqualified penalty (0.7) than the senior data roles it was
   being compared against (0.4) — one of the things inverting the senior
   control. One posting in 62, and it was the top-scoring unrelated one.

Applying the boilerplate fix to already-stored postings needs
`scripts/reembed.py`, added for this: chunks are written once at
ingestion, so a new marker otherwise only affects future ingests. It
re-chunked 18 of the 62 stored postings.

### Both fixes are correct and neither moves the metric

Re-scored after re-embedding: 280 pairs, the same 40 postings, three
resumes, before → after.

| resume | pooled | mid | senior | rho |
|---|---|---|---|---|
| the candidate's | 0.68 → **0.71** | 0.97 → 0.97 | 0.33 → 0.33 | 0.59 → 0.58 |
| `avery_chen_clean.pdf` | 0.86 → **0.87** | 1.00 → 1.00 | 0.43 → **0.47** | 0.70 → 0.68 |
| `jordan_blake_tables.pdf` | 0.73 → **0.71** | 0.80 → 0.80 | 0.57 → 0.57 | 0.41 → 0.39 |

Pooled AUC moves +0.03, +0.01 and **−0.02**. The mid-level figure is
identical on all three. The senior figure moves on one resume out of
three. `good`-vs-`no` stays at 0.96 for the candidate's resume.

The one control that improved cleanly is the contrast-resume ranking: the
candidate's resume now ranks above the five deliberate mismatches on
**14 of 21** relevant postings, up from 13.

The individual corrections do land where they should — "Senior Account
Executive, Mid Market" falls 32.0 → 30.7, and the postings whose scam
warnings were removed rise by up to 2.2 points. But on aggregate this is
noise: a spread of −0.02 to +0.03 on 29 relevant/unrelated postings is
well inside what one posting changing rank can produce, and the direction
is not even consistent across resumes.

`rho` drifts down 0.01–0.02 on all three, which looks systematic but is
not interpretable: for the two fictional resumes `rho` measures agreement
with *the candidate's* judgement of their own fit, which those resumes
were never labelled against. Only the first row's `rho` means anything,
and −0.01 on 40 postings is noise.

This is the expected result of the diagnosis above, not a disappointment
to be explained away: one posting in 62 had the seniority bug, and 5 had
boilerplate reaching the embedder, so neither could plausibly move a
40-posting AUC. They are worth keeping because they are correct — a fraud
notice is not a job requirement, and a senior role is not a mid-level one
— not because they bought a number.

**The corollary is the useful part.** The senior inversion is untouched by
both fixes, on every resume tried. It is therefore not an artifact of
these two bugs, and the remaining candidates are the label design (level
and domain are confounded) and the resume content — which is where the
next item in "Next" points, and why "filter ESCO's generic tail" is no
longer on that list.

**Other limits, stated plainly:**

- One resume, one labeller, 40 postings. These are separation points for
  this candidate, not an employability standard.
- Labels were corrected from a draft rather than produced independently.
- `experience` contributes nothing on this set — only 4 postings state a
  minimum, so it is dropped from the blend almost everywhere.
- Two postings in the set are the same IMC internship loaded twice, from
  the manual batch and the board fetch.
- Thresholds were chosen on the same 40 postings they are reported on.
  Leave-one-out accuracy (70%) is the honest figure; the in-sample table
  above flatters them.

## Reproducing

```bash
python -m scripts.fetch_board_jds --out data/jds/board   # pull postings
python -m scripts.build_eval_set                          # sample, ingest, write labels.csv
python -m scripts.evaluate --score                        # score every pair
python -m scripts.evaluate                                # metrics only
python -m scripts.calibrate                               # weight and threshold search
```

`data/eval/labels.csv` (the judgements) and `data/eval/scores.csv` (the
resulting numbers) are both committed, so the figures above can be
recomputed without re-running the pipeline.

## Next

1. **Separate "wrong field" from "too senior" in the label set.** This is
   now the top item, and it replaces "filter ESCO's generic tail", which
   was the wrong target. The structural control needs a domain axis that
   does not correlate with level: unrelated postings at every level, and a
   `domain` judgement made independently of whether the candidate would
   apply. Until then the senior-level AUC cannot distinguish an engine
   fault from a label-design fault, and the pooled figure should not be
   quoted on its own.
2. **Re-check the senior inversion once the labels are clean.** It
   persisted on all three resumes tried (0.33 / 0.43 / 0.57), so something
   beyond the "Mid Market" bug is likely still there. Note where the
   "Mid Market" fix leaves the title component: every senior posting in
   the set now reads as level 3 against a level-1 resume, so the seniority
   half is identical (0.4) across all of them, and the family half is 0.0
   for both the sales and the AI roles — the component stops
   discriminating at senior level rather than inverting. Whatever
   inversion survives is therefore in `semantic` and `skill_overlap`, and
   those should be measured per-component before anything is reweighted.
3. Grow the evaluation set past 40 and re-check the thresholds — ideally
   labelled blind rather than corrected from a draft.
3. Revisit `keyword_bm25` (AUC 0.61): either improve the query
   construction or accept a lower weight, with evidence either way.
