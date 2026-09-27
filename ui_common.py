"""
Shared helpers for the Streamlit pages in app_pages/.

Kept out of streamlit_app.py so each page is a plain script that can be
imported and driven by st.testing.v1.AppTest on its own -- with the pages
as inline functions there was no way to exercise them headlessly.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st

UPLOAD_DIR = Path("data/uploads")

VERDICT_COLOUR = {
    "Likely pass": "green",
    "Borderline": "orange",
    "Likely reject": "red",
}


@st.cache_resource(show_spinner=False)
def get_service():
    """Import once per process.

    Streamlit re-executes the script on every interaction; without the
    cache that would re-import torch and spaCy each time.
    """
    from src import service

    return service


def token() -> str:
    """Per-browser-session id, the key everything is scoped by.

    Resumes carry names, phone numbers and addresses, so nothing is
    listed without one -- service.list_resumes returns nothing rather
    than everything when the token is empty.
    """
    if "token" not in st.session_state:
        st.session_state.token = str(uuid.uuid4())
    return st.session_state.token


def guarded(label: str, fn, *args, **kwargs):
    """Run a service call, turning failure into a visible, safe message.

    safe_error strips credentials: psycopg2 puts the whole DSN into its
    exceptions and this text is shown to whoever is looking at the page.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as error:  # noqa: BLE001 -- surfaced, not swallowed
        st.error(f"{label}: {get_service().safe_error(error)}", icon=":material/error:")
        return None


def load_with_progress(label: str, items: list, work, name_of) -> int:
    """Run `work(item)` over items, showing real per-item progress.

    The service's own load_sample_* helpers do this loop internally and
    return only a count, so the UI could show nothing but an indefinite
    spinner -- and parsing two resumes takes ~30 seconds, which feels
    broken without a number moving. Driving the same per-item calls from
    here means the bar reflects actual work, not a guess.
    """
    total = len(items)
    if not total:
        return 0
    bar = st.progress(0.0, text=f"{label}…")
    done = 0
    for index, item in enumerate(items, start=1):
        bar.progress((index - 1) / total,
                     text=f"{label} — {index} of {total}: {name_of(item)}")
        work(item)
        done += 1
        bar.progress(index / total, text=f"{label} — {index} of {total} done")
    bar.empty()
    return done


# Read-only lookups, cached. Streamlit re-executes the whole script on
# every interaction, so without this each click re-ran five database
# round trips -- and against a remote Postgres that is seconds, during
# which Streamlit greys out the previous render. That grey, duplicated
# page is what "it looks broken / it's so slow" actually was.
#
# Short TTL plus an explicit clear after every write: a stale dropdown
# after uploading a resume would be worse than the round trip.
@st.cache_data(ttl=1800, show_spinner=False)
def _resumes(tok: str) -> list[dict]:
    return get_service().list_resumes(tok) or []


@st.cache_data(ttl=1800, show_spinner=False)
def _postings(tok: str) -> list[dict]:
    return get_service().list_jds(tok) or []


@st.cache_data(ttl=1800, show_spinner=False)
def cached_stats(tok: str, resume_id: int | None) -> dict:
    return get_service().dashboard_stats(resume_id, tok) or {}


@st.cache_data(ttl=1800, show_spinner=False)
def cached_summary(resume_id: int) -> dict:
    return get_service().resume_summary(resume_id) or {}


@st.cache_data(ttl=1800, show_spinner=False)
def cached_resume_detail(resume_id: int) -> dict:
    return get_service().resume_detail(resume_id) or {}


@st.cache_data(ttl=1800, show_spinner=False)
def cached_jd_detail(jd_id: int) -> dict:
    return get_service().jd_detail(jd_id) or {}


@st.cache_data(ttl=1800, show_spinner=False)
def cached_recent(resume_id: int) -> list[dict]:
    return get_service().recent_matches(resume_id) or []


def invalidate() -> None:
    """Drop the cached reads after anything writes."""
    for fn in (_resumes, _postings, cached_stats, cached_summary,
               cached_resume_detail, cached_jd_detail, cached_recent):
        fn.clear()


def resumes() -> list[dict]:
    return _resumes(token())


def postings() -> list[dict]:
    return _postings(token())


def _sample_resume_names() -> set[str]:
    try:
        return {path.name for path in get_service().SAMPLE_RESUMES_DIR.glob("*.pdf")}
    except Exception:  # noqa: BLE001 -- only affects which row is preselected
        return set()


def samples_already_loaded() -> bool:
    """True once this session holds the bundled sample resumes.

    Checked against what is actually in the session rather than a flag,
    so it survives a page reload and cannot drift from reality.
    """
    names = _sample_resume_names()
    if not names:
        return False
    have = {row.get("file_name") for row in resumes()}
    return bool(names) and names.issubset(have)


def resume_name_taken(file_name: str) -> bool:
    """Guard against loading the same file twice into one session."""
    return any(row.get("file_name") == file_name for row in resumes())


def _default_resume(rows: list[dict]) -> int:
    """Prefer the newest thing the visitor uploaded over a bundled sample.

    Rows arrive newest-first, so the first non-sample is the most recent
    upload. Someone who has just uploaded their own CV should not have
    to pick it out of a list that opens on a demo file.
    """
    samples = _sample_resume_names()
    for row in rows:
        if row.get("file_name") not in samples:
            return row["id"]
    return rows[0]["id"]


def selected_resume(widget_key: str, label: str = "Resume") -> int | None:
    """The resume selector, sharing one choice across every page.

    The value lives in st.session_state["resume_id"], not in the widget:
    each page renders its own selectbox, so per-widget state meant
    choosing a resume on Overview and finding the default again on
    Resume, Match and Leaderboard.
    """
    rows = resumes()
    if not rows:
        return None
    ids = [row["id"] for row in rows]
    if st.session_state.get("resume_id") not in ids:
        st.session_state.resume_id = _default_resume(rows)
    chosen = st.selectbox(
        label, rows, index=ids.index(st.session_state.resume_id),
        format_func=lambda r: r["label"], key=widget_key,
    )
    st.session_state.resume_id = chosen["id"]
    return chosen["id"]


def selected_posting(widget_key: str, label: str = "Job posting") -> int | None:
    """Same for postings: newest first, remembered across pages."""
    rows = postings()
    if not rows:
        return None
    ids = [row["id"] for row in rows]
    if st.session_state.get("jd_id") not in ids:
        st.session_state.jd_id = rows[0]["id"]      # newest added
    chosen = st.selectbox(
        label, rows, index=ids.index(st.session_state.jd_id),
        format_func=lambda r: r["label"], key=widget_key,
    )
    st.session_state.jd_id = chosen["id"]
    return chosen["id"]


def pick_pair(key: str, need_posting: bool = True) -> tuple[int | None, int | None]:
    """Both selectors side by side, sharing the session-wide choice."""
    if not resumes():
        return None, None
    show_posting = need_posting and bool(postings())
    columns = st.columns(2) if show_posting else [st.container()]
    with columns[0]:
        resume_id = selected_resume(f"{key}_resume")
    jd_id = None
    if show_posting:
        with columns[1]:
            jd_id = selected_posting(f"{key}_posting")
    return resume_id, jd_id


def nav_link(path: str, label: str, icon: str) -> None:
    """A link to another page, degrading to a caption if navigation is absent.

    st.page_link only resolves pages registered by st.navigation, so a
    page rendered on its own -- which is how the tests drive them --
    raises StreamlitPageNotFoundError and takes the whole page down. A
    missing link is not worth that.
    """
    try:
        st.page_link(path, label=label, icon=icon)
    except Exception:  # noqa: BLE001 -- no navigation context
        st.caption(f"{icon} {label}")


def empty_page(what_title: str, what_lines: list[str],
               next_title: str, next_lines: list[str],
               links: list[tuple[str, str, str]] | None = None) -> None:
    """The landing state for a page with nothing loaded yet.

    Two blocks rather than one icon in a void: what this page will show
    once there is data, and what to do to get there. An empty page is
    the first thing most visitors see, so it should still explain the
    tool rather than look broken.

    links: (page path, label, icon) tuples rendered as page links.
    """
    left, right = st.columns([3, 2])
    with left:
        with panel("whatis", what_title, ":material/help:"):
            for line in what_lines:
                st.markdown(line)
    with right:
        with panel("next", next_title, ":material/play_circle:"):
            for line in next_lines:
                st.markdown(line)
            for path, label, icon in links or []:
                nav_link(path, label, icon)


def score_table(rows: list[dict]):
    """Leaderboard/recent-match table, with the score as a bar."""
    return st.dataframe(
        [{"Posting": r["title"], "Company": r.get("company", ""), "Score": r["score"],
          "Verdict": r["verdict"], "Matched": r.get("matched", 0),
          "Missing": r.get("missing", 0)} for r in rows],
        width="stretch", hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.1f"),
        },
    )


def sidebar_footer() -> None:
    with st.sidebar:
        st.caption("**This session only**")
        st.caption(
            "Resumes and postings you add are visible only in this browser "
            "session, and are deleted 24 hours after you add them."
        )
        if st.button("Delete my data now", width="stretch", icon=":material/delete:"):
            result = guarded("Could not clear the session",
                             get_service().clear_session, token())
            if result:
                # the loaders are offered again once their rows are gone
                for flag in ("loaded_sample_postings", "loaded_live_postings"):
                    st.session_state.pop(flag, None)
                for key in ("views", "boards", "resume_id", "jd_id"):
                    st.session_state.pop(key, None)
                invalidate()
                st.toast(f"Deleted {result[0]} resumes and {result[1]} postings.",
                         icon=":material/check_circle:")
        try:
            stats = cached_stats(token(), None)
            st.caption(f":material/database: {stats.get('skills', 0):,} skills in taxonomy")
        except Exception:  # noqa: BLE001 -- a caption is not worth an error
            pass


# ---------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------
# CSS, which the Streamlit guidance says to avoid -- rightly, because
# selectors target internal class names. It is here because the brief
# asked for a card-based dashboard: a gradient hero and colour-coded
# stat tiles have no native equivalent. Everything expressible as a
# theme token is in .streamlit/config.toml instead, and every rule below
# hangs off a `key=` we set ourselves (.st-key-<key>), which is the
# documented way to target an element.
#
# Tailwind slate + indigo, matching config.toml. Tints are the -50
# shades, borders -200, figures -700: enough colour to separate the
# four tiles, not so much that the page turns into a rainbow.
# Tile tints per mode. The light set is Tailwind -50 backgrounds with
# -200 borders and -700 figures; the dark set inverts that -- a dark
# translucent wash with a lighter figure -- so the four tiles stay
# distinguishable without glowing.
# Tailwind -50 backgrounds, -200 borders, -700 figures: enough colour to
# tell the four tiles apart without turning the page into a rainbow.
TILE_COLOURS = {
    "indigo":  ("#eef2ff", "#c7d2fe", "#4338ca"),
    "emerald": ("#ecfdf5", "#a7f3d0", "#047857"),
    "amber":   ("#fffbeb", "#fde68a", "#b45309"),
    "sky":     ("#f0f9ff", "#bae6fd", "#0369a1"),
}

_SHADOW = ("0 1px 2px rgba(16, 24, 40, 0.04), "
           "0 4px 12px -4px rgba(16, 24, 40, 0.06)")

_CSS = f"""
<style>
/* ---- hero band ---- */
.st-key-hero {{
    background: linear-gradient(120deg, #eef2ff 0%, #f0f9ff 55%, #ffffff 100%);
    border: 1px solid #c7d2fe;
    border-radius: 14px;
    padding: 1.5rem 1.75rem;
    box-shadow: {_SHADOW};
}}
.st-key-hero h2, .st-key-hero h3 {{ margin: 0.2rem 0 0.1rem; }}

/* ---- quick start ---- */
.st-key-quickstart {{
    background: #ffffff;
    border: 1px solid #e6eaf2;
    border-radius: 14px;
    padding: 1.25rem 1.4rem;
    box-shadow: {_SHADOW};
}}

/* ---- panels: the left/right blocks each page is built from ----
   White cards on a tinted page, with a shadow soft enough to read as
   depth rather than as a second drawn border. */
div[class*="st-key-panel-"] {{
    border: 1px solid #e6eaf2;
    border-radius: 14px;
    padding: 1.1rem 1.3rem;
    background: #ffffff;
    box-shadow: {_SHADOW};
}}
div[class*="st-key-panel-"] h3 {{ margin-top: 0; }}
div[class*="st-key-panel-"] [data-testid="stDataFrame"] {{ border-radius: 10px; }}

/* ---- stat tiles ---- */
div[class*="st-key-tile-"] {{
    border-radius: 12px;
    padding: 0.9rem 1.1rem;
    box-shadow: {_SHADOW};
}}
div[class*="st-key-tile-"] [data-testid="stMetricValue"] {{
    font-size: 1.9rem; font-weight: 700; line-height: 1.15;
}}
div[class*="st-key-tile-"] [data-testid="stMetricLabel"] {{
    font-weight: 600; opacity: 0.85;
}}
"""
for _name, (_bg, _border, _fg) in TILE_COLOURS.items():
    _CSS += (f'\n.st-key-tile-{_name} {{ background: {_bg}; border: 1px solid {_border}; }}'
             f'\n.st-key-tile-{_name} [data-testid="stMetricValue"] {{ color: {_fg}; }}')
_CSS += "\n</style>"


def inject_css() -> None:
    """Once per page render; Streamlit dedupes identical html blocks."""
    st.html(_CSS)


def stat_tile(label: str, value, caption: str, colour: str) -> None:
    """One of the four coloured figures across the top of the overview."""
    with st.container(key=f"tile-{colour}"):
        st.metric(label, value)
        st.caption(caption)


def panel(key: str, title: str, icon: str):
    """A bordered block with a heading -- the unit each page is built from.

    Returns the container so the caller can fill it with `with`.
    """
    box = st.container(key=f"panel-{key}")
    with box:
        st.subheader(title, icon=icon)
    return box


def page_header(title: str, subtitle: str, icon: str) -> None:
    inject_css()
    st.title(title, icon=icon)
    st.caption(subtitle)
