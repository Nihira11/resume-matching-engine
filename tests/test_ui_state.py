"""
UI interaction logic: the state handlers the page binds to.

The pipeline is stubbed, so these run with no database, no spaCy and no
embedding model. What they cover is the wiring that a browser click
exercises -- selection, validation, busy/error handling, and the mapping
from a scored result onto the typed vars the page renders.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

from resume_matcher import service, state as state_module  # noqa: E402
from resume_matcher.state import AppState  # noqa: E402

VIEW = {
    "final_score": 40.7, "verdict": "Likely reject", "verdict_color": "tomato",
    "fit_band": "Strong fit", "percentile_label": "top 5% of the 40-posting calibration set",
    "components": [{"key": "skill_overlap", "label": "Skill overlap", "help": "h", "score": 44.4, "weight_pct": 44, "contribution": 19.7}],
    "dropped": ["Experience"],
    "matched_required": ["SQL"], "matched_preferred": [], "missing_required": ["Power BI"], "missing_preferred": [],
    "gaps": [{"skill_name": "Power BI", "requirement": "Required", "is_required": True, "mentions": 3, "adjacent": "Tableau"}],
    "suggestions": ["Add a title line."], "keyword_terms": ["sql"], "keyword_matched": 9, "keyword_total": 60,
    "parsability": 75.0, "title_note": "note", "experience_note": "exp note",
}


def new_state() -> AppState:
    s = AppState(_reflex_internal_init=True)
    s.resumes = [{"id": 5, "label": "#5 · mine.pdf"}, {"id": 4, "label": "#4 · other.pdf"}]
    s.jds = [{"id": 1, "label": "#1 · Data Analyst — Iress"}, {"id": 2, "label": "#2 · BA"}]
    s.resume_id, s.jd_id = 5, 1
    return s


def drain(state: AppState, handler_name: str, *args):
    """Run a background handler to completion.

    Reflex refuses a direct call on a background handler (it normally has
    to be scheduled by the server), so the underlying function is invoked
    against the state instance. `async with self` works fine outside the
    event loop the server would provide.
    """
    fn = getattr(type(state), handler_name).fn
    asyncio.run(fn(state, *args))


def test_selecting_a_posting_clears_the_previous_result():
    s = new_state()
    s._apply_view(VIEW)
    assert s.has_result
    s.select_jd("#2 · BA")
    assert s.jd_id == 2 and not s.has_result


def test_selecting_a_resume_clears_result_and_leaderboard():
    s = new_state()
    s._apply_view(VIEW)
    s.leaderboard = [state_module.BoardRow(jd_id=1, title="x")]
    s.select_resume("#4 · other.pdf")
    assert s.resume_id == 4 and not s.has_result and s.leaderboard == []


def test_apply_view_fills_every_var_the_page_renders():
    s = new_state()
    s._apply_view(VIEW)
    assert s.final_score == 40.7
    assert s.components[0].label == "Skill overlap" and s.components[0].weight_pct == 44
    assert s.gaps[0].skill_name == "Power BI" and s.gaps[0].mentions == 3
    assert s.missing_required == ["Power BI"] and s.keyword_matched == 9
    assert s.title_note == "note" and s.experience_note == "exp note"
    assert s.fit_band == "Strong fit" and "calibration set" in s.percentile_label


def test_score_button_disabled_until_both_sides_chosen():
    s = new_state()
    assert s.ready_to_score
    s.jd_id = 0
    assert not s.ready_to_score
    s.jd_id, s.busy = 1, True
    assert not s.ready_to_score  # and while a run is in flight


def test_short_paste_is_rejected_without_touching_the_pipeline(monkeypatch):
    s = new_state()
    called = []
    monkeypatch.setattr(service, "add_jd", lambda *a, **k: called.append(a))
    s.jd_text = "too short"
    drain(s, "save_pasted_jd")
    assert called == []
    assert "whole posting" in s.error and not s.busy


def test_saving_a_posting_selects_it_and_resets_the_form(monkeypatch):
    s = new_state()
    monkeypatch.setattr(service, "add_jd", lambda *a, **k: 99)
    monkeypatch.setattr(service, "list_jds", lambda: [{"id": 99, "label": "#99 · New"}])
    s.jd_text = "x" * 250
    s.jd_title = "Data Scientist"
    drain(s, "save_pasted_jd")
    assert s.jd_id == 99 and s.jd_text == "" and s.jd_mode == "Saved postings"
    assert not s.busy and s.error == ""


def test_scoring_failure_surfaces_the_error_and_clears_busy(monkeypatch):
    s = new_state()
    def boom(*a, **k):
        raise RuntimeError("database is asleep")
    monkeypatch.setattr(service, "score_pair", boom)
    drain(s, "run_match")
    assert "database is asleep" in s.error and not s.busy and s.status == ""


def test_successful_scoring_populates_the_result(monkeypatch):
    s = new_state()
    monkeypatch.setattr(service, "score_pair", lambda *a, **k: VIEW)
    drain(s, "run_match")
    assert s.has_result and s.final_score == 40.7 and not s.busy


def board_row(jd_id, title, score):
    return {"jd_id": jd_id, "title": title, "company": "Co", "score": score,
            "verdict": "Likely reject", "verdict_color": "tomato", "matched": 8, "missing": 10}


def test_leaderboard_rows_are_typed_and_sorted(monkeypatch):
    s = new_state()
    scores = {1: 12.0, 2: 40.7}
    monkeypatch.setattr(service, "board_row",
                        lambda rid, jd: board_row(jd["id"], jd["label"], scores[jd["id"]]))
    drain(s, "run_leaderboard")
    # highest first, regardless of the order postings were scored in
    assert [r.score for r in s.leaderboard] == [40.7, 12.0]
    assert s.leaderboard[0].title.startswith("#2")
    assert not s.busy and s.status == ""


def test_leaderboard_reports_which_posting_failed(monkeypatch):
    s = new_state()
    def boom(rid, jd):
        raise RuntimeError("timeout")
    monkeypatch.setattr(service, "board_row", boom)
    drain(s, "run_leaderboard")
    assert "Ranking failed" in s.error and "#1" in s.error and not s.busy


def test_upload_rejects_a_non_resume_file():
    s = new_state()
    class FakeUpload:
        name = "notes.txt"
        async def read(self):
            return b""
    asyncio.run(s.handle_resume_upload([FakeUpload()]))
    assert ".pdf" in s.error


def test_segmented_control_accepts_list_or_str():
    s = new_state()
    s.set_jd_mode(["Paste new"])
    assert s.jd_mode == "Paste new"
    s.set_jd_mode("Saved postings")
    assert s.jd_mode == "Saved postings"


def test_page_load_fills_the_parsability_panel(monkeypatch):
    # regression: the summary used to be fetched by a chained background
    # event, whose delta could land after the browser reconnected -- the
    # panel then sat at 0/100 with "0 skill mentions" for a parsed resume
    s = AppState(_reflex_internal_init=True)
    monkeypatch.setattr(service, "list_resumes", lambda: [{"id": 5, "label": "#5 · mine.pdf"}])
    monkeypatch.setattr(service, "list_jds", lambda: [{"id": 1, "label": "#1 · DA", "title": "DA", "company": "Iress"}])
    monkeypatch.setattr(service, "resume_summary", lambda rid: {
        "file_name": "mine.pdf", "parsability": 75.0, "skills": 93, "flags": ["table detected"]})
    drain(s, "load_catalogues")
    assert s.resume_id == 5 and s.jd_id == 1
    assert s.parsability_score == 75.0 and s.resume_skill_count == 93
    assert s.parsability_flags == ["table detected"]


def test_stale_summary_does_not_overwrite_a_newer_selection(monkeypatch):
    s = new_state()
    monkeypatch.setattr(service, "resume_summary", lambda rid: {"file_name": "old.pdf", "parsability": 10.0})
    s.resume_id = 4                      # selection moved while in flight
    asyncio.run(s._load_summary(5))      # summary for the old resume lands late
    assert s.parsability_score == 0.0 and s.resume_file_name == ""


def test_database_failure_on_load_is_surfaced(monkeypatch):
    s = AppState(_reflex_internal_init=True)
    def boom():
        raise RuntimeError("tenant not found")
    monkeypatch.setattr(service, "list_resumes", boom)
    drain(s, "load_catalogues")
    assert "Could not reach the database" in s.error and "tenant not found" in s.error
