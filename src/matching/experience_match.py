"""
Years-of-experience match.

Three cases, and the two edge cases matter more than the main one:

  JD states no minimum      -> no signal, component dropped from the blend
                               and the remaining weights renormalised.
                               Scoring 0 would punish every resume against
                               a vaguely written posting.

  Resume states no years    -> neutral score, plus a gap-analysis flag.
                               Most student and early-career resumes never
                               write "N years of experience" anywhere. That
                               is a resume-writing gap worth telling the
                               user about, not evidence of zero experience,
                               and scoring it as zero would make the tool
                               useless for exactly the people most likely
                               to use it.

  Both present              -> ratio with a superlinear shortfall curve.

Overqualification is not penalised. Real ATS keyword screens do not filter
on "too much experience"; human reviewers sometimes do, but that is not
what this tool claims to model.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.matching.config import (
    EXPERIENCE_SHORTFALL_EXPONENT,
    NO_YEARS_ON_RESUME_SCORE,
)
from src.matching.profiles import JDProfile, ResumeProfile


@dataclass
class ExperienceMatchResult:
    score: float | None
    jd_min_years: int | None = None
    resume_years: int | None = None
    shortfall_years: int | None = None
    resume_states_no_years: bool = False


def score_experience(resume: ResumeProfile, jd: JDProfile) -> ExperienceMatchResult:
    jd_min = jd.min_years
    resume_years = resume.years_experience

    if jd_min is None:
        return ExperienceMatchResult(score=None, resume_years=resume_years)

    if resume_years is None:
        return ExperienceMatchResult(
            score=NO_YEARS_ON_RESUME_SCORE,
            jd_min_years=jd_min,
            resume_years=None,
            resume_states_no_years=True,
        )

    if jd_min <= 0:
        return ExperienceMatchResult(
            score=1.0, jd_min_years=jd_min, resume_years=resume_years
        )

    ratio = resume_years / jd_min
    if ratio >= 1.0:
        score = 1.0
        shortfall = 0
    else:
        # ratio ** 1.5: 0.8 of the requirement still scores 0.72, 0.3
        # scores 0.16. A linear ratio treats those as proportionally
        # different when they are qualitatively different -- one is a
        # rounding error on a CV, the other is a different career stage.
        score = ratio ** EXPERIENCE_SHORTFALL_EXPONENT
        shortfall = jd_min - resume_years

    return ExperienceMatchResult(
        score=score,
        jd_min_years=jd_min,
        resume_years=resume_years,
        shortfall_years=shortfall,
    )