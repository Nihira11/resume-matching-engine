"""Overview: the landing page — hero band, quick start, headline figures."""
import streamlit as st

from ui_common import (cached_recent, cached_stats, cached_summary,
                       get_service, guarded, invalidate, load_with_progress, nav_link,
                       samples_already_loaded,
                       page_header, panel, pick_pair,
                       postings, resumes, score_table, sidebar_footer, stat_tile,
                       token)

page_header("Overview",
            "Where this resume stands against the postings you've added this session.",
            ":material/dashboard:")

service = get_service()
resume_rows, posting_rows = resumes(), postings()
stats = guarded("Could not load the dashboard", cached_stats, token(), None) or {}

# ---- hero ------------------------------------------------------------
# Rendered before anything is loaded, not after. Gated on data it left a
# first-time visitor looking at an empty page with one box on it.
best_score = stats.get("best_score", 0) or 0
with st.container(key="hero"):
    st.badge("ATS-style screening", icon=":material/auto_awesome:", color="violet")
    if best_score:
        st.header(f"Best fit: {stats.get('best_title', '')}")
        st.markdown(f"{stats.get('matches', 0)} matches run across "
                    f"{stats.get('postings', 0)} postings · average "
                    f"{stats.get('avg_score', 0):.1f} / 100")
    else:
        st.header("Score your resume against a posting")
        st.markdown("Skill overlap, keyword match, title and seniority, experience "
                    "and semantic similarity — every number traceable to a component.")
    chips = st.columns(4)
    chips[0].markdown(":violet-badge[:material/label: 14,063 skills]")
    chips[1].markdown(":blue-badge[:material/functions: 5 components]")
    chips[2].markdown(":green-badge[:material/tune: calibrated on 40 postings]")
    chips[3].markdown(":gray-badge[:material/lock: session-scoped]")

# ---- quick start -----------------------------------------------------
# Shown until there is both a resume and a posting. The loaders used to
# live on the Resume and Job postings tabs, which assumes a visitor goes
# looking for them; most will not.
if not resume_rows or not posting_rows:
    with st.container(key="quickstart"):
        st.markdown("##### :material/rocket_launch: Try it in two clicks")
        st.caption("Load a pair of sample resumes and some postings, or upload your own. "
                   "Everything stays in this browser session.")

        # Each loader disappears once it has nothing left to add.
        # Offering it again only produced duplicate rows, and the
        # dropdowns then filled with copies of the same file.
        show_resumes = not samples_already_loaded()
        show_samples = not st.session_state.get("loaded_sample_postings")
        show_live = not st.session_state.get("loaded_live_postings")
        offered = [x for x in (show_resumes, show_live, show_samples) if x]
        if not offered:
            st.caption(":material/check_circle: Samples loaded. Upload your own "
                       "resume or paste a posting from the tabs below.")
        slots = st.columns(len(offered)) if offered else []
        slot = iter(slots)
        left = next(slot) if show_resumes else st.container()
        middle = next(slot) if show_live else st.container()
        right = next(slot) if show_samples else st.container()
        # No st.rerun() after these: the click already triggers one, and
        # the page renders after the work finishes so it sees the new
        # rows. A second rerun re-ran a 30s import and left the previous
        # run's widgets greyed out -- the "duplicated buttons" effect.
        with left:
            if show_resumes and st.button("Load 2 sample resumes", width="stretch", type="primary",
                         icon=":material/group:"):
                paths = sorted(service.SAMPLE_RESUMES_DIR.glob("*.pdf"))
                n = guarded(
                    "Could not load the sample resumes", load_with_progress,
                    "Parsing, extracting skills and embedding", paths,
                    lambda p: service.add_resume(str(p), token()),
                    lambda p: p.name,
                )
                if n:
                    invalidate()
                    st.toast(f"Loaded {n} sample resumes.", icon=":material/check_circle:")
                    st.rerun()
            st.caption("One ATS-clean, one with a table and a photo (100 vs 68 parsability).")

        with middle:
            if show_live and st.button("Load 5 live postings", width="stretch", type="primary",
                         icon=":material/download:"):
                # this one really is opaque: the fetch and the ingest
                # happen inside the service, so there is nothing honest
                # to count. Say what it is doing instead of faking a bar.
                with st.status("Fetching from company job boards…", expanded=False) as box:
                    n = guarded("Could not load postings",
                                service.load_live_postings, token())
                    box.update(label=f"Fetched {n or 0} postings", state="complete")
                if n:
                    st.session_state.loaded_live_postings = True
                    invalidate()
                    st.toast(f"Loaded {n} live postings.", icon=":material/check_circle:")
                    st.rerun()
            if show_live:
                st.caption("Current Australian graduate roles, fetched from "
                           "company job boards now.")

        with right:
            if show_samples and st.button("Load sample postings", width="stretch",
                         icon=":material/description:"):
                files = sorted(service.SAMPLES_DIR.glob("*.txt"))
                n = guarded(
                    "Could not load the samples", load_with_progress,
                    "Extracting requirements", files,
                    lambda f: service.add_jd(f.read_text(encoding="utf-8"), token(),
                                             source="sample", source_url=None),
                    lambda f: f.stem.replace("_", " "),
                )
                if n:
                    st.session_state.loaded_sample_postings = True
                    invalidate()
                    st.toast(f"Loaded {n} sample postings.", icon=":material/check_circle:")
                    st.rerun()
            if show_samples:
                st.caption("Three fictional postings that ship with the project "
                           "— instant, and never stale.")

        st.caption(":material/upload: Or upload your own resume and paste a posting:")
        links = st.columns([1, 1, 4])
        with links[0]:
            nav_link("app_pages/resume.py", "Resume tab", ":material/description:")
        with links[1]:
            nav_link("app_pages/postings.py", "Job postings", ":material/work:")

if not resume_rows:
    a, b, c, d = st.columns(4)
    with a:
        stat_tile("Best match", "—", "nothing scored yet", "emerald")
    with b:
        stat_tile("Average score", "—", "across scored postings", "indigo")
    with c:
        stat_tile("ATS parsability", "—", "formatting, scored separately", "amber")
    with d:
        stat_tile("Postings stored", stats.get("postings", 0),
                  "load some to get started", "sky")

    left_block, right_block = st.columns([3, 2])
    with left_block:
        with panel("start", "Start here", ":material/play_circle:"):
            st.markdown(
                "1. **Load a resume** — the samples above, or your own PDF\n"
                "2. **Add a posting** — sample, live, or paste one\n"
                "3. **Score the pair** — and see every component behind the number"
            )
            st.caption("Nothing is shared: rows are scoped to this browser session "
                       "and deleted after 24 hours.")
    with right_block:
        with panel("what", "What it measures", ":material/functions:"):
            st.markdown(
                ":violet-badge[Skill overlap] against a 14,063-term taxonomy\n\n"
                ":blue-badge[Keyword BM25] weighted by ~2,500 real resumes\n\n"
                ":green-badge[Title & seniority] role family and rung\n\n"
                ":orange-badge[Experience] years against the stated minimum\n\n"
                ":gray-badge[Semantic] MiniLM similarity, pooled per section"
            )
    sidebar_footer()
    st.stop()

# both selectors here, and the two actions, so the landing page can
# drive the whole flow without hunting for the right tab
resume_id, jd_id = pick_pair("overview")

actions = st.columns([1, 1, 3])
with actions[0]:
    if st.button("Score this pair", type="primary", width="stretch",
                 icon=":material/play_arrow:", disabled=not jd_id):
        st.session_state.autoscore = True
        st.switch_page("app_pages/match.py")
with actions[1]:
    if st.button("Rank all postings", width="stretch", icon=":material/sort:",
                 disabled=not jd_id):
        st.session_state.autorank = True
        st.switch_page("app_pages/leaderboard.py")
if not jd_id:
    st.caption("Add a posting to score against.")
stats = guarded("Could not load the dashboard", cached_stats, token(), resume_id) or stats
summary = guarded("Could not read that resume", cached_summary, resume_id) or {}

# ---- headline figures ------------------------------------------------
a, b, c, d = st.columns(4)
with a:
    stat_tile("Best match", f"{stats.get('best_score', 0):.1f}"
              if stats.get("best_score") else "—",
              stats.get("best_title") or "nothing scored yet", "emerald")
with b:
    stat_tile("Average score", f"{stats.get('avg_score', 0):.1f}",
              "across scored postings", "indigo")
with c:
    stat_tile("ATS parsability", f"{summary.get('parsability', 0):.0f}",
              "formatting, scored separately", "amber")
with d:
    stat_tile("Postings stored", stats.get("postings", 0),
              f"{stats.get('matches', 0)} matches run", "sky")

# ---- two blocks: what has been scored, and what is loaded ----------
recent = guarded("Could not load matches", cached_recent, resume_id) or []
left_block, right_block = st.columns([3, 2])

with left_block:
    with panel("recent", "Recent matches", ":material/history:"):
        if recent:
            score_table(recent)
        else:
            st.caption("Nothing scored yet. Pick a posting and score the pair.")
            nav_link("app_pages/match.py", "Go to Match results", ":material/play_arrow:")

with right_block:
    with panel("session", "In this session", ":material/inventory_2:"):
        counts = st.columns(2)
        counts[0].metric("Resumes", stats.get("resumes", 0))
        counts[1].metric("Postings", stats.get("postings", 0))
        st.caption("Scored against a fixed 40-posting calibration set, so "
                   "a score means the same thing between runs.")
        nav_link("app_pages/leaderboard.py", "Rank every posting", ":material/sort:")

sidebar_footer()
