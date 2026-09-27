"""Job postings: paste one, see required vs nice-to-have."""
import streamlit as st

from ui_common import (page_header, panel, cached_jd_detail, empty_page, invalidate,
                       selected_posting, get_service, guarded, postings,
                       sidebar_footer, token)

page_header("Job postings",
            "Paste a posting whole — required vs nice-to-have is read from its headings.",
            ":material/work:")

service = get_service()

with panel("addposting", "Add a posting", ":material/add_circle:"):
    with st.form("add_posting", border=False):
        meta = st.columns(2)
        title = meta[0].text_input("Title", placeholder="Graduate Data Analyst")
        company = meta[1].text_input("Company", placeholder="Acme")
        text = st.text_area("Posting text", height=200,
                            placeholder="Paste the whole posting, headings and all.")
        if st.form_submit_button("Add posting", type="primary",
                                 icon=":material/add:") and text.strip():
            with st.spinner("Extracting requirements and embedding…"):
                new_id = guarded("Could not save that posting", service.add_jd,
                                 text, token(), title, company)
            if new_id:
                st.toast("Posting added.", icon=":material/check_circle:")

posting_rows = postings()
if not posting_rows:
    empty_page(
        "What gets extracted",
        ["**Required vs nice-to-have**, read from the posting's own headings — "
         "\"must have\" and \"desirable\" sections are weighted differently",
         "**Boilerplate stripped** — benefits, EEO statements and scam warnings "
         "describe the employer, not the job, and would otherwise skew the score",
         "**Skills, seniority and any stated minimum years**"],
        "Add a posting",
        ["Paste one whole above — headings and all, that is what the section "
         "parser reads. Or load three fictional ones that ship with the project."],
        [("app_pages/overview.py", "Load sample postings", ":material/dashboard:")],
    )
else:
    # the shared selector, not a local one: a private selectbox here was
    # why choosing a posting on Overview left this tab on its own choice
    jd_id = selected_posting("postings_page")
    detail = guarded("Could not read that posting", cached_jd_detail, jd_id) or {}

    left, right = st.columns(2)
    with left:
        with panel("required", f"Required · {len(detail.get('required', []))}",
                   ":material/priority_high:"):
            st.markdown(" ".join(f":red-badge[{s}]" for s in detail.get("required", []))
                        or "None extracted.")
    with right:
        with panel("preferred", f"Nice to have · {len(detail.get('preferred', []))}",
                   ":material/star:"):
            st.markdown(" ".join(f":orange-badge[{s}]" for s in detail.get("preferred", []))
                        or "None flagged — the posting has no 'preferred' heading.")

    with st.expander("Posting text", icon=":material/article:"):
        st.text(detail.get("excerpt", ""))

sidebar_footer()
