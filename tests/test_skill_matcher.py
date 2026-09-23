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
