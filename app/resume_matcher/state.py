"""
Central app state.

Scoring is slow the first time -- spaCy's large model, the ESCO +
curated PhraseMatcher and MiniLM all load on first use, and the embedding
pass writes chunks back to pgvector. Every handler that touches the
pipeline is therefore a background event running the blocking work in a
worker thread, so the websocket stays live and the UI can show what stage
it is at instead of freezing.
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import reflex as rx

from . import service


# Plain dataclasses, not rx.Base (removed in Reflex 0.9). The point is the
# annotations: rx.foreach refuses to iterate a var it only knows as Any,
# which is what an untyped dict state var produces once you index it.
@dataclasses.dataclass
class ComponentRow:
    """One scoring component, as the breakdown renders it."""
    key: str = ""
    label: str = ""
    help: str = ""
    score: float = 0.0
    weight_pct: int = 0
    contribution: float = 0.0


@dataclasses.dataclass
class GapRow:
    skill_name: str = ""
    requirement: str = ""
    is_required: bool = False
    mentions: int = 0
    adjacent: str = ""


@dataclasses.dataclass
class MatchRow:
    jd_id: int = 0
    title: str = ""
    company: str = ""
    score: float = 0.0
    verdict: str = ""
    verdict_color: str = "gray"
    when: str = ""


@dataclasses.dataclass
class BoardRow:
    jd_id: int = 0
    title: str = ""
    company: str = ""
    score: float = 0.0
    verdict: str = ""
    verdict_color: str = "gray"
    matched: int = 0
    missing: int = 0


class AppState(rx.State):
    # --- session ------------------------------------------------------
    # Everything this browser session creates is stamped with this token
    # and listed only for it. Reflex issues one per session, so two
    # visitors never see each other's resumes.
    @rx.var
    def session_token(self) -> str:
        return self.router.session.client_token or ""

    # --- navigation ---------------------------------------------------
    section: str = "overview"   # overview | resume | postings | match | leaderboard

    # --- dashboard ------------------------------------------------------
    stat_resumes: int = 0
    stat_postings: int = 0
    stat_matches: int = 0
    stat_skills: int = 0
    best_title: str = ""
    best_score: float = 0.0
    avg_score: float = 0.0
    recent: list[MatchRow] = []

    # --- detail panels --------------------------------------------------
    resume_skills: list[str] = []
    resume_titles: list[str] = []
    resume_education: list[str] = []
    resume_years: list[str] = []
    jd_required: list[str] = []
    jd_preferred: list[str] = []
    jd_excerpt: str = ""

    # --- catalogues -------------------------------------------------
    resumes: list[dict] = []
    jds: list[dict] = []

    # --- selection --------------------------------------------------
    resume_id: int = 0
    jd_id: int = 0

    # --- resume panel -----------------------------------------------
    resume_file_name: str = ""
    resume_skill_count: int = 0
    parsability_score: float = 0.0
    parsability_flags: list[str] = []

    # --- JD entry ---------------------------------------------------
    jd_mode: str = "Saved postings"      # "Saved postings" | "Paste new"
    jd_text: str = ""
    jd_title: str = ""
    jd_company: str = ""

    # --- results ----------------------------------------------------
    # Flat and typed rather than one result dict: rx.foreach cannot
    # iterate a var it only knows as Any, which is what indexing an
    # untyped dict state var produces.
    has_result: bool = False
    final_score: float = 0.0
    fit_band: str = ""
    percentile_label: str = ""
    verdict: str = ""
    verdict_color: str = "gray"
    components: list[ComponentRow] = []
    dropped: list[str] = []
    matched_required: list[str] = []
    matched_preferred: list[str] = []
    missing_required: list[str] = []
    missing_preferred: list[str] = []
    gaps: list[GapRow] = []
    suggestions: list[str] = []
    keyword_terms: list[str] = []
    keyword_matched: int = 0
    keyword_total: int = 0
    title_note: str = ""
    experience_note: str = ""
    leaderboard: list[BoardRow] = []

    # --- progress / errors ------------------------------------------
    busy: bool = False
    status: str = ""
    status_note: str = ""
    error: str = ""

    @rx.var
    def score_ring_css(self) -> str:
        """The score ring's conic-gradient, built server-side.

        Interpolating state vars into a CSS string inside the component
        emitted a raw template literal into the generated JSX and the
        bundler refused to parse it. A plain computed string var is one
        value the frontend just assigns.
        """
        colors = {
            "grass": "#30a46c",
            "amber": "#ffb224",
            "tomato": "#e5484d",
            "gray": "#8b8d98",
        }
        color = colors.get(self.verdict_color, colors["gray"])
        degrees = max(0.0, min(self.final_score, 100.0)) * 3.6
        return f"conic-gradient({color} {degrees:.1f}deg, rgba(128,128,128,0.22) 0deg)"

    @rx.var
    def best_ring_css(self) -> str:
        degrees = max(0.0, min(self.best_score, 100.0)) * 3.6
        return f"conic-gradient(#12a594 {degrees:.1f}deg, rgba(148,163,184,0.25) 0deg)"

    @rx.var
    def ready_to_score(self) -> bool:
        return self.resume_id > 0 and self.jd_id > 0 and not self.busy

    @rx.var
    def resume_options(self) -> list[str]:
        return [r["label"] for r in self.resumes]

    @rx.var
    def jd_options(self) -> list[str]:
        return [j["label"] for j in self.jds]

    @rx.var
    def selected_resume_label(self) -> str:
        return next((r["label"] for r in self.resumes if r["id"] == self.resume_id), "")

    @rx.var
    def selected_jd_label(self) -> str:
        return next((j["label"] for j in self.jds if j["id"] == self.jd_id), "")

    @rx.var
    def parsability_caption(self) -> str:
        if not self.resume_id:
            return ""
        if not self.parsability_flags:
            return "No formatting problems detected."
        return f"{len(self.parsability_flags)} formatting issue(s) an ATS may trip on:"

    def _apply_view(self, view: dict) -> None:
        self.final_score = view["final_score"]
        self.fit_band = view["fit_band"]
        self.percentile_label = view["percentile_label"]
        self.verdict = view["verdict"]
        self.verdict_color = view["verdict_color"]
        self.components = [ComponentRow(**c) for c in view["components"]]
        self.dropped = view["dropped"]
        self.matched_required = view["matched_required"]
        self.matched_preferred = view["matched_preferred"]
        self.missing_required = view["missing_required"]
        self.missing_preferred = view["missing_preferred"]
        self.gaps = [GapRow(**g) for g in view["gaps"]]
        self.suggestions = view["suggestions"]
        self.keyword_terms = view["keyword_terms"]
        self.keyword_matched = view["keyword_matched"]
        self.keyword_total = view["keyword_total"]
        self.title_note = view["title_note"]
        self.experience_note = view["experience_note"]
        self.has_result = True

    def _clear_result(self) -> None:
        self.has_result = False
        self.components = []
        self.gaps = []
        self.suggestions = []

    @rx.event
    def go(self, section: str):
        self.section = section

    @rx.event(background=True)
    async def refresh_dashboard(self):
        resume_id = self.resume_id
        try:
            stats = await asyncio.to_thread(service.dashboard_stats, resume_id, self.session_token)
            recent = await asyncio.to_thread(service.recent_matches, resume_id) if resume_id else []
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.error = f"Could not load the dashboard: {exc}"
            return
        async with self:
            self.stat_resumes = stats["resumes"]
            self.stat_postings = stats["postings"]
            self.stat_matches = stats["matches"]
            self.stat_skills = stats["skills"]
            self.best_title = stats["best_title"]
            self.best_score = stats["best_score"]
            self.avg_score = stats["avg_score"]
            self.recent = [MatchRow(**m) for m in recent]

    @rx.event(background=True)
    async def refresh_details(self):
        resume_id, jd_id = self.resume_id, self.jd_id
        if resume_id:
            detail = await asyncio.to_thread(service.resume_detail, resume_id)
            async with self:
                self.resume_skills = detail["skills"]
                self.resume_titles = detail["titles"]
                self.resume_education = detail["education"]
                self.resume_years = detail["years"]
        if jd_id:
            detail = await asyncio.to_thread(service.jd_detail, jd_id)
            async with self:
                self.jd_required = detail["required"]
                self.jd_preferred = detail["preferred"]
                self.jd_excerpt = detail["excerpt"]

    # --- loading ----------------------------------------------------
    @rx.event(background=True)
    async def load_catalogues(self):
        token = self.session_token
        async with self:
            self.error = ""
        # opportunistic: keeps abandoned sessions from accumulating
        # without needing a scheduler
        try:
            await asyncio.to_thread(service.purge_expired)
        except Exception:  # noqa: BLE001 -- a failed sweep must not block the page
            pass
        try:
            resumes = await asyncio.to_thread(service.list_resumes, token)
            jds = await asyncio.to_thread(service.list_jds, token)
        except Exception as exc:  # noqa: BLE001 -- surfaced in the UI
            async with self:
                self.error = f"Could not reach the database: {exc}"
            return
        async with self:
            self.resumes = resumes
            self.jds = jds
            if not self.resume_id and resumes:
                self.resume_id = resumes[0]["id"]
            if not self.jd_id and jds:
                self.jd_id = jds[0]["id"]
            resume_id = self.resume_id

        # Fetched here rather than by chaining a second background event.
        # The chained version raced the page: its delta could land after
        # the browser had reconnected under a new token, and the panel sat
        # at 0/100 while the server logged "delta to disconnected client".
        if resume_id:
            await self._load_summary(resume_id)
        return [AppState.refresh_dashboard, AppState.refresh_details]

    async def _load_summary(self, resume_id: int) -> None:
        summary = await asyncio.to_thread(service.resume_summary, resume_id)
        async with self:
            if resume_id != self.resume_id:
                return  # selection moved on while this was in flight
            self.resume_file_name = summary.get("file_name", "")
            self.parsability_score = summary.get("parsability", 0.0)
            self.parsability_flags = summary.get("flags", [])
            self.resume_skill_count = summary.get("skills", 0)

    @rx.event(background=True)
    async def refresh_resume_summary(self):
        resume_id = self.resume_id
        if resume_id:
            await self._load_summary(resume_id)
        return [AppState.refresh_dashboard, AppState.refresh_details]

    # --- selection handlers ------------------------------------------
    @rx.event
    def select_resume(self, label: str):
        for r in self.resumes:
            if r["label"] == label:
                self.resume_id = r["id"]
                self._clear_result()
                self.leaderboard = []
                return [
                    AppState.refresh_resume_summary,
                    AppState.refresh_details,
                    AppState.refresh_dashboard,
                ]

    @rx.event
    def select_jd(self, label: str):
        for j in self.jds:
            if j["label"] == label:
                self.jd_id = j["id"]
                self._clear_result()
                return AppState.refresh_details

    @rx.event
    def set_jd_mode(self, mode: str | list[str]):
        # segmented_control hands back a list when multi-select is possible
        self.jd_mode = mode if isinstance(mode, str) else (mode[0] if mode else "")

    # Reflex 0.9 dropped implicit set_<var> handlers, so the pasted-JD
    # fields get explicit ones.
    @rx.event
    def set_jd_title(self, value: str):
        self.jd_title = value

    @rx.event
    def set_jd_company(self, value: str):
        self.jd_company = value

    @rx.event
    def set_jd_text(self, value: str):
        self.jd_text = value

    # --- ingestion ----------------------------------------------------
    @rx.event
    async def handle_resume_upload(self, files: list[rx.UploadFile]):
        """Save the upload, then hand the slow part to a background event.

        Reflex rejects a background upload handler outright, and it is right
        to: the file has to be read while the request is alive. Parsing and
        the taxonomy pass happen in process_resume instead.
        """
        if not files:
            return
        upload = files[0]
        name = Path(upload.name or "resume.pdf").name
        if Path(name).suffix.lower() not in (".pdf", ".docx"):
            self.error = "Upload a .pdf or .docx file."
            return

        data = await upload.read()
        target = Path(rx.get_upload_dir()) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        self.busy = True
        self.error = ""
        self.status = f"Parsing {name} — extracting text, checking ATS formatting, tagging skills…"
        return AppState.process_resume(str(target))

    @rx.event(background=True)
    async def process_resume(self, target: str):
        token = self.session_token
        try:
            resume_id = await asyncio.to_thread(service.add_resume, str(target), token)
            resumes = await asyncio.to_thread(service.list_resumes, token)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Could not parse that resume: {exc}"
            return
        async with self:
            self.resumes = resumes
            self.resume_id = resume_id
            self._clear_result()
            self.leaderboard = []
            self.busy, self.status = False, ""
        return AppState.refresh_resume_summary

    @rx.event(background=True)
    async def save_pasted_jd(self):
        if len(self.jd_text.strip()) < 200:
            async with self:
                self.error = "That looks too short — paste the whole posting, including the requirements."
            return
        async with self:
            self.busy = True
            self.error = ""
            self.status = "Reading the posting and tagging its requirements…"
        try:
            jd_id = await asyncio.to_thread(
                service.add_jd, self.jd_text, self.session_token,
                self.jd_title, self.jd_company,
            )
            jds = await asyncio.to_thread(service.list_jds, self.session_token)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Could not save that posting: {exc}"
            return
        async with self:
            self.jds = jds
            self.jd_id = jd_id
            self.jd_text = self.jd_title = self.jd_company = ""
            self.jd_mode = "Saved postings"
            self._clear_result()
            self.busy, self.status = False, ""

    # --- scoring ------------------------------------------------------
    @rx.event(background=True)
    async def run_match(self):
        if not (self.resume_id and self.jd_id):
            return
        async with self:
            self.busy = True
            self.error = ""
            self._clear_result()
            self.status = "Scoring — loading models, embedding sections, comparing skills…"
        try:
            view = await asyncio.to_thread(service.score_pair, self.resume_id, self.jd_id)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Scoring failed: {exc}"
            return
        async with self:
            self._apply_view(view)
            self.section = "match"
            self.busy, self.status = False, ""
        return AppState.refresh_dashboard

    @rx.event(background=True)
    async def run_leaderboard(self):
        if not self.resume_id:
            return
        jds = list(self.jds)
        async with self:
            self.busy = True
            self.error = ""
            self.leaderboard = []
            self.status = f"Scoring against {len(jds)} postings…"
            self.section = "leaderboard"

        # One posting at a time, pushing each row as it lands. The whole
        # set takes minutes against a remote database, and a table that
        # fills in beats a spinner that sits there.
        rows: list[dict] = []
        for index, jd in enumerate(jds, start=1):
            try:
                row = await asyncio.to_thread(service.board_row, self.resume_id, jd)
            except Exception as exc:  # noqa: BLE001
                async with self:
                    self.busy, self.status = False, ""
                    label = jd.get("title") or jd.get("label") or f"posting {jd.get('id')}"
                    self.error = f"Ranking failed on '{label}': {exc}"
                return
            rows.append(row)
            rows.sort(key=lambda r: r["score"], reverse=True)
            async with self:
                self.leaderboard = [BoardRow(**r) for r in rows]
                self.status = f"Scored {index} of {len(jds)} postings…"
        async with self:
            self.busy, self.status = False, ""

    @rx.event
    def clear_error(self):
        self.error = ""

    @rx.event(background=True)
    async def load_live_postings(self):
        """Pull current graduate postings from company job boards.

        Fetched at click time rather than shipped with the repo: real
        postings go stale within weeks, and a demo full of dead listings
        is worse than no demo. Falls back to the fictional samples if the
        boards cannot be reached.
        """
        token = self.session_token
        async with self:
            self.busy = True
            self.error = ""
            self.status = "Fetching current graduate postings from company job boards…"
        try:
            count = await asyncio.to_thread(service.load_live_postings, token, 5)
            jds = await asyncio.to_thread(service.list_jds, token)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Could not load postings: {exc}"
            return
        async with self:
            self.jds = jds
            if jds:
                self.jd_id = jds[0]["id"]
            self.busy, self.status = False, ""
            self.status_note = f"Loaded {count} postings into this session."
        return AppState.refresh_details

    @rx.event(background=True)
    async def load_sample_postings(self):
        """Three fictional postings that ship with the repo -- written for
        this project, so they never expire and belong to nobody."""
        token = self.session_token
        async with self:
            self.busy = True
            self.error = ""
            self.status = "Loading sample postings…"
        try:
            count = await asyncio.to_thread(service.load_sample_postings, token)
            jds = await asyncio.to_thread(service.list_jds, token)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Could not load the samples: {exc}"
            return
        async with self:
            self.jds = jds
            if jds:
                self.jd_id = jds[0]["id"]
            self.busy, self.status = False, ""
            self.status_note = f"Loaded {count} sample postings into this session."
        return AppState.refresh_details

    @rx.event(background=True)
    async def clear_my_data(self):
        """Delete everything this session added, now rather than at TTL."""
        token = self.session_token
        async with self:
            self.busy = True
            self.status = "Deleting this session's resumes and postings…"
        try:
            resumes, postings = await asyncio.to_thread(service.clear_session, token)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.busy, self.status = False, ""
                self.error = f"Could not clear the session: {exc}"
            return
        async with self:
            self.resumes, self.jds = [], []
            self.resume_id = self.jd_id = 0
            self.resume_skills, self.resume_titles = [], []
            self.resume_education, self.resume_years = [], []
            self.jd_required, self.jd_preferred, self.jd_excerpt = [], [], ""
            self.parsability_score, self.resume_skill_count = 0.0, 0
            self.parsability_flags = []
            self._clear_result()
            self.leaderboard = []
            self.busy, self.status = False, ""
            self.status_note = f"Deleted {resumes} resume(s) and {postings} posting(s)."
        return AppState.refresh_dashboard

    @rx.event
    def cancel_busy(self):
        """Escape hatch for a lost update.

        A websocket event can be dropped (a reconnect mid-run, a server
        reload), and the work that would have cleared `busy` then never
        reports back, leaving the page spinning with no way out but a
        refresh. This does not stop the background work; it hands the
        controls back.
        """
        self.busy = False
        self.status = ""
