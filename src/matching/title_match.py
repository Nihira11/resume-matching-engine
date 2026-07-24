"""
Title match, split into two independent questions:

  1. role family  -- is this the same kind of job at all?
                     (data analyst vs data engineer vs product manager)
  2. seniority    -- is it the same rung of the ladder?

Kept separate because they fail differently and a user reading the
breakdown in the UI needs to know which one went wrong. "Right job,
wrong level" and "wrong job entirely" are very different pieces of advice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.matching.config import (
    DEFAULT_SENIORITY_LEVEL,
    OVERQUALIFIED_PENALTY_PER_STEP,
    SENIORITY_LADDER,
    TITLE_FAMILY_WEIGHT,
    TITLE_NOISE_WORDS,
    TITLE_SENIORITY_WEIGHT,
    UNDERQUALIFIED_PENALTY_PER_STEP,
)
from src.matching.profiles import JDProfile, ResumeProfile

_WORD_RE = re.compile(r"[a-z][a-z+#.\-]*")


@dataclass
class TitleMatchResult:
    score: float | None
    family_score: float | None = None
    seniority_score: float | None = None
    jd_level: int | None = None
    resume_level: int | None = None
    best_matching_title: str | None = None


def normalize_title(title: str) -> set[str]:
    """Lowercase content words, with seniority and boilerplate stripped.

    Seniority words are removed here on purpose so that "Senior Data
    Analyst" and "Data Analyst" register as the same family -- the level
    difference is the seniority component's job, and leaving the words in
    would count the same mismatch twice.
    """
    words = _WORD_RE.findall((title or "").lower())
    return {w for w in words if w not in TITLE_NOISE_WORDS and len(w) > 1}


def detect_seniority(text: str) -> int | None:
    """Lowest ladder level mentioned, or None.

    Lowest rather than highest because JD text routinely name-drops levels
    it is not advertising ("reporting to the Director", "mentored by
    senior engineers"). The advertised level is nearly always the most
    junior one named.
    """
    lowered = f" {(text or '').lower()} "
    found = [
        level for term, level in SENIORITY_LADDER.items()
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered)
    ]
    return min(found) if found else None


def score_title_match(resume: ResumeProfile, jd: JDProfile) -> TitleMatchResult:
    jd_tokens = normalize_title(jd.title)
    if not jd_tokens:
        return TitleMatchResult(score=None)

    # family
    # Asymmetric containment, not Jaccard. extract_titles keeps
    # the whole line a title keyword appeared on (up to 80 chars), so
    # resume "titles" are often "Data Analyst | Acme Corp | 2023-2024".
    # Jaccard would punish that extra context even though the match is
    # perfect. Dividing by the JD token count only asks the question that
    # matters: how much of the advertised role does this line cover?
    best_family = 0.0
    best_title = None
    for title in resume.titles:
        tokens = normalize_title(title)
        if not tokens:
            continue
        overlap = len(jd_tokens & tokens) / len(jd_tokens)
        if overlap > best_family:
            best_family = overlap
            best_title = title

    # seniority
    jd_level = detect_seniority(jd.seniority_level or "")
    if jd_level is None:
        jd_level = detect_seniority(jd.title)
    if jd_level is None:
        jd_level = detect_seniority(jd.cleaned_text)

    resume_level = detect_seniority(" ".join(resume.titles))

    if jd_level is None or resume_level is None:
        # Nothing detectable on one side. Fall back to family alone rather
        # than inventing a level and scoring against it.
        seniority_score = None
        combined = best_family
    else:
        steps = resume_level - jd_level
        if steps < 0:
            penalty = abs(steps) * UNDERQUALIFIED_PENALTY_PER_STEP
        else:
            penalty = steps * OVERQUALIFIED_PENALTY_PER_STEP
        seniority_score = max(0.0, 1.0 - penalty)
        combined = (
            TITLE_FAMILY_WEIGHT * best_family
            + TITLE_SENIORITY_WEIGHT * seniority_score
        )

    return TitleMatchResult(
        score=combined,
        family_score=best_family,
        seniority_score=seniority_score,
        jd_level=jd_level,
        resume_level=resume_level if resume_level is not None else DEFAULT_SENIORITY_LEVEL,
        best_matching_title=best_title,
    )