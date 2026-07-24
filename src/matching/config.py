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

# ---------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------
BM25_K1 = 1.5
BM25_B = 0.75
BM25_CORPUS_STATS_PATH = "data/processed/bm25_corpus_stats.json"
BM25_MIN_TOKEN_LEN = 3
BM25_MAX_QUERY_TERMS = 120  # highest-IDF terms only; the tail is noise

# ---------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # must match vector(384) in schema.sql
CHUNK_TARGET_CHARS = 600
CHUNK_MIN_CHARS = 120

# MiniLM cosine similarity between two pieces of professional English
# almost never leaves roughly [0.25, 0.75], so raw cosine compresses every
# pair into a narrow band and the component stops discriminating. Rescaled
# to spread that band across [0, 1]. These bounds are the most obviously
# provisional numbers in this file -- calibration should set them from the
# observed distribution over real postings rather than this estimate.
SEMANTIC_FLOOR = 0.25
SEMANTIC_CEILING = 0.75

# ---------------------------------------------------------------------
# Verdicts (0-100 scale, matching the NUMERIC(5,2) score columns)
# ---------------------------------------------------------------------
VERDICT_PASS_THRESHOLD = 70.0
VERDICT_BORDERLINE_THRESHOLD = 45.0

# ---------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------
ESCO_RELATIONS_PATH = "data/taxonomy/esco_occupation_skill_relations.csv"
ESCO_SKILLS_PATH = "data/taxonomy/esco_skills.csv"
MAX_ADJACENT_SUGGESTIONS = 3  # per missing skill