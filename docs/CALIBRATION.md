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

**Domain discrimination is weak: structural AUC 0.68.** This is the
number that matters most, and it needs no labels, so it cannot be
circular. Relevant postings average 32.7 and unrelated ones 29.6 —
barely separated. The candidate's resume ranks above five unrelated
contrast resumes on only 13 of 21 relevant postings. The engine ranks
*within* a plausible set well; it cannot reliably tell a data role from a
sales role.

The likely cause is the generic tail of ESCO: terms like "communication",
"statistics" and "project management" are extracted from almost every
posting and appear on almost every resume, so every pair earns a floor of
overlap regardless of field. That is the next thing to fix, and it is an
extraction problem, not a weighting one.

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

1. **Fix domain discrimination.** Down-weight or filter ESCO's generic
   competency tail, which every posting and every resume shares. Measure
   against the structural AUC, which is label-free.
2. Grow the evaluation set past 40 and re-check the thresholds — ideally
   labelled blind rather than corrected from a draft.
3. Revisit `keyword_bm25` (AUC 0.61): either improve the query
   construction or accept a lower weight, with evidence either way.
