"""
Central app state.
"""
import reflex as rx


class AppState(rx.State):
    # resume upload
    resume_filename: str = ""
    resume_text: str = ""
    parsability_score: float = 0.0
    parsability_flags: list[str] = []

    # job description input 
    jd_source: str = "paste"       # "paste" | "adzuna_search" | "url"
    jd_text: str = ""
    jd_title: str = ""

    # match results
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    final_score: float = 0.0
    verdict: str = ""              # "likely_pass" | "borderline" | "likely_reject"
    matched_skills: list[str] = []
    missing_skills: list[str] = []

    # stretch: LLM rewrite suggestions 
    rewrite_suggestions: list[str] = []

    # stretch: batch leaderboard 
    batch_results: list[dict] = []

    def handle_resume_upload(self, files: list[rx.UploadFile]):
        # wire this to src/ingestion parsing pipeline
        pass

    def run_match(self):
        # wire this to src/matching pipeline
        pass
