"""
Matching engine tests.

These assert ORDERING, not exact values: a perfect pair must outscore a
partial pair must outscore a mismatch. Calibration rewrites the weights in
config.py, and any test asserting `score == 73.4` breaks the moment that
happens – which trains you to edit the test until it passes, which is
worse than having no test. Monotonicity survives recalibration and is the
property actually being relied on.

Runs with no database and no spaCy/sentence-transformers model load: every
scorer is a pure function over the profile dataclasses.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.matching.bm25_scorer import BM25Scorer, tokenize
from src.matching.experience_match import score_experience
from src.matching.profiles import (
    JDProfile,
    ResumeProfile,
    extract_jd_min_years,
    split_requirement_sections,
)
from src.matching.score import blend, verdict_for
from src.matching.semantic import score_semantic
from src.matching.skill_overlap import score_skill_overlap
from src.matching.title_match import detect_seniority, normalize_title, score_title_match

PYTHON, SQL, SPARK, AIRFLOW, TABLEAU = 1, 2, 3, 4, 5
NAMES = {
    PYTHON: "Python", SQL: "SQL", SPARK: "Apache Spark",
    AIRFLOW: "Apache Airflow", TABLEAU: "Tableau",
}


def make_jd(required, preferred=(), **kwargs) -> JDProfile:
    return JDProfile(
        jd_id=1,
        required_skill_ids=set(required),
        preferred_skill_ids=set(preferred),
        skill_names={k: v for k, v in NAMES.items()},
        **kwargs,
    )


def make_resume(skills, **kwargs) -> ResumeProfile:
    return ResumeProfile(
        resume_id=1,
        skill_ids=set(skills),
        skill_names={k: NAMES[k] for k in skills},
        **kwargs,
    )


# ---------------------------------------------------------------------
# Skill overlap
# ---------------------------------------------------------------------
class TestSkillOverlap:
    def test_ordering_perfect_partial_none(self):
        jd = make_jd([PYTHON, SQL, SPARK])
        perfect = score_skill_overlap(make_resume([PYTHON, SQL, SPARK]), jd).score
        partial = score_skill_overlap(make_resume([PYTHON, SQL]), jd).score
        none = score_skill_overlap(make_resume([TABLEAU]), jd).score
        assert perfect > partial > none
        assert perfect == pytest.approx(1.0)
        assert none == pytest.approx(0.0)

    def test_required_outweighs_preferred(self):
        jd = make_jd(required=[PYTHON], preferred=[SQL])
        has_required = score_skill_overlap(make_resume([PYTHON]), jd).score
        has_preferred = score_skill_overlap(make_resume([SQL]), jd).score
        assert has_required > has_preferred

    def test_skill_in_both_lists_counts_as_required(self):
        jd = make_jd(required=[PYTHON], preferred=[PYTHON])
        result = score_skill_overlap(make_resume([PYTHON]), jd)
        assert result.score == pytest.approx(1.0)
        assert result.matched_preferred == []

    def test_no_jd_skills_returns_none_not_zero(self):
        # A JD with no extractable skills says nothing about the resume.
        # None means "drop this component"; 0.0 would mean "this resume
        # is bad", which is a claim the data does not support.
        assert score_skill_overlap(make_resume([PYTHON]), make_jd([])).score is None


# ---------------------------------------------------------------------
# Title / seniority
# ---------------------------------------------------------------------
class TestTitleMatch:
    def test_seniority_stripped_from_family_comparison(self):
        assert normalize_title("Senior Data Analyst") == normalize_title("Data Analyst")

    def test_detect_seniority_takes_lowest_mentioned(self):
        # JDs name-drop levels they are not advertising. "Junior analyst
        # reporting to the Director" is a junior role.
        assert detect_seniority("Junior Analyst reporting to the Director") == 1

    def test_associate_is_not_a_seniority_signal(self):
        assert detect_seniority("Associate Consultant") is None

    def test_ordering_same_role_beats_different_role(self):
        jd = make_jd([], title="Data Analyst")
        same = score_title_match(make_resume([], titles=["Data Analyst | Acme"]), jd).score
        different = score_title_match(make_resume([], titles=["Chef | Acme"]), jd).score
        assert same > different

    def test_underqualified_penalised_more_than_overqualified(self):
        jd = make_jd([], title="Senior Data Analyst")
        junior = score_title_match(make_resume([], titles=["Junior Data Analyst"]), jd).score
        lead = score_title_match(make_resume([], titles=["Lead Data Analyst"]), jd).score
        assert lead > junior

    def test_long_resume_title_line_not_punished(self):
        # extract_titles keeps the whole line a title keyword appeared on, so
        # scorer must not penalise the extra context around the match.
        jd = make_jd([], title="Data Analyst")
        clean = score_title_match(make_resume([], titles=["Data Analyst"]), jd)
        noisy = score_title_match(
            make_resume([], titles=["Data Analyst | Acme Corp | Jan 2023 - Present"]), jd
        )
        assert noisy.family_score == pytest.approx(clean.family_score)


# ---------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------
class TestExperienceMatch:
    def test_no_jd_minimum_returns_none(self):
        assert score_experience(make_resume([], years_experience=3), make_jd([])).score is None

    def test_missing_resume_years_is_neutral_not_zero(self):
        result = score_experience(make_resume([]), make_jd([], min_years=3))
        assert result.score == pytest.approx(0.5)
        assert result.resume_states_no_years is True

    def test_ordering_by_shortfall(self):
        jd = make_jd([], min_years=5)
        meets = score_experience(make_resume([], years_experience=5), jd).score
        close = score_experience(make_resume([], years_experience=4), jd).score
        far = score_experience(make_resume([], years_experience=1), jd).score
        assert meets > close > far

    def test_overqualified_not_penalised(self):
        jd = make_jd([], min_years=3)
        assert score_experience(make_resume([], years_experience=10), jd).score == pytest.approx(1.0)


# ---------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------
class TestBM25:
    @staticmethod
    def scorer() -> BM25Scorer:
        # 1000 docs: "python" is everywhere, "airflow" is rare. IDF should
        # make the rare term dominate.
        return BM25Scorer(
            n_docs=1000,
            avgdl=300.0,
            df={"python": 900, "sql": 850, "airflow": 12, "experience": 990},
        )

    def test_rare_term_has_higher_idf(self):
        scorer = self.scorer()
        assert scorer.idf("airflow") > scorer.idf("python")

    def test_idf_never_negative(self):
        # Unfloored BM25 IDF goes negative past 50% document frequency,
        # which would penalise a resume for containing a common word.
        assert self.scorer().idf("experience") > 0

    def test_matching_rare_term_beats_matching_common_term(self):
        scorer = self.scorer()
        jd = "airflow python"
        rare = scorer.score("airflow airflow orchestration", jd).score
        common = scorer.score("python python programming", jd).score
        assert rare > common

    def test_score_bounded_and_ordered(self):
        scorer = self.scorer()
        jd = "python sql airflow"
        full = scorer.score("python sql airflow", jd).score
        partial = scorer.score("python sql", jd).score
        empty = scorer.score("chef catering hospitality", jd).score
        assert 0.0 <= empty < partial < full <= 1.0

    def test_tokenizer_keeps_technical_punctuation(self):
        tokens = tokenize("C++ and Node.js and scikit-learn")
        assert "c++" in tokens
        assert "node.js" in tokens
        assert "scikit-learn" in tokens


# ---------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------
class TestSemantic:
    def test_identical_chunks_score_high(self):
        vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
        assert score_semantic(vectors, vectors).score == pytest.approx(1.0)

    def test_orthogonal_chunks_score_zero(self):
        assert score_semantic(
            np.array([[1.0, 0.0]]), np.array([[0.0, 1.0]])
        ).score == pytest.approx(0.0)

    def test_empty_side_returns_none(self):
        assert score_semantic(np.zeros((0, 0)), np.array([[1.0, 0.0]])).score is None

    def test_pooling_is_jd_directed(self):
        # An extra irrelevant resume section must not lower the score --
        # the question is JD coverage, not resume purity.
        jd = np.array([[1.0, 0.0]])
        focused = score_semantic(np.array([[1.0, 0.0]]), jd).score
        padded = score_semantic(np.array([[1.0, 0.0], [0.0, 1.0]]), jd).score
        assert padded == pytest.approx(focused)


# ---------------------------------------------------------------------
# Blend
# ---------------------------------------------------------------------
class TestBlend:
    def test_missing_components_renormalise_rather_than_zero(self):
        full = blend({"skill_overlap": 0.8, "keyword_bm25": 0.8,
                      "title_seniority": 0.8, "experience": 0.8, "semantic": 0.8})[0]
        partial = blend({"skill_overlap": 0.8, "keyword_bm25": 0.8,
                         "title_seniority": 0.8, "experience": None, "semantic": None})[0]
        assert full == pytest.approx(partial)

    def test_weights_sum_to_one_after_dropping(self):
        _, weights, dropped = blend(
            {"skill_overlap": 0.5, "keyword_bm25": None, "title_seniority": 0.5,
             "experience": None, "semantic": 0.5}
        )
        assert sum(weights.values()) == pytest.approx(1.0)
        assert set(dropped) == {"keyword_bm25", "experience"}

    def test_skill_overlap_is_the_heaviest_component(self):
        _, weights, _ = blend(
            {"skill_overlap": 0.5, "keyword_bm25": 0.5, "title_seniority": 0.5,
             "experience": 0.5, "semantic": 0.5}
        )
        assert weights["skill_overlap"] == max(weights.values())

    def test_all_components_missing_does_not_crash(self):
        score, weights, _ = blend({k: None for k in
                                   ["skill_overlap", "keyword_bm25", "title_seniority",
                                    "experience", "semantic"]})
        assert score == 0.0 and weights == {}

    def test_verdict_ordering(self):
        assert verdict_for(95) == "likely_pass"
        assert verdict_for(55) == "borderline"
        assert verdict_for(10) == "likely_reject"


# ---------------------------------------------------------------------
# Required vs preferred
# ---------------------------------------------------------------------
class TestRequirementSections:
    def test_nice_to_have_heading_flips_mode(self):
        blocks = split_requirement_sections(
            "Requirements:\nStrong Python\nAdvanced SQL\n"
            "Nice to have:\nExposure to Spark\n"
        )
        required = "\n".join(b for b, req in blocks if req).lower()
        preferred = "\n".join(b for b, req in blocks if not req).lower()
        assert "python" in required
        assert "spark" in preferred
        assert "spark" not in required

    def test_text_before_any_heading_defaults_to_required(self):
        blocks = split_requirement_sections("We need someone with strong SQL.\n")
        assert all(req for _, req in blocks)


# ---------------------------------------------------------------------
# JD years re-extraction
# ---------------------------------------------------------------------
class TestJDMinYears:
    def test_range_takes_lower_bound(self):
        # The whole reason this exists. The extractor stores "3-5 years" as 5,
        # discarding the 3 at extraction time, so the advertised bar is
        # unrecoverable from jd_entities and has to be re-read from text.
        assert extract_jd_min_years("We need 3-5 years experience.") == 3

    def test_en_dash_range(self):
        assert extract_jd_min_years("3–5 years of experience") == 3

    def test_plus_notation(self):
        assert extract_jd_min_years("5+ years of Python") == 5

    def test_minimum_cue_wins_over_smaller_incidental_figure(self):
        text = (
            "Our team has been running for 2 years.\n"
            "Requirements:\nMinimum 4 years of commercial SQL.\n"
        )
        assert extract_jd_min_years(text) == 4

    def test_falls_back_to_smallest_when_no_cue(self):
        assert extract_jd_min_years("5 years Python, 2 years Spark") == 2

    def test_no_years_returns_none(self):
        assert extract_jd_min_years("Great team, flexible hours.") is None

# ---------------------------------------------------------------------
# Regressions found by scoring a real resume against 13 real postings.
# Every one of these passed the ordering tests above and still made the
# engine return "likely_reject" for every posting.
# ---------------------------------------------------------------------
class TestTitleWithNoResumeTitles:
    def test_no_resume_titles_is_neutral_not_zero(self):
        # student resumes often have no job-title line; that was scored
        # as a 0 title match and zeroed 15% of every score
        jd = make_jd([], title="Associate Data Scientist")
        result = score_title_match(make_resume([], titles=[]), jd)
        assert result.resume_states_no_title
        mismatch = score_title_match(make_resume([], titles=["Chef"]), jd).score
        match = score_title_match(make_resume([], titles=["Data Scientist"]), jd).score
        assert mismatch < result.score < match

    def test_gap_analysis_suggests_adding_a_title(self):
        from src.matching.gap_analysis import analyse_gaps
        resume, jd = make_resume([PYTHON]), make_jd([PYTHON])
        overlap = score_skill_overlap(resume, jd)
        gaps = analyse_gaps(resume, jd, overlap, resume_states_no_title=True)
        assert any("title" in s.lower() for s in gaps.suggestions)


class TestBM25RealPostings:
    def scorer(self):
        return BM25Scorer(
            n_docs=1000,
            avgdl=300.0,
            df={"sql": 300, "forecasting": 200, "insights": 400,
                "parental": 6, "carers": 5, "iress": 0},
        )

    def test_tokenizer_strips_sentence_final_punctuation(self):
        tokens = tokenize("Deliver insights. Use Node.js and scikit-learn.")
        assert "insights" in tokens and "insights." not in tokens
        assert "node.js" in tokens and "scikit-learn" in tokens

    def test_benefits_section_excluded_from_query(self):
        jd = (
            "Data Analyst\n"
            "What You Will Bring\n"
            "SQL and forecasting experience.\n"
            "Why work with us?\n"
            "Paid parental leave for carers.\n"
        )
        query = self.scorer().build_query(jd)
        assert "sql" in query and "forecasting" in query
        assert "parental" not in query and "carers" not in query

    def test_terms_no_resume_uses_are_excluded(self):
        # df=0 gives the maximum IDF, so employer names used to top the query
        query = self.scorer().build_query("Iress needs SQL and forecasting.")
        assert "iress" not in query
        assert "sql" in query


class TestJDBoilerplate:
    def test_strips_benefits_about_and_eeo(self):
        from src.matching.jd_sections import strip_boilerplate
        jd = (
            "Associate Data Scientist\n"
            "You have:\n"
            "Experience with SQL and Python.\n"
            "About Mistral\n"
            "We build frontier models.\n"
            "What You Will Do\n"
            "Deploy models.\n"
            "Perks & Benefits\n"
            "Equity and a MacBook.\n"
            "We are an equal opportunities employer.\n"
        )
        kept = strip_boilerplate(jd)
        assert "SQL and Python" in kept and "Deploy models" in kept
        assert "frontier" not in kept and "MacBook" not in kept
        assert "equal opportunities" not in kept

    def test_about_the_role_is_content(self):
        from src.matching.jd_sections import heading_kind
        assert heading_kind("About The Role") == "content"
        assert heading_kind("About you:") == "content"
        assert heading_kind("About GloBird Energy") == "boilerplate"
        assert heading_kind("Why RBA?") == "boilerplate"

    def test_all_boilerplate_falls_back_to_original(self):
        from src.matching.jd_sections import strip_boilerplate
        jd = "Benefits\nFree lunch."
        assert strip_boilerplate(jd) == jd


class TestChunking:
    def test_pdf_text_without_blank_lines_is_split(self):
        # PDF extraction gives no blank lines; the whole resume became one
        # chunk and MiniLM only read its first 256 tokens
        from src.matching.config import CHUNK_TARGET_CHARS
        from src.matching.embeddings import chunk_text
        lines = [f"Project {i}: built an XGBoost model on {i * 1000} rows of data" for i in range(60)]
        chunks = chunk_text("\n".join(lines))
        assert len(chunks) > 1
        assert all(len(c) <= CHUNK_TARGET_CHARS for c in chunks)
        assert "Project 59" in chunks[-1]


class TestJDMinYearsRealPostings:
    def test_or_more(self):
        assert extract_jd_min_years("5 or more years of experience with requirements") == 5

    def test_decimal_not_misread(self):
        # the "8" in "6.8" used to match on its own
        assert extract_jd_min_years("6.8 years of experience") != 8
