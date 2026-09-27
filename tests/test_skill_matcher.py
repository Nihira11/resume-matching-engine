"""
Skill matcher precedence and filtering. Built from in-memory taxonomy rows
and a blank spaCy pipeline, so no database and no model load.

Every case here is a real mismatch found scoring 13 real job postings.
"""
from __future__ import annotations

import spacy

from src.nlp.skill_matcher import SkillMatcher, build_term_maps

ROWS = [
    # (skill_id, skill_name, aliases, source)
    (1, "dies", ["patterns", "die"], "ESCO"),
    (2, "computer vision", ["TensorFlow", "tensorflow"], "ESCO"),
    (3, "TensorFlow", ["Tensorflow"], "curated"),
    (4, "SPARK", [], "ESCO"),                      # the Ada language
    (5, "Apache Spark", ["Spark", "PySpark"], "curated"),
    (6, "Python (computer programming)", ["Python"], "ESCO"),
    (7, "logistics", ["logistic", "transport"], "ESCO"),
    (8, "regression analysis", ["logistic regression"], "curated"),
    (9, "Microsoft Excel", ["Excel"], "curated"),
    (10, "Source (digital game creation systems)", ["Source"], "ESCO"),
]


def matcher():
    return SkillMatcher(spacy.blank("en"), rows=ROWS)


def skills_in(text: str) -> set[str]:
    m = matcher()
    return {r.skill_name for r in m.match(m.nlp(text))}


def test_generic_lowercase_esco_alias_is_dropped():
    insensitive, _ = build_term_maps(ROWS)
    assert "patterns" not in insensitive
    assert "dies" in insensitive  # ESCO skill names are never filtered


def test_capitalised_esco_alias_is_kept():
    assert "Python (computer programming)" in skills_in("Built pipelines in Python")


def test_curated_beats_esco_alias_for_same_term():
    assert skills_in("Trained models in TensorFlow") == {"TensorFlow"}


def test_case_sensitive_term_claims_lowercase_form_from_esco():
    # "Spark" is the curated tool; lowercase "spark" must not fall back to
    # ESCO's SPARK (Ada) either
    assert skills_in("ETL jobs in Spark") == {"Apache Spark"}
    assert skills_in("spark curiosity in the team") == set()


def test_case_sensitive_excel_ignores_the_verb():
    assert skills_in("Advanced Excel skills") == {"Microsoft Excel"}
    assert skills_in("You will excel in a fast team") == set()


def test_logistic_regression_is_not_logistics():
    assert skills_in("Fitted a logistic regression scorecard") == {"regression analysis"}


def test_open_source_is_not_a_game_engine():
    assert skills_in("Contributions to open-source projects") == set()


def test_matcher_only_needs_a_tokenizer():
    """The pipeline deliberately runs on spacy.blank('en'): a PhraseMatcher
    needs tokenisation, not tags, parses or NER. This fails if anything in
    the extraction path starts depending on a trained pipeline."""
    from src.nlp.extract_entities import get_nlp
    nlp = get_nlp()
    assert nlp.pipe_names == []
    assert "Python" in [s.matched_text for s in SkillMatcher(nlp, rows=ROWS).match(nlp("I use Python"))]


def test_multiword_skill_matches_across_a_line_break():
    """Resumes wrap phrases constantly. The old PhraseMatcher compared raw
    token sequences, so a newline between the words broke the match and
    "Supply\\nChain Management" scored as nothing. Whitespace tokens are
    skipped now, so the wrapped form matches the same skill."""
    assert skills_in("experience with logistic\nregression models") == {"regression analysis"}
    assert skills_in("Apache\nSpark pipelines") == {"Apache Spark"}


def test_line_break_does_not_relax_the_ambiguity_rules():
    """Skipping whitespace must not smuggle past the case-sensitive and
    precedence rules the matcher exists to enforce."""
    assert skills_in("you will\nexcel in this role") == set()
    assert skills_in("open-\nsource projects") == set()


def test_matcher_holds_no_per_pattern_documents():
    """The taxonomy expands to ~99k surface forms. Holding a spaCy Doc for
    each cost 313MB and was what OOM-killed a 1GB deployment. The index is
    plain strings; this fails if a Doc-per-pattern structure comes back."""
    m = matcher()
    assert isinstance(m._lower, dict)
    assert all(isinstance(k, str) for k in m._lower)
    assert not hasattr(m, "matcher")
