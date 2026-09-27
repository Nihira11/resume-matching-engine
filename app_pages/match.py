"""Match results: the blended score, and every component behind it."""
import time

import streamlit as st

from ui_common import (page_header, panel, VERDICT_COLOUR, empty_page, invalidate, get_service, guarded,
                       pick_pair, postings, resumes, sidebar_footer)

page_header("Match results",
            "Every number here is traceable to a component and its weight.",
            ":material/target:")

service = get_service()


def render_match(view: dict) -> None:
    colour = VERDICT_COLOUR.get(view["verdict"], "gray")

    with st.container(key="hero"):
        headline, verdict, note = st.columns([1, 1, 2])
        headline.metric("Blended score", f"{view['final_score']:.1f}",
                        view["fit_band"], delta_color="off")
        with verdict:
            st.caption("Verdict")
            st.badge(view["verdict"], color=colour, icon=":material/gavel:")
        with note:
            st.caption("How this compares")
            st.markdown(f"**{view['percentile_label']}**")
            if st.session_state.get("view_seconds"):
                st.caption(f"scored in {st.session_state.view_seconds:.1f}s")
        st.progress(min(max(view["final_score"] / 100, 0.0), 1.0))

    with panel("components", "How the score is built", ":material/insights:"):
        st.dataframe(
            [{"Component": c["label"], "Score": c["score"], "Weight %": c["weight_pct"],
              "Contribution": c["contribution"], "What it measures": c["help"]}
             for c in view["components"]],
            width="stretch", hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.1f"),
                "Contribution": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        if view["dropped"]:
            st.caption("Dropped — no signal, weights renormalised: "
                       + ", ".join(view["dropped"]))

    left, right = st.columns(2)
    with left:
        with panel("matched", f"Matched · {len(view['matched_required'])} required",
                   ":material/check_circle:"):
            st.markdown(" ".join(f":green-badge[{s}]" for s in view["matched_required"])
                        or "None.")
            if view["matched_preferred"]:
                st.caption("Nice to have")
                st.markdown(" ".join(f":blue-badge[{s}]" for s in view["matched_preferred"]))
    with right:
        with panel("missing", f"Missing · {len(view['missing_required'])} required",
                   ":material/cancel:"):
            st.markdown(" ".join(f":red-badge[{s}]" for s in view["missing_required"])
                        or "None.")

    if view["gaps"]:
        with panel("gaps", "Where the gaps are", ":material/trending_up:"):
            st.dataframe(
                [{"Skill": g["skill_name"], "Requirement": g["requirement"],
                  "Mentions": g["mentions"], "Related skills you have": g["adjacent"]}
                 for g in view["gaps"]],
                width="stretch", hide_index=True,
            )
    for suggestion in view.get("suggestions", []):
        st.info(suggestion, icon=":material/lightbulb:")

    with st.expander("Keyword and title detail", icon=":material/manage_search:"):
        st.markdown(f"**Keyword terms matched:** "
                    f"{view['keyword_matched']} of {view['keyword_total']}")
        st.markdown(" ".join(f":gray-badge[{t}]" for t in view["keyword_terms"]))
        st.markdown(f"**Title:** {view['title_note']}")
        st.markdown(f"**Experience:** {view['experience_note']}")


if not (resumes() and postings()):
    have_resume, have_posting = bool(resumes()), bool(postings())
    empty_page(
        "What you get back",
        ["**A blended score** with the fit band and where it sits against a "
         "fixed 40-posting calibration set",
         "**Five components** — skill overlap, keyword BM25, title and seniority, "
         "experience, semantic — each with its weight and contribution",
         "**Matched and missing skills**, required and nice-to-have apart",
         "**Gap analysis** — what is missing, and related skills you already have"],
        "Still needed",
        [f"{'✅' if have_resume else '⬜️'} A resume",
         f"{'✅' if have_posting else '⬜️'} A job posting"],
        [("app_pages/overview.py", "Load samples", ":material/dashboard:"),
         ("app_pages/resume.py", "Upload a resume", ":material/description:"),
         ("app_pages/postings.py", "Paste a posting", ":material/work:")],
    )
else:
    resume_id, jd_id = pick_pair("match")

    # Results are kept per pair, not in one slot. With a single slot,
    # navigating to another page and back re-rendered the page with the
    # selection re-initialised, the stored view no longer matched, and a
    # finished score vanished -- forcing a 60s rerun for a result the
    # session already had.
    views = st.session_state.setdefault("views", {})
    pair = (resume_id, jd_id)

    run = st.button("Score this pair", type="primary", icon=":material/play_arrow:")
    if st.session_state.pop("autoscore", False):
        run = True      # arrived here from the button on Overview

    if run:
        # score_pair is one call, so there is no honest sub-progress to
        # show. A status box naming the stages at least says what the
        # wait is for, and flags that the model load is a one-off.
        with st.status("Scoring this pair…", expanded=True) as box:
            started = time.time()
            st.write(":material/memory: Loading the embedding model "
                     "(first score only — later ones skip this)")
            st.write(":material/segment: Embedding resume and posting sections")
            st.write(":material/join_inner: Comparing skills, keywords, title and experience")
            view = guarded("Scoring failed", service.score_pair, resume_id, jd_id)
            elapsed = time.time() - started
            if view:
                views[pair] = (view, elapsed)
                # scoring writes a match_results row, so the dashboard
                # figures (best match, average, matches run) are now
                # stale -- without this they sat at 0 until the TTL
                invalidate()
                box.update(label=f"Scored in {elapsed:.1f}s", state="complete",
                           expanded=False)
            else:
                box.update(label="Scoring failed", state="error")

    if pair in views:
        view, seconds = views[pair]
        st.session_state.view_seconds = seconds
        render_match(view)
    else:
        st.caption("Press **Score this pair** to run the engine on this combination.")

sidebar_footer()
