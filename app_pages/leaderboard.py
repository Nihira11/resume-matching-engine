"""Leaderboard: one resume against every posting in the session."""
import streamlit as st

from ui_common import (page_header, panel, empty_page, invalidate, get_service, guarded, pick_pair, postings,
                       resumes, score_table, sidebar_footer)

page_header("Leaderboard",
            "One resume against every posting in this session, best first.",
            ":material/trophy:")

service = get_service()
posting_rows = postings()

if not (resumes() and posting_rows):
    have_resume = bool(resumes())
    empty_page(
        "What this ranks",
        ["**One resume against every posting** in this session, best first",
         "**Scored one at a time**, so the table fills in as results land "
         "rather than blocking on the whole set",
         "**Matched and missing counts** beside each score, so a high rank "
         "with thin evidence is visible rather than hidden"],
        "Still needed",
        [f"{'✅' if have_resume else '⬜️'} A resume",
         f"{'✅' if posting_rows else '⬜️'} At least one posting"],
        [("app_pages/overview.py", "Load samples", ":material/dashboard:")],
    )
else:
    resume_id, _ = pick_pair("board", need_posting=False)

    with panel("board", f"{len(posting_rows)} postings in this session",
               ":material/format_list_numbered:"):
        st.caption("Scored one at a time, so the table fills in as results land. "
                   "The first takes longest — the model loads once.")

    # kept per resume, so switching pages does not discard a finished run
    boards = st.session_state.setdefault("boards", {})
    run = st.button(f"Rank all {len(posting_rows)} postings", type="primary",
                    icon=":material/sort:")
    if st.session_state.pop("autorank", False):
        run = True      # arrived from the button on Overview

    if run:
        rows: list[dict] = []
        progress = st.progress(0.0, text="Starting…")
        slot = st.empty()
        # one posting at a time, rendering as each lands: the whole set
        # takes a while against a remote database, and a table that fills
        # in beats a spinner that sits there
        for index, posting in enumerate(posting_rows, start=1):
            row = guarded(f"Ranking failed on '{posting['label']}'",
                          service.board_row, resume_id, posting)
            if row is None:
                break
            rows.append(row)
            rows.sort(key=lambda r: r["score"], reverse=True)
            progress.progress(index / len(posting_rows),
                              text=f"Scored {index} of {len(posting_rows)}")
            with slot.container():
                score_table(rows)
        progress.empty()
        boards[resume_id] = rows
        invalidate()   # every row scored is a new match_results row
    elif boards.get(resume_id):
        score_table(boards[resume_id])
    else:
        st.caption("Press **Rank all** to score this resume against every posting.")

sidebar_footer()
