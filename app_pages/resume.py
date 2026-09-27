"""Resume: upload, first-page preview, ATS parsability, what was read."""
import uuid

import streamlit as st

from ui_common import (page_header, panel, UPLOAD_DIR, cached_resume_detail,
                       cached_summary, empty_page, invalidate, resume_name_taken, get_service, guarded, pick_pair,
                       resumes, sidebar_footer, token)

page_header("Resume",
            "What the parser actually read, and how a real ATS would cope with the formatting.",
            ":material/description:")

service = get_service()

with panel("upload", "Upload a resume", ":material/upload_file:"):
    uploaded = st.file_uploader("Resume file", type=["pdf", "docx"],
                                label_visibility="collapsed")
    duplicate = uploaded is not None and resume_name_taken(uploaded.name)
    if duplicate:
        st.warning(f"**{uploaded.name}** is already in this session — parsing it "
                   "again would just add a duplicate to every dropdown. Rename "
                   "the file if it really is a different version.",
                   icon=":material/content_copy:")

    if (uploaded is not None and not duplicate
            and st.button("Parse this resume", type="primary",
                          icon=":material/play_arrow:")):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{uploaded.name}"
        path.write_bytes(uploaded.getbuffer())
        with st.spinner("Parsing, extracting skills and embedding…"):
            new_id = guarded("Could not parse that resume",
                             service.add_resume, str(path), token())
        # the text and preview are in the database now; the file itself is
        # personal data and is not needed again
        path.unlink(missing_ok=True)
        if new_id:
            invalidate()
            st.session_state.resume_id = new_id   # select what was just added
            st.toast("Resume parsed.", icon=":material/check_circle:")
            st.rerun()

if not resumes():
    empty_page(
        "What this page shows",
        ["**Page one, rendered** — see what the file actually looks like",
         "**ATS parsability, scored 0–100** — tables, images and running headers "
         "are the three things real parsers mangle, each flagged separately",
         "**Every skill the parser found**, against a 14,063-term taxonomy",
         "**The job titles it read**, which drive the title and seniority component"],
        "Get a resume in",
        ["Upload a PDF or DOCX above, or load the two samples — one ATS-clean, "
         "one deliberately broken, so the difference is visible."],
        [("app_pages/overview.py", "Load the samples", ":material/dashboard:")],
    )
else:
    resume_id, _ = pick_pair("resume", need_posting=False)
    summary = guarded("Could not read that resume", cached_summary, resume_id) or {}
    detail = guarded("Could not read that resume", cached_resume_detail, resume_id) or {}

    left, right = st.columns([2, 3])
    with left:
        with panel("preview", "Page one", ":material/image:"):
            if summary.get("preview"):
                st.image(summary["preview"], width="stretch")
            else:
                st.caption("No preview — these are rendered for PDFs only.")

    with right:
        score = summary.get("parsability", 0.0)
        flags = summary.get("flags") or []
        with panel("parsability", "ATS parsability", ":material/fact_check:"):
            head, badge = st.columns([1, 2])
            head.metric("Score", f"{score:.0f}/100", label_visibility="collapsed")
            with badge:
                if score >= 90:
                    st.badge("Clean", icon=":material/check:", color="green")
                elif score >= 70:
                    st.badge("Minor issues", icon=":material/warning:", color="orange")
                else:
                    st.badge("Would be mangled", icon=":material/error:", color="red")
            st.progress(min(max(score / 100, 0.0), 1.0))
            for flag in flags:
                st.warning(flag, icon=":material/warning:")
            if not flags:
                st.success("No formatting problems detected.", icon=":material/check_circle:")

        with panel("skills", f"Skills found · {summary.get('skills', 0)}", ":material/label:"):
            skills = detail.get("skills", [])
            st.markdown(" ".join(f":violet-badge[{s}]" for s in skills[:40]) or "None extracted.")

        if detail.get("titles"):
            with panel("titles", "Job titles read", ":material/work:"):
                for title in detail["titles"]:
                    st.markdown(f":material/chevron_right: {title}")

sidebar_footer()
