# Parsing & Extraction

Status: complete.

## Text extraction

`src/ingestion/extract_text.py` – PDF via `pdfplumber`, DOCX via `python-docx`. Falls back to PyMuPDF for PDFs where `pdfplumber` returns under 50 characters of text, which happens with resumes exported from design tools (Canva/Figma-style templates) that occasionally produce a broken text layer.

DOCX extraction walks table cells in addition to paragraphs – resume templates frequently put contact info or a skills grid inside a table, which `python-docx`'s `document.paragraphs` alone misses.

`clean_text()` does light normalization (collapse repeated whitespace, strip stray control characters) before anything hits NER – line breaks are kept intentionally, since both the years-of-experience regex and title extraction rely on line structure.

## ATS parsability scoring

`src/ingestion/ats_parsability.py` – standalone from content extraction, by design: a resume can have perfect keyword coverage and still fail a real ATS because of how it's formatted.

Checks four things. Each deduction scales with how much of the document
the issue affects, so the score is continuous rather than landing on one
of thirteen fixed values:

| Issue | Full deduction | Severity | Detection |
|---|---|---|---|
| Tables | −25 | fraction of pages containing one | ruled lines, or a localised text-aligned grid |
| Multi-column | −20 | fraction of pages affected | gutter-detection heuristic (below) |
| Headers/footers | −15 | always 1.0 — a running header is on every page | repeated line in the top/bottom 8% margin |
| Images | −10 | count, full at 3+ | `page.images` (PDF) / `doc.inline_shapes` (DOCX) |

Any occurrence costs at least half its deduction: one mangled section can
be the one holding your experience. A table on one page of four scores
88; tables on all four score 75.

**Three false-positive classes were found by testing against real
resumes, and each is now excluded.**

1. **The whole page is not a table.** pdfplumber's text strategy infers
   structure from whitespace alignment, and on an ordinary resume every
   line becomes a row. Measured on 25 random real resumes, the original
   "any 2×2 grid" rule fired on 25 of 25 — every resume scored exactly
   75, and the check carried no information. Now a table must be a
   *localised* grid: at most 35% of page height, ≥3 rows, ≥2 columns.

2. **Columns that cut through words are not columns.** A resume flagged
   at 75 turned out to have no table at all: the inferred boundaries ran
   straight through its project bullets — `Resu|me Matching`, `In
   Progr|ess`, `Pyth|on`. Real tables never split a word. Grids where
   more than 5% of words are sliced by a column edge are now rejected;
   on the validation set the two groups did not overlap (rejected grids
   sliced 8.6–37.3% of words, genuine tables 3.4–3.7%).

3. **A running header plus a heading is still a running header.** The
   header check compared the whole top band as one string, so a page
   reading "…Curriculum Vitae JORDAN BLAKE" and another reading
   "…Curriculum Vitae CERTIFICATIONS" looked different and the check
   never fired. It now compares line by line and strips digits, so
   "Page 1 of 3" matches "Page 2 of 3".

After all three, a fresh sample of 40 real resumes scores 34 clean, 4 at
85, 2 at 88 — the check finally distinguishes documents instead of
flagging everything.

Two detection issues needed real iteration to get right, caught by building synthetic test PDFs rather than trusting the first pass:

- **Table detection had to use pdfplumber's `text` strategy, not the default.** The default strategy only detects tables with visible grid lines. Real resume templates almost always use *borderless* layout tables – which is exactly the case that matters, since that's the formatting an ATS can't see either. Switched to `vertical_strategy="text"` / `horizontal_strategy="text"`, which infers table structure from text alignment instead of drawn lines.

- **The first multi-column heuristic false-positived on any normal wrapped paragraph.** Checking "do words appear on both halves of the page" fails immediately – a single wrapped line of justified text naturally has words on both sides of the midpoint. Rewrote it to group words into lines first, then classify each *line* as confined to one column or crossing the gutter. Normal single-column text has almost every line crossing the gutter; genuine multi-column layouts have almost no line crossing it. Also replaced the fixed 50/50 page-center assumption with dynamic gutter detection (largest whitespace gap in the middle 25–75% of the page), since real sidebar layouts aren't always an even split.

Regression tests for both fixes live in `tests/test_ats_parsability.py`
against synthetic fixture PDFs in `tests/fixtures/`.

**Known overlap:** a genuine two-column layout can trip *both* the table and multi-column checks, since text-alignment-based table detection and column-gutter detection are both fundamentally reading the same whitespace-gap signal. Not treated as a bug – both checks independently lower the score, so a resume with real layout problems still ends up correctly flagged as low-parsability even if the specific flag label is approximate.

## NER / entity extraction

`src/nlp/extract_entities.py`:

- **Skills** – routed through `src/nlp/skill_matcher.py`, which builds a spaCy `PhraseMatcher` from all 13,939 ESCO skill names + aliases loaded during dataset setup. Exact/alias match, case-insensitive, not fuzzy – fuzzy matching against a ~14k-term list produces too many false positives (e.g. "R" matching inside unrelated words). Terms under 3 characters are excluded from matching for the same reason, plus a small stoplist (`AMBIGUOUS_SKILL_TERMS`) for real skill names that are also common English words at 4+ characters – e.g. `"LESS"` (the CSS preprocessor) matching inside `"(Less than 1 year)"` boilerplate, found via validation against the Kaggle NER dataset (see below). Fuzzy/embedding similarity is deferred to the matching-engine phase, where it's meant to be a secondary semantic signal, not a hard skill match.
  - **Curated tech skills** (`src/nlp/tech_skills.py`, 124 entries, loaded with `python -m scripts.load_tech_skills`) sit alongside ESCO. ESCO has no entry for most of what data and AI postings screen on (Tableau, Power BI, pandas, PyTorch, LLMs, RAG, AWS, Jira) and maps a few to the wrong concept (TensorFlow → "computer vision", and bare "Spark" → ESCO's `SPARK`, which is an Ada programming language). See "Validation against real job postings" below.
  - **Precedence:** every surface form resolves to exactly one skill – curated term, then ESCO skill name, then ESCO alias. Before this, whichever match the `PhraseMatcher` returned first won.
  - **Generic single-word ESCO aliases are filtered by shape:** an alias that is one all-lowercase word (`patterns` → dies, `brands` → trademarks, `logistic` → logistics) is dropped; capitalised, mixed-case and multi-word aliases and all ESCO skill names are kept. 518 aliases dropped.
  - **Case-sensitive terms:** curated names that are also ordinary words (`Excel`, `React`, `Spark`, `Snowflake`, `Confluence`, `RAG`, `VaR` …) are matched by a second `PhraseMatcher` on exact case, so "excel in a team" and "react quickly" don't match.
- **Titles** – keyword-line heuristic rather than spaCy's built-in NER labels. ESCO occupation labels are too noisy for reliable free-text title extraction. Uses whole-word matching (`\b` boundaries), not plain substring checks – a first version used substring matching and false-positived on `"Directorate"` (matched inside "director") and `"Managerial"` (matched inside "manager").
- **Education** – regex over common degree abbreviations (`Bachelor`, `B.Sc`, `MBA`, `Associate`, etc.), optionally followed by the field of study. `Associate` is handled more strictly than the other degree words: it's extremely common as a job-title word ("Associate Consultant", "Sales Associate"), so it's only treated as a degree signal when followed by a colon + field of study or the explicit word "degree" – a dash is deliberately not accepted, since "Title - Company" uses dashes just as often as a real degree line would. (This was a real bug caught by validating against the Kaggle NER dataset – see below.)
- **Years of experience** – regex over numeric range patterns (`3-5 years`, `5+ years experience`), taking the upper bound when a range is given. Decimals are parsed as part of the number (`"6.8 years"` → `6.8`, `"3.2-years"` → `3.2`). An earlier version only matched whole digits, so the word boundary before the `8` in `"6.8"` let it read 6.8 years as `8`. Whole numbers stay integers. Downstream, `profiles._safe_int` floors a stored `"6.8"` to `6`, which is conservative and closer to the truth than the old `8`. `"5 or more years"` is accepted (missed on a real posting until fixed). Known gap: abbreviated units (`"9 Yrs"`) and months (`"15 Months"`) aren't matched.

## Storage

`src/ingestion/pipeline.py` – CLI entrypoint, one resume file in, one row in `resumes` + N rows in `resume_entities` out:

```bash
python -m src.ingestion.pipeline path/to/resume.pdf
```

`src/ingestion/jd_pipeline.py` – same entity extraction reused for job descriptions (Adzuna or pasted text, so no file parsing or ATS parsability check needed there – that's resume-formatting-specific). `is_required` is defaulted to `TRUE` for every JD entity for now; distinguishing required-vs-nice-to-have language ("preferred", "bonus") is left for the matching-engine phase, next to the weighted matching engine it actually feeds into.

`resume_entities.confidence` is left `NULL` for now rather than populated with a fabricated number – a real confidence score (NER label probability, or exact-vs-alias match type) is a later-phase refinement once there's an actual use for it in scoring.

## Validation against Kaggle NER ground truth

`tests/validate_against_kaggle_ner.py` scores extraction against the Kaggle "Resume Entities for NER" dataset (`resume_entities.json` – despite the extension, it's JSONL: one JSON object per line, each with a `content` field and character-offset `annotation` spans).

Scored by **overlap**, not exact match, since ground-truth spans and our extracted spans operate at different granularity by design – e.g. `Designation` ground truth is a short title string while our heuristic grabs the whole line it sits on. Two numbers per label:
- **precision** – fraction of our extracted spans that overlap at least one ground-truth span
- **coverage** – fraction of ground-truth characters captured by any of our spans

Run against the full 220-record dataset. "First run" is the number from when this phase was first written up; "current" is a full re-run after the fixes in "Validation against real job postings" below:

| Label | First run: spans / precision / coverage | Current: spans / precision / coverage |
|---|---|---|
| Skills | 5,564 / 20.8% / 14.3% | 4,849 / 20.8% / 14.0% |
| Designation | 632 / 44.6% / 41.7% | 673 / 44.0% / 43.8% |
| Degree | 224 / 47.8% / 40.6% | 168 / 63.7% / 40.6% |
| Years of Experience | 61.4% (27/44, ±1 year) | 77.3% (34/44, ±1 year) |

- **Skills:** 13% fewer spans (generic-alias filter) at unchanged precision – the dropped matches weren't landing on labelled skill spans either.
- **Designation:** more spans and higher coverage from the added general-workforce title keywords.
- **Degree:** the degree pattern wasn't changed between the two runs. The first-run figure most likely predates the `"Associate"` fix below being committed; not claimed as an improvement from later work.
- **Years:** decimal parsing fixed; exact matches went from 21/44 to 33/44.

**Skills' low number is not a straightforward "our matcher is bad" result.** Ground-truth `Skills` spans mark a specific labeled block (the resume's "SKILLS" section); the ESCO matcher correctly finds skill terms *anywhere* in the document, including inside job descriptions – those are real, correct matches that just fall outside the labeled span, so the overlap metric scores them as false positives. `tests/spot_check_skills.py` prints our extracted terms next to the ground-truth block per resume so this can be checked by eye rather than trusted from the aggregate number alone – a first sample confirmed genuine matches landing outside the labeled block, consistent with this being a metric artifact rather than a real precision problem, though a fuller read across more resumes is worth doing before treating that as settled.

`Designation`/`Degree` numbers are cleaner comparisons (closer in nature to what we extract) and land in a believable range for regex/keyword heuristics – a reasonable baseline to improve on later, not a red flag. Coverage for `Designation` is also pulled down by ground-truth label noise found during validation: at least one record mislabels a degree line (`"B.E in Information science and engineering"`) as `Designation` instead of `Degree` – not something our code did wrong.

**Bug found and fixed via this validation:** bare `"Associate"` in the degree-word list (added to catch `"Associate : Accounting"`-style degree lines) was false-positive-matching job titles like `"Associate Consultant"` and `"Application Development Associate - Accenture"`, since "Associate" is far more common as a job-title word than "Bachelor"/"Master" are. Fixed as described above. Regression tests for this in `tests/test_extract_entities.py`.

**Second bug found via the same validation, this time in the skill matcher – later determined to be a broader limitation, not a one-off:** `tests/spot_check_skills.py` first surfaced `"LESS"` (a real ESCO skill – the CSS preprocessor language) matching inside `"(Less than 1 year)"` boilerplate, since case-insensitive matching treats `"LESS"` and `"less"` identically. Fixed in `src/nlp/skill_matcher.py` with a small stoplist (`AMBIGUOUS_SKILL_TERMS`).

Re-running the spot-check after that fix surfaced the same ambiguity class recurring on a different record: ESCO includes broad competency terms with bare generic-word aliases (`"call"`, `"plan"`, `"design"`, `"purchase"`, `"integrity"` all matched as skills inside ordinary prose that had nothing to do with those competencies). This isn't a handful of one-off terms to stoplist away – it's a structural property of exact matching against a ~14k-term general-purpose taxonomy: some fraction of it will always overlap with common English vocabulary, and a new term surfaces every time validation runs against a new batch of resumes.

**Decision: documented as a known limitation, not chased further.** Two ways to actually fix this properly were considered: (a) keep an ever-growing manual stoplist – doesn't scale, since new resumes will keep surfacing new colliding terms; (b) build a systematic common-English-word filter (e.g. exclude any ESCO term that collides with a list of the ~200-300 most common English words) – more systematic, but a blunter instrument that would also suppress genuine matches (someone who really does list "Design" as a skill loses credit for it), and doesn't address matches embedded in prose the way a smarter context-aware disambiguation would (e.g. only trusting single-common-word matches in list/bullet context near a "Skills" heading, versus ordinary sentence prose). Both trade one error type for another rather than solving the root cause. Real disambiguation is matching-engine-scale design work, not a quick patch, so `LESS` stays fixed as a specific, confirmed case, and the general class is left as a documented limitation rather than addressed with a stopgap that wouldn't meaningfully improve accuracy.

**Revisited after scoring real job postings – see below.** On 13 real postings the ambiguity wasn't a tail of occasional misses; it made up a large share of every extracted skill list. That changed the trade-off, and the shape-based alias filter was added.

Also worth noting from the spot-check: `"Email"` shows up as a frequent "false positive," but this is very likely specific to *this dataset* – every record in the Kaggle export has `"Email me on Indeed: indeed.com/r/..."` boilerplate footer text, which real user-uploaded resumes won't have. Left unfixed since it's a test-set artifact, not something that should shape the pipeline for real inputs – worth rechecking if it turns up on actual uploaded resumes later.

**Ground-truth offset drift – confirmed, not just theorized.** One record (Akhil Yadav Polemaina) showed 0% overlap on every label despite the extraction looking reasonable on inspection – every ground-truth `Skills` span in that record came back truncated by **exactly one character** (`"Teradat"` missing the final `a`, `"Mainfram"` missing `e`, `"cobo"` missing `l`, `"serviceno"` missing `w`). That consistent one-character-short pattern across every span in the record, on a resume using heavy unicode bullets (●), confirms the earlier theory: the annotation tool that produced this ground truth recorded **byte** offsets while Python string slicing counts **characters** – multi-byte bullet characters silently drift the two counts apart. This is a data
artifact specific to unicode-bullet-heavy records in this Kaggle export, not a bug in the extraction pipeline – the low scores on affected records should be read with that in mind rather than taken as a pipeline regression. Not corrected in the validation script itself, since fixing it would mean re-deriving byte-based offsets for this one dataset's quirks rather than improving anything about the pipeline being validated.

## Validation against real job postings

The Kaggle ground truth only covers resumes. The first run against 13 real Sydney data, AI, business-analyst and quant postings (and one real resume) exposed problems that the unit tests and the Kaggle metric couldn't:

1. **ESCO lacks most modern tools.** SQL mapped to "database management systems"; Tableau, Power BI, Excel, pandas, NumPy, scikit-learn, PyTorch, LLMs, RAG, AWS, Azure, Jira, React and Airflow had no entry at all. A skill the matcher can't see never appears as matched *or* missing, so the gap analysis skipped exactly the requirements these roles screen on. Fixed with the curated list.
2. **Generic aliases dominated the skill lists.** Each of these was an actual match: "patterns" → *dies*, "brands" → *trademarks*, "integrity" → *morality*, "harnesses" → *climbing equipment*, "Reserve" (Bank) → *make reservations*, "CFD" (the trading product) → *computational fluid dynamics*, "open-source" → *Source (digital game creation systems)*, "logistic regression" → *logistics*. Fixed with the alias-shape filter plus `source` and `cfd` in the stoplist. On the validation set, 22 of the 26 matches the filter removed were wrong; the 4 real losses (Git, TensorFlow, two borderline soft-skill matches) are covered by curated terms.
3. **"5 or more years" wasn't recognised**, so that posting had no years requirement. Fixed on both the resume and JD side (`profiles._JD_YEARS_RE`, which also had the decimal bug).

Stored entities keep whatever extraction produced at ingestion; `python -m scripts.reextract_entities` re-runs extraction over stored text after changes like these.

Residual noise, left as is: a few multi-word ESCO aliases still land on the wrong concept ("job opportunities" → *job market offers*, "architecture standards" → *architecture regulations*, "trading strategies" → *trade sector policies*). Multi-word aliases are right far more often than single words, so they aren't filtered.

## Testing

`tests/test_extract_entities.py` – regex/heuristic extraction (titles, education, years-of-experience), no DB or spaCy model load required. 20 tests, including decimal and "or more" years-of-experience and general-workforce title keywords (accountant, assistant, technician, officer, etc.), plus regressions for the two false-positive bugs found while building and validating this phase (`"Directorate"`/`"Managerial"` substring matches, `"Associate"` job-title matches).

`tests/test_skill_matcher.py` – precedence, the alias filter and case-sensitive matching, each case a real mismatch from the job-posting validation. Built from in-memory taxonomy rows and a blank spaCy pipeline, so no DB or model load.

`tests/test_ats_parsability.py` – parsability scoring against synthetic fixture PDFs, generated with `reportlab` specifically to catch the two false-positive/false-negative bugs found during development.

`tests/validate_against_kaggle_ner.py` – overlap-based scoring against external ground truth (see above).

`tests/spot_check_skills.py` – manual side-by-side inspection tool for the Skills metric, since the aggregate number alone is misleading (see above).

## Outcome

Extraction, ATS parsability scoring, NER, ESCO skill matching, DB storage, and validation against external ground truth are all implemented and tested. This phase is functionally complete. Three real bugs were found and fixed via testing against real data rather than assumed correct (`"Directorate"` substring false-positive, `"Associate"` job-title false-positive, `"LESS"` skill/common-word ambiguity). Decimal years-of-experience parsing (`"6.8 years"` read as `8`) was first documented as a limitation and then fixed, raising years-of-experience accuracy from 61.4% to 77.3% (±1 year) and exact matches from 21/44 to 33/44. Common-English-word/ESCO-term ambiguity was first left as a known limitation, then addressed with a shape-based alias filter once real job postings showed how much of the extracted skill lists it made up; ESCO's gaps on modern tools are covered by a curated list of 124 skills. One ground-truth data-quality issue in the Kaggle dataset itself (byte/character
offset drift on unicode-bullet-heavy resumes) was investigated and confirmed, not a pipeline bug. Ready to move to the matching engine. 