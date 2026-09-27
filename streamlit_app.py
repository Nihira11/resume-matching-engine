"""
Resume <-> Job Matcher.

Streamlit UI over the matching engine in src/. Five pages, one question
each: what have I got, what did the parser read, what does the posting
ask for, how does this pair score, and which posting fits best.

Pages live in app_pages/ as plain scripts so each can be driven on its
own by st.testing.v1.AppTest; shared helpers are in ui_common.py.

Replaced a Reflex UI -- see docs/UI.md for why.

Run:  streamlit run streamlit_app.py
"""
import streamlit as st

st.set_page_config(
    page_title="Resume ↔ Job Matcher",
    page_icon=":material/target:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.navigation([
    st.Page("app_pages/overview.py", title="Overview",
            icon=":material/dashboard:", default=True),
    st.Page("app_pages/resume.py", title="Resume", icon=":material/description:"),
    st.Page("app_pages/postings.py", title="Job postings", icon=":material/work:"),
    st.Page("app_pages/match.py", title="Match results", icon=":material/target:"),
    st.Page("app_pages/leaderboard.py", title="Leaderboard", icon=":material/trophy:"),
]).run()
