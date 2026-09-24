"""
Hard skill overlap -- the ATS-mirroring core of the blend, and the only
component whose output a user can check by eye.

Set arithmetic over ESCO skill_ids rather than surface strings, so
"Python" on the resume and "Python (computer programming)" in the JD
unify through the taxonomy instead of missing each other.

Worth noting against the known extraction limitation (common English words
colliding with ESCO terms -- "plan", "design", "call"): intersection
suppresses a good deal of that noise on its own. A spurious "plan" match
in the resume only inflates this score if the JD *independently* produced
the same spurious match, and two independent false positives colliding on
the same term is much rarer than either one alone. The limitation is real
and still documented, but it degrades this component far less than the
raw extraction precision number suggests.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.matching.config import (
    PREFERRED_SKILL_WEIGHT,
    REQUIRED_SKILL_WEIGHT,
    SKILL_OVERLAP_MIN_EVIDENCE,
)
from src.matching.profiles import JDProfile, ResumeProfile


@dataclass
class SkillOverlapResult:
    score: float | None  # None => JD listed no skills, component has no signal
    matched_required: list[int] = field(default_factory=list)
    matched_preferred: list[int] = field(default_factory=list)
    missing_required: list[int] = field(default_factory=list)
    missing_preferred: list[int] = field(default_factory=list)

    @property
    def matched_ids(self) -> list[int]:
        return self.matched_required + self.matched_preferred

    @property
    def missing_ids(self) -> list[int]:
        return self.missing_required + self.missing_preferred


def score_skill_overlap(resume: ResumeProfile, jd: JDProfile) -> SkillOverlapResult:
    required = jd.required_skill_ids
    preferred = jd.preferred_skill_ids - required  # required wins on overlap

    if not required and not preferred:
        # No extractable skills in the JD at all. Returning 0.0 here would
        # mean every resume scores badly against a vaguely written posting,
        # which says nothing about the resume. score.py drops the component
        # and renormalises the remaining weights instead.
        return SkillOverlapResult(score=None)

    matched_required = sorted(required & resume.skill_ids)
    matched_preferred = sorted(preferred & resume.skill_ids)

    earned = (
        len(matched_required) * REQUIRED_SKILL_WEIGHT
        + len(matched_preferred) * PREFERRED_SKILL_WEIGHT
    )
    available = (
        len(required) * REQUIRED_SKILL_WEIGHT
        + len(preferred) * PREFERRED_SKILL_WEIGHT
    )

    # Denominator floored at SKILL_OVERLAP_MIN_EVIDENCE: a thin posting is
    # weak evidence, not strong evidence of a match. See config.py for the
    # false positive that motivated it.
    denominator = max(available, SKILL_OVERLAP_MIN_EVIDENCE)
    return SkillOverlapResult(
        score=earned / denominator if available else None,
        matched_required=matched_required,
        matched_preferred=matched_preferred,
        missing_required=sorted(required - resume.skill_ids),
        missing_preferred=sorted(preferred - resume.skill_ids),
    )