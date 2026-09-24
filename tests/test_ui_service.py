"""
UI service layer: the shaping between MatchScore and what the page renders.

No database and no models -- a MatchScore is built by hand and pushed
through the same formatter the app uses, so a field renamed in the engine
breaks a test rather than silently rendering blank in the browser.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from resume_matcher import service  # noqa: E402
from src.matching.score import MatchScore  # noqa: E402


def make_match(**overrides) -> MatchScore:
    breakdown = {
        "components": {"skill_overlap": 0.5},
        "dropped_components": ["experience"],
        "skills": {
            "matched_required": ["SQL", "Python (computer programming)"],
            "matched_preferred": ["Tableau"],
            "missing_required": ["Power BI"],
            "missing_preferred": ["Jira"],
        },
        "keyword": {"top_terms": [["sql", 3.1], ["forecasting", 2.4]], "matched_term_count": 9, "query_term_count": 60},
        "title": {"resume_states_no_title": True, "best_matching_title": None},
        "experience": {"score": None},
        "semantic": {"raw_similarity": 0.4, "weakest_jd_chunks": []},
        "gaps": [
            {"skill_id": 1, "skill_name": "Power BI", "is_required": True, "jd_mentions": 3, "adjacent_skills_you_have": ["Tableau"]},
        ],
        "suggestions": ["Add a title line."],
        "parsability_score": 75.0,
    }
    breakdown.update(overrides.pop("breakdown", {}))
    return MatchScore(
        resume_id=5, jd_id=1, final_score=40.7, verdict="likely_reject",
        component_scores={"skill_overlap": 0.444, "semantic": 0.432},
        weights_used={"skill_overlap": 0.444, "semantic": 0.222},
        dropped_components=["experience"], breakdown=breakdown, **overrides,
    )


def test_view_has_every_field_the_page_reads():
    view = service.to_view(make_match())
    required_keys = {
        "final_score", "verdict", "verdict_color", "components", "dropped",
        "matched_required", "matched_preferred", "missing_required", "missing_preferred",
        "gaps", "suggestions", "keyword_terms", "keyword_matched", "keyword_total",
        "parsability", "title_note", "experience_note",
    }
    assert required_keys <= set(view)


def test_components_sorted_by_contribution_not_raw_score():
    view = service.to_view(make_match())
    contributions = [c["contribution"] for c in view["components"]]
    assert contributions == sorted(contributions, reverse=True)
    assert view["components"][0]["label"] == "Skill overlap"


def test_component_rows_carry_weight_and_help_text():
    row = service.to_view(make_match())["components"][0]
    assert row["weight_pct"] == 44
    assert row["score"] == 44.4
    assert "ATS" in row["help"]


def test_dropped_components_are_labelled_for_humans():
    assert service.to_view(make_match())["dropped"] == ["Experience"]


def test_verdict_is_labelled_and_coloured():
    view = service.to_view(make_match())
    assert view["verdict"] == "Likely reject"
    assert view["verdict_color"] == "tomato"


def test_gap_rows_are_flat_primitives_for_the_table():
    gap = service.to_view(make_match())["gaps"][0]
    assert gap == {
        "skill_name": "Power BI", "is_required": True, "requirement": "Required",
        "mentions": 3, "adjacent": "Tableau",
    }


def test_title_note_explains_neutral_score():
    assert "neutral" in service.to_view(make_match())["title_note"]


def test_experience_note_explains_dropped_component():
    assert "no minimum" in service.to_view(make_match())["experience_note"]


def test_experience_note_reports_shortfall():
    match = make_match(breakdown={"experience": {"score": 0.4, "jd_min_years": 5, "shortfall_years": 2, "resume_states_no_years": False}})
    assert "2 year(s) short" in service.to_view(match)["experience_note"]


def test_verdict_caveat_names_the_calibrated_thresholds():
    from src.matching.config import (
        VERDICT_BORDERLINE_THRESHOLD,
        VERDICT_PASS_THRESHOLD,
    )
    assert f"{VERDICT_PASS_THRESHOLD:.0f}" in service.VERDICT_CAVEAT
    assert f"{VERDICT_BORDERLINE_THRESHOLD:.0f}" in service.VERDICT_CAVEAT
    # the caveat must keep saying what the number is worth
    assert "calibrated" in service.VERDICT_CAVEAT


def test_labels_disambiguate_duplicates():
    # rx.select keys on the label, so two postings with the same title and
    # company would otherwise collide in the dropdown
    rows = [
        {"id": 1, "label": "Business Analyst — Acme"},
        {"id": 2, "label": "Business Analyst — Acme"},
        {"id": 3, "label": "Data Analyst — Iress"},
    ]
    labels = [r["label"] for r in service._unique_labels(rows)]
    assert labels == ["Business Analyst — Acme (1)", "Business Analyst — Acme (2)", "Data Analyst — Iress"]
    assert len(set(labels)) == 3
