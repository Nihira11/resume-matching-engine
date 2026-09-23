"""
The blend, and the only place a final number is produced.

Two rules the rest of the engine is built around:

  1. A component with no signal is DROPPED and the remaining weights are
     renormalised -- never scored as zero. A JD that states no minimum
     experience should not drag every candidate down; it should just stop
     contributing an opinion.

  2. Nothing is a black box. Every component score, the weights actually
     used, the matched and missing skills, the top BM25 terms and the gap
     analysis are persisted to match_results.score_breakdown so the UI
     can explain the number without recomputing anything.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from src.matching.config import (
    COMPONENT_WEIGHTS,
    VERDICT_BORDERLINE_THRESHOLD,
    VERDICT_PASS_THRESHOLD,
)
from src.matching.experience_match import ExperienceMatchResult
from src.matching.gap_analysis import GapAnalysisResult
from src.matching.bm25_scorer import BM25Result
from src.matching.profiles import JDProfile, ResumeProfile
from src.matching.semantic import SemanticResult
from src.matching.skill_overlap import SkillOverlapResult
from src.matching.title_match import TitleMatchResult
from src.utils.db import get_connection


@dataclass
class MatchScore:
    resume_id: int
    jd_id: int
    final_score: float                      # 0-100
    verdict: str
    component_scores: dict[str, float] = field(default_factory=dict)   # 0-1, present only
    weights_used: dict[str, float] = field(default_factory=dict)
    dropped_components: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)


def blend(component_scores: dict[str, float | None]) -> tuple[float, dict, list[str]]:
    """Weighted mean over components that produced a signal.

    Returns (score_0_to_1, weights_used, dropped_component_names).
    """
    present = {k: v for k, v in component_scores.items() if v is not None}
    dropped = [k for k, v in component_scores.items() if v is None]

    if not present:
        return 0.0, {}, dropped

    raw_weights = {k: COMPONENT_WEIGHTS[k] for k in present}
    total_weight = sum(raw_weights.values())
    weights = {k: w / total_weight for k, w in raw_weights.items()}

    score = sum(present[k] * weights[k] for k in present)
    return score, weights, dropped


def verdict_for(score_0_to_100: float) -> str:
    if score_0_to_100 >= VERDICT_PASS_THRESHOLD:
        return "likely_pass"
    if score_0_to_100 >= VERDICT_BORDERLINE_THRESHOLD:
        return "borderline"
    return "likely_reject"


def build_match_score(
    resume: ResumeProfile,
    jd: JDProfile,
    overlap: SkillOverlapResult,
    keyword: BM25Result,
    title: TitleMatchResult,
    experience: ExperienceMatchResult,
    semantic: SemanticResult,
    gaps: GapAnalysisResult,
) -> MatchScore:
    components = {
        "skill_overlap": overlap.score,
        "keyword_bm25": keyword.score,
        "title_seniority": title.score,
        "experience": experience.score,
        "semantic": semantic.score,
    }
    blended, weights, dropped = blend(components)
    final = round(blended * 100, 2)

    breakdown = {
        "components": {k: round(v, 4) for k, v in components.items() if v is not None},
        "dropped_components": dropped,
        "skills": {
            "matched_required": [jd.skill_names.get(i, str(i)) for i in overlap.matched_required],
            "matched_preferred": [jd.skill_names.get(i, str(i)) for i in overlap.matched_preferred],
            "missing_required": [jd.skill_names.get(i, str(i)) for i in overlap.missing_required],
            "missing_preferred": [jd.skill_names.get(i, str(i)) for i in overlap.missing_preferred],
        },
        "keyword": {
            "top_terms": [[t, round(c, 4)] for t, c in keyword.top_terms],
            "matched_term_count": keyword.matched_term_count,
            "query_term_count": keyword.query_term_count,
        },
        "title": {
            "family_score": title.family_score,
            "seniority_score": title.seniority_score,
            "jd_level": title.jd_level,
            "resume_level": title.resume_level,
            "best_matching_title": title.best_matching_title,
            "resume_states_no_title": title.resume_states_no_title,
        },
        "experience": asdict(experience),
        "semantic": {
            "raw_similarity": semantic.raw_similarity,
            "weakest_jd_chunks": semantic.weakest_jd_chunks,
        },
        "gaps": [asdict(g) for g in gaps.gaps],
        "suggestions": gaps.suggestions,
        # Not part of the score. ATS parsability is a separate axis by
        # design -- a resume can score 90 on content and still be shredded
        # by a real parser -- so it rides along in the breakdown for the
        # UI warnings panel rather than being folded into the blend.
        "parsability_score": resume.parsability_score,
    }

    return MatchScore(
        resume_id=resume.resume_id,
        jd_id=jd.jd_id,
        final_score=final,
        verdict=verdict_for(final),
        component_scores={k: v for k, v in components.items() if v is not None},
        weights_used=weights,
        dropped_components=dropped,
        breakdown=breakdown,
    )


def persist(match: MatchScore) -> int:
    def pct(key: str) -> float | None:
        value = match.component_scores.get(key)
        return round(value * 100, 2) if value is not None else None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO match_results (
            resume_id, jd_id,
            skill_overlap_score, keyword_score, semantic_score,
            title_seniority_score, experience_match_score, final_blended_score,
            matched_skills, missing_skills, verdict,
            score_breakdown, weights_used
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (resume_id, jd_id) DO UPDATE SET
            computed_at            = now(),
            skill_overlap_score    = EXCLUDED.skill_overlap_score,
            keyword_score          = EXCLUDED.keyword_score,
            semantic_score         = EXCLUDED.semantic_score,
            title_seniority_score  = EXCLUDED.title_seniority_score,
            experience_match_score = EXCLUDED.experience_match_score,
            final_blended_score    = EXCLUDED.final_blended_score,
            matched_skills         = EXCLUDED.matched_skills,
            missing_skills         = EXCLUDED.missing_skills,
            verdict                = EXCLUDED.verdict,
            score_breakdown        = EXCLUDED.score_breakdown,
            weights_used           = EXCLUDED.weights_used
        RETURNING match_id
        """,
        (
            match.resume_id,
            match.jd_id,
            pct("skill_overlap"),
            pct("keyword_bm25"),
            pct("semantic"),
            pct("title_seniority"),
            pct("experience"),
            match.final_score,
            match.breakdown["skills"]["matched_required"]
            + match.breakdown["skills"]["matched_preferred"],
            match.breakdown["skills"]["missing_required"]
            + match.breakdown["skills"]["missing_preferred"],
            match.verdict,
            json.dumps(match.breakdown, default=str),
            json.dumps(match.weights_used),
        ),
    )
    match_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return match_id