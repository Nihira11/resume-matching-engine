"""
Every tunable number in the matching engine lives here.

Calibration against real job postings will rewrite these, so they live in
one module rather than scattered as literals across the scorers -- the
calibration pass should be a single-file edit, and `weights_used` is
persisted per match_results row so an old score stays reproducible after
the weights move.

Nothing in here is claimed to be optimal. The starting values are
reasoned defaults; the point of calibration is to replace them with numbers
that have evidence behind them.
"""

from __future__ import annotations

import os
from pathlib import Path

# Data files are addressed from the repo root, never from the working
# directory. Reflex runs the app with app/ as its cwd, so relative paths
# silently missed both the BM25 corpus statistics and the ESCO adjacency
# files -- the keyword component dropped out of the blend and gap
# analysis lost its "related skills" suggestions, with no error anywhere.
# DATA_ROOT can be overridden for containers that lay the tree out
# differently.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path(__file__).resolve().parents[2]))

# ---------------------------------------------------------------------
# Blend weights
# ---------------------------------------------------------------------
# Hard skill overlap is weighted highest because that is what real ATS
# keyword screens actually do. Semantic similarity is deliberately a
# secondary signal -- it is good at "this resume is broadly in the right
# field" and bad at "this resume has Airflow", and the second question is
# the one that gets people filtered out.
COMPONENT_WEIGHTS: dict[str, float] = {
    "skill_overlap": 0.40,
    "keyword_bm25": 0.15,
    "title_seniority": 0.15,
    "experience": 0.10,
    "semantic": 0.20,
}

# ---------------------------------------------------------------------
# Skill overlap
# ---------------------------------------------------------------------
# A missed "required" skill hurts; a missed "nice to have" should cost
# something but not much, otherwise long wishlist JDs make every resume
# look bad.
REQUIRED_SKILL_WEIGHT = 1.0
PREFERRED_SKILL_WEIGHT = 0.4
# Floor under the overlap denominator, so a posting with very few
# extractable skills cannot score highly on a coincidence. Calibration on
# 40 real postings found the top false positive was a "Lead Talent
# Acquisition Partner" role: 4 skills extracted, 2 matched, scoring 50 --
# above a data analyst posting where 8 of 18 matched (39). A thin posting
# is weak evidence, not strong evidence.
#
# A floor rather than additive smoothing: matching everything a
# substantial posting asks for should still score 1.0, and smoothing took
# that away. Postings with at least this much weight are scored normally;
# thinner ones are divided by the floor. See docs/validation-results.md.
SKILL_OVERLAP_MIN_EVIDENCE = 7.0

# Phrases that flip a JD section from required to preferred. Applied at
# section level, not per-sentence -- JDs signal this with headings far
# more often than inline.
PREFERRED_MARKERS = (
    "nice to have", "nice-to-have", "preferred", "desirable", "desired",
    "bonus", "a plus", "advantageous", "would be great", "ideally",
    "not essential", "beneficial",
)
REQUIRED_MARKERS = (
    "requirement", "required", "must have", "must-have", "essential",
    "you will need", "what you'll need", "what you need", "qualification",
    "minimum", "mandatory",
)

# ---------------------------------------------------------------------
# Title / seniority
# ---------------------------------------------------------------------
# "associate" is deliberately absent. It sits at wildly different levels
# depending on context ("Associate Director" is senior, "Sales Associate"
# is entry) and it already caused a false-positive bug in the degree
# regex in extract_entities.py. A weak signal that is wrong half the time is worse than
# no signal, and no signal here just falls back to the default level.
SENIORITY_LADDER: dict[str, int] = {
    "intern": 0, "internship": 0, "trainee": 0, "placement": 0,
    "graduate": 1, "grad": 1, "junior": 1, "jnr": 1,
    "entry level": 1, "entry-level": 1, "assistant": 1,
    "mid": 2, "mid-level": 2, "midlevel": 2, "intermediate": 2,
    "senior": 3, "snr": 3, "sr": 3, "sr.": 3,
    "staff": 4, "lead": 4, "principal": 5, "head": 5,
    "director": 6, "vp": 7, "chief": 7,
}
DEFAULT_SENIORITY_LEVEL = 2  # assumed when nothing is detected

# Asymmetric on purpose. A candidate one rung below the advertised level
# is the failure mode a screen is built to catch; a candidate one rung
# above is a mild mismatch at worst and often still gets a call.
UNDERQUALIFIED_PENALTY_PER_STEP = 0.30
OVERQUALIFIED_PENALTY_PER_STEP = 0.08

TITLE_FAMILY_WEIGHT = 0.6
TITLE_SENIORITY_WEIGHT = 0.4

# Words stripped before comparing role families, so "Senior Data Analyst"
# and "Data Analyst" compare as the same family and the level difference
# is handled by the ladder instead of double-counted.
TITLE_NOISE_WORDS = frozenset(
    list(SENIORITY_LADDER)
    + ["the", "a", "an", "and", "of", "for", "to", "in", "at", "with",
       "role", "position", "job", "opportunity", "team", "full", "time",
       "part", "permanent", "contract", "hybrid", "remote", "onsite"]
)

# ---------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------
# Shortfall is punished superlinearly: 80% of the required years is still
# broadly fine, 30% is not, and a linear ratio treats those as
# proportionally different when they are qualitatively different.
EXPERIENCE_SHORTFALL_EXPONENT = 1.5

# A resume with no explicit "N years" claim is scored neutral, not zero.
# Absence of the phrase is a resume-writing gap, not evidence of zero
# experience -- most student and early-career resumes never state it.
# Gap analysis raises it as a suggestion instead of the score punishing it.
NO_YEARS_ON_RESUME_SCORE = 0.5

# Same reasoning for titles. Student and early-career resumes often have no
# job-title line at all (projects and coursework instead), and extract_titles
# returns nothing. Scoring that as a 0 title match zeroed 15% of every score
# for exactly the people most likely to use the tool; neutral plus a
# gap-analysis suggestion matches how missing years are handled.
NO_TITLE_ON_RESUME_SCORE = 0.5

# ---------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------
BM25_K1 = 1.5
BM25_B = 0.75
BM25_CORPUS_STATS_PATH = str(DATA_ROOT / "data/processed/bm25_corpus_stats.json")
BM25_MIN_TOKEN_LEN = 3
BM25_MAX_QUERY_TERMS = 60
# Query terms must appear in at least this many corpus resumes. A term no
# resume uses (company names, "work180", "udemy") gets the maximum IDF, so
# ranking by IDF alone filled the query with words no candidate could
# match -- and pushed out "sql" and "forecasting" on a data analyst JD.
BM25_MIN_QUERY_DF = 5

# ---------------------------------------------------------------------
# JD boilerplate
# ---------------------------------------------------------------------
# Benefits, "about us", privacy and EEO sections describe the employer,
# not the job. Left in, they dominate the BM25 query (rare words like
# "carers" and "parental" out-rank "sql") and drag the semantic score down
# (every benefits chunk is a JD chunk no resume covers). A heading that
# contains one of these switches to boilerplate until a content heading
# switches back.
JD_BOILERPLATE_HEADING_MARKERS = (
    "benefit", "perks", "why work", "why join", "why us", "what we offer",
    "what's in it", "in it for you", "about us", "about the company",
    "privacy", "accommodation", "how to apply", "rewards", "equal opportunit",
    "diversity", "inclusion", "employment type", "time type",
)
JD_CONTENT_HEADING_MARKERS = (
    "responsibilit", "requirement", "what you'll", "what you will", "you will",
    "you have", "you are", "bring", "skills", "experience", "the role",
    "looking for", "essentials", "day to day", "qualification", "about you",
    "competenc", "opportunity", "role purpose", "what you", "who are you",
    "success looks", "mission", "doing",
)
# EEO and privacy sentences often sit under no heading at all
JD_BOILERPLATE_LINE_PATTERN = (
    r"equal opportunit|regardless of|diverse backgrounds|underrepresented|"
    r"hiring decisions are never|reasonable accommodation|privacy policy|"
    r"agency submissions|committed to (?:fostering|equity|making the recruitment)"
)

# ---------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # must match vector(384) in schema.sql
CHUNK_TARGET_CHARS = 600
CHUNK_MIN_CHARS = 120

# Measured, not estimated. Across 268 real resume-posting matches the raw
# pooled MiniLM similarity ran 0.11 to 0.51: p5 0.19, median 0.32, p95
# 0.44. The original [0.25, 0.75] guess put the ceiling above anything
# that ever occurs, so the component could never exceed ~0.5, while a
# quarter of all pairs fell under the floor and clipped to exactly 0 --
# losing the distinction between "unrelated" and "very unrelated".
# Bounds now sit just outside the observed range (p2 to p95), which
# spreads the real distribution across most of [0, 1].
SEMANTIC_FLOOR = 0.15
SEMANTIC_CEILING = 0.45

# ---------------------------------------------------------------------
# Verdicts (0-100 scale, matching the NUMERIC(5,2) score columns)
# ---------------------------------------------------------------------
# Calibrated 24 Sep 2026 against 40 real postings labelled by the
# candidate (good / maybe / no) -- see docs/validation-results.md.
#
# The original 70 / 45 were placeholders set before any data existed, and
# they put every real posting in "likely reject", including roles the
# candidate rated a good fit. On the observed distribution, "good"
# postings score 32-50, "maybe" 22-39 and "no" 9-36.
#
# 37 is where "good" separates cleanly: 6 of 7 good postings clear it and
# none of the 23 "no" postings do. 30 keeps every good posting inside the
# borderline band; 9 of the "no" set land there too, which is the right
# side to err on for a band that means "worth a look".
#
# These are separation points on one resume and 40 postings, not an
# absolute standard. Scores are comparable between postings, not against
# some external notion of employability.
VERDICT_PASS_THRESHOLD = 37.0
VERDICT_BORDERLINE_THRESHOLD = 30.0

# Score deciles from the same 40-posting calibration run, used to express
# a score as a percentile against a fixed reference.
#
# The blend is honest but reads badly on its own: 100 would require
# matching every extracted skill, every distinctive keyword, the exact
# title and seniority, and near-identical semantics, which no real pair
# does. Good fits landed at 32-50, so "50/100" invites the reader to
# think "half marks" when it is in fact the top of the observed range.
#
# A fixed reference, not a running distribution over whatever happens to
# be in the database: percentiles that drift as postings are added would
# make two screenshots of the same pair disagree.
CALIBRATION_SCORE_DECILES = [9.4, 22.5, 24.9, 27.5, 28.2, 30.0, 32.0, 32.9, 36.3, 40.1, 50.2]
CALIBRATION_SET_SIZE = 40

# ---------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------
ESCO_RELATIONS_PATH = str(DATA_ROOT / "data/taxonomy/esco_occupation_skill_relations.csv")
ESCO_SKILLS_PATH = str(DATA_ROOT / "data/taxonomy/esco_skills.csv")
MAX_ADJACENT_SUGGESTIONS = 3  # per missing skill
# Two skills sharing a single ESCO occupation means little; the raw
# co-occurrence set linked Python to "3d lighting". Requiring the pair to
# turn up in at least this many occupations, and ranking by that count,
# leaves recognisable neighbours (Python -> C++, C#, Java).
MIN_ADJACENCY_CO_OCCURRENCES = 2