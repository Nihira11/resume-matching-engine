"""
Reflex entrypoint. Run with: reflex run (from the app/ directory)

Dashboard shell: fixed sidebar, one section at a time. The sections follow
the work -- overview, the resume, the postings, the scored pair, the
ranking -- so each page answers one question instead of one long scroll
answering all of them at once.

The design rule throughout: every number is traceable. Components carry
their weights, skills carry their required/preferred status, gaps carry
how often the posting repeated them.
"""
import reflex as rx

from .service import VERDICT_CAVEAT
from .state import AppState

# Violet primary with teal/amber/rose accents: enough hue separation that
# the five scoring components stay distinguishable at a glance, including
# for red-green colour blindness (the two "good/bad" states are teal and
# rose, not green and red).
ACCENT = "violet"
SURFACE = "slate"

# per-tile accent colours, reused between the overview tiles and the
# charts so a colour always means the same thing
TILE_COLORS = ["teal", "violet", "amber", "cyan"]

SECTIONS = [
    ("overview", "Overview", "layout-dashboard"),
    ("resume", "Resume", "file-text"),
    ("postings", "Job postings", "briefcase"),
    ("match", "Match results", "target"),
    ("leaderboard", "Leaderboard", "trophy"),
]


def component_color(key) -> rx.Var:
    """One colour per scoring component, reused everywhere it appears."""
    return rx.match(
        key,
        ("skill_overlap", "violet"),
        ("keyword_bm25", "cyan"),
        ("title_seniority", "amber"),
        ("experience", "jade"),
        ("semantic", "pink"),
        "gray",
    )


# ---------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------
def card(*children, **props) -> rx.Component:
    # defaults, not hardcoded values: callers override padding and the
    # duplicate keyword would otherwise blow up at compile time
    style = {
        "padding": "1.25em",
        "border_radius": "16px",
        "background": rx.color(SURFACE, 1),
        "border": f"1px solid {rx.color(SURFACE, 5)}",
        "box_shadow": "0 1px 3px rgba(16, 24, 40, 0.06), 0 1px 2px rgba(16, 24, 40, 0.04)",
        "width": "100%",
    }
    style.update(props)
    return rx.box(rx.vstack(*children, spacing="3", align="stretch", width="100%"), **style)


def card_title(title: str, icon: str = "", hint: str = "", trailing=None) -> rx.Component:
    return rx.hstack(
        rx.cond(
            icon != "",
            rx.flex(
                rx.icon(icon, size=15, color=rx.color(ACCENT, 9)),
                align="center",
                justify="center",
                width="2em",
                height="2em",
                border_radius="8px",
                background=rx.color(ACCENT, 3),
                flex_shrink="0",
            ),
            rx.fragment(),
        ),
        rx.vstack(
            rx.heading(title, size="3"),
            rx.cond(hint != "", rx.text(hint, size="1", color_scheme="gray"), rx.fragment()),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        trailing if trailing is not None else rx.fragment(),
        width="100%",
        align="center",
        spacing="3",
    )


def chip(text, color: str, icon: str | None = None) -> rx.Component:
    return rx.badge(
        rx.cond(
            icon is not None,
            rx.hstack(rx.icon(icon or "dot", size=11), rx.text(text, size="1"), spacing="1", align="center"),
            rx.text(text, size="1"),
        ),
        color_scheme=color,
        variant="soft",
        radius="full",
        size="2",
    )


def chips(names, color: str, empty: str, icon: str | None = None) -> rx.Component:
    return rx.cond(
        names.length() > 0,
        rx.flex(rx.foreach(names, lambda n: chip(n, color, icon)), wrap="wrap", spacing="2", width="100%"),
        rx.text(empty, size="1", color_scheme="gray", font_style="italic"),
    )


def stat_tile(label: str, value, caption: str, icon: str, color: str) -> rx.Component:
    return card(
        rx.hstack(
            rx.flex(
                rx.icon(icon, size=17, color=rx.color(color, 9)),
                align="center",
                justify="center",
                width="2.4em",
                height="2.4em",
                border_radius="10px",
                background=rx.color(color, 3),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text(value, size="7", weight="bold", line_height="1.1", color=rx.color(color, 11)),
                rx.text(label, size="1", weight="medium", color=rx.color(SURFACE, 11)),
                spacing="1",
                align="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.text(caption, size="1", color=rx.color(SURFACE, 11)),
        padding="1em",
        background=rx.color(color, 2),
        border=f"1px solid {rx.color(color, 6)}",
    )


def donut(value, caption: str, gradient) -> rx.Component:
    """Score donut. The gradient string is computed in the state: building
    CSS by interpolating vars inside the component emits a raw template
    literal into the generated JSX and the bundler refuses to parse it."""
    return rx.flex(
        rx.flex(
            rx.vstack(
                rx.text(value, size="7", weight="bold", line_height="1"),
                rx.text(caption, size="1", color_scheme="gray"),
                spacing="0",
                align="center",
            ),
            align="center",
            justify="center",
            width="7.1em",
            height="7.1em",
            border_radius="999px",
            background=rx.color("gray", 1),
        ),
        align="center",
        justify="center",
        width="8.5em",
        height="8.5em",
        border_radius="999px",
        flex_shrink="0",
        background=gradient,
    )


def empty_hint(text: str, icon: str = "info") -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=14, color=rx.color("gray", 9), flex_shrink="0"),
        rx.text(text, size="1", color_scheme="gray"),
        spacing="2",
        align="center",
        padding_y="0.5em",
    )


# ---------------------------------------------------------------------
# sidebar + shell
# ---------------------------------------------------------------------
def nav_item(key: str, label: str, icon: str) -> rx.Component:
    active = AppState.section == key
    return rx.hstack(
        rx.icon(icon, size=16, color=rx.cond(active, "white", rx.color(SURFACE, 10))),
        rx.text(label, size="2", weight=rx.cond(active, "bold", "regular")),
        spacing="3",
        align="center",
        width="100%",
        padding_x="0.8em",
        padding_y="0.6em",
        border_radius="10px",
        cursor="pointer",
        background=rx.cond(active, rx.color(ACCENT, 9), "transparent"),
        color=rx.cond(active, "white", rx.color(SURFACE, 12)),
        box_shadow=rx.cond(active, "0 6px 16px -6px rgba(99, 91, 255, 0.65)", "none"),
        _hover={"background": rx.cond(active, rx.color(ACCENT, 10), rx.color(ACCENT, 3))},
        on_click=AppState.go(key),
        transition="background 120ms ease",
    )


def sidebar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.flex(
                rx.icon("scan-search", size=18, color="white"),
                align="center",
                justify="center",
                width="2.4em",
                height="2.4em",
                border_radius="12px",
                background=f"linear-gradient(135deg, {rx.color(ACCENT, 9)}, {rx.color('cyan', 9)})",
                box_shadow="0 8px 18px -8px rgba(99, 91, 255, 0.8)",
            ),
            rx.vstack(
                rx.text("Resume Matcher", size="2", weight="bold"),
                rx.text("ATS-style screening", size="1", color_scheme="gray"),
                spacing="0",
                align="start",
            ),
            spacing="3",
            align="center",
            width="100%",
            padding_bottom="1em",
        ),
        rx.vstack(
            *[nav_item(key, label, icon) for key, label, icon in SECTIONS],
            spacing="1",
            width="100%",
        ),
        rx.spacer(),
        rx.box(
            rx.text("Scores are uncalibrated", size="1", weight="medium"),
            rx.text(
                "Ordering between postings is the meaningful output, not the absolute number.",
                size="1",
                color_scheme="gray",
            ),
            padding="0.8em",
            border_radius="10px",
            background=rx.color("amber", 2),
            border=f"1px solid {rx.color('amber', 5)}",
            width="100%",
        ),
        rx.hstack(
            rx.text(AppState.stat_skills.to_string() + " skills in taxonomy", size="1", color_scheme="gray"),
            rx.spacer(),
            rx.color_mode.button(),
            width="100%",
            align="center",
        ),
        spacing="3",
        align="stretch",
        height="100vh",
        width="17em",
        padding="1.2em",
        border_right=f"1px solid {rx.color(SURFACE, 5)}",
        background=rx.color(SURFACE, 1),
        position="sticky",
        top="0",
        flex_shrink="0",
        display=rx.breakpoints(initial="none", md="flex"),
    )


def mobile_nav() -> rx.Component:
    return rx.flex(
        rx.foreach(
            rx.Var.create([s[0] for s in SECTIONS]),
            lambda key: rx.button(
                key,
                on_click=AppState.go(key),
                size="1",
                variant=rx.cond(AppState.section == key, "solid", "soft"),
                color_scheme=ACCENT,
            ),
        ),
        spacing="2",
        wrap="wrap",
        width="100%",
        padding_bottom="0.5em",
        display=rx.breakpoints(initial="flex", md="none"),
    )


def page_header(title: str, subtitle: str) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading(title, size="6"),
            rx.text(subtitle, size="2", color_scheme="gray"),
            spacing="1",
            align="start",
        ),
        rx.spacer(),
        rx.cond(
            AppState.busy,
            rx.hstack(
                rx.spinner(size="2"),
                rx.vstack(
                    rx.text(AppState.status, size="1", weight="medium"),
                    rx.text("first run loads the models", size="1", color_scheme="gray"),
                    spacing="0",
                    align="start",
                ),
                rx.button("Reset", on_click=AppState.cancel_busy, variant="ghost", size="1", color_scheme="gray"),
                spacing="2",
                align="center",
                padding="0.5em 0.8em",
                border_radius="10px",
                background=rx.color("gray", 2),
            ),
            rx.fragment(),
        ),
        width="100%",
        align="start",
        wrap="wrap",
        spacing="3",
    )


def score_buttons(size: str = "2") -> rx.Component:
    return rx.hstack(
        rx.button(
            rx.icon("play", size=15),
            "Score this pair",
            on_click=AppState.run_match,
            disabled=~AppState.ready_to_score,
            color_scheme=ACCENT,
            size=size,
        ),
        rx.button(
            rx.icon("list-ordered", size=15),
            "Rank all postings",
            on_click=AppState.run_leaderboard,
            disabled=AppState.busy | (AppState.resume_id == 0),
            variant="outline",
            color_scheme=ACCENT,
            size=size,
        ),
        spacing="2",
        wrap="wrap",
    )


def selection_bar() -> rx.Component:
    """Which pair is loaded, visible from every section."""
    return card(
        rx.hstack(
            rx.vstack(
                rx.text("Resume", size="1", color_scheme="gray"),
                rx.select(
                    AppState.resume_options,
                    value=AppState.selected_resume_label,
                    on_change=AppState.select_resume,
                    width="100%",
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            rx.vstack(
                rx.text("Job posting", size="1", color_scheme="gray"),
                rx.select(
                    AppState.jd_options,
                    value=AppState.selected_jd_label,
                    on_change=AppState.select_jd,
                    width="100%",
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            score_buttons(),
            spacing="4",
            align="end",
            wrap="wrap",
            width="100%",
        ),
        padding="1em",
    )


# ---------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------
def hero() -> rx.Component:
    """Headline band: what this resume is doing against the stored postings."""
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.badge(
                    rx.hstack(rx.icon("sparkles", size=12), rx.text("ATS-style screening", size="1"), spacing="1", align="center"),
                    color_scheme=ACCENT, variant="soft", radius="full",
                ),
                rx.heading(
                    rx.cond(AppState.best_title != "", "Best fit: " + AppState.best_title, "Score your resume against a posting"),
                    size="7",
                    color=rx.color(SURFACE, 12),
                ),
                rx.text(
                    rx.cond(
                        AppState.stat_matches > 0,
                        AppState.stat_matches.to_string() + " matches run across "
                        + AppState.stat_postings.to_string() + " postings · average "
                        + AppState.avg_score.to_string() + " / 100",
                        "Upload a resume, add a posting, and every number you get back is traceable to a component.",
                    ),
                    size="2",
                    color=rx.color(SURFACE, 11),
                ),
                score_buttons("2"),
                spacing="3",
                align="start",
            ),
            rx.spacer(),
            rx.cond(
                AppState.best_score > 0,
                donut(AppState.best_score.to_string(), "best score", AppState.best_ring_css),
                rx.fragment(),
            ),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="5",
        ),
        padding=rx.breakpoints(initial="1.3em", md="1.8em"),
        border_radius="18px",
        border=f"1px solid {rx.color(ACCENT, 5)}",
        background=f"linear-gradient(120deg, {rx.color(ACCENT, 3)}, {rx.color('cyan', 3)} 55%, {rx.color(SURFACE, 1)})",
        width="100%",
    )


def overview_section() -> rx.Component:
    return rx.vstack(
        page_header("Overview", "Where this resume stands against the postings you've stored."),
        hero(),
        selection_bar(),
        rx.grid(
            stat_tile("Best match", AppState.best_score.to_string(), AppState.best_title, "trophy", "teal"),
            stat_tile("Average score", AppState.avg_score.to_string(), "across scored postings", "chart-column", "violet"),
            stat_tile("ATS parsability", AppState.parsability_score.to_string(), "formatting, scored separately", "scan-line", "amber"),
            stat_tile("Postings stored", AppState.stat_postings.to_string(), AppState.stat_matches.to_string() + " matches run", "briefcase", "cyan"),
            columns=rx.breakpoints(initial="1", sm="2", lg="4"),
            spacing="4",
            width="100%",
        ),
        rx.grid(
            card(
                card_title(
                    "Recent matches", "history", "Latest score per posting for this resume",
                    trailing=rx.button("Rank all", on_click=AppState.run_leaderboard, size="1", variant="soft", color_scheme=ACCENT, disabled=AppState.busy),
                ),
                rx.cond(
                    AppState.recent.length() > 0,
                    rx.vstack(
                        rx.foreach(AppState.recent, recent_row),
                        spacing="2",
                        width="100%",
                    ),
                    empty_hint("No matches scored yet — pick a posting and hit 'Score this pair'."),
                ),
            ),
            card(
                card_title("How the score is built", "layers", "Weights are provisional until calibration"),
                rx.vstack(
                    weight_line("Skill overlap", "40%", "skill_overlap", "Taxonomy skills the posting asks for that the resume has"),
                    weight_line("Semantic", "20%", "semantic", "Section-level embedding similarity"),
                    weight_line("Keyword (BM25)", "15%", "keyword_bm25", "Distinctive posting terms, boilerplate stripped"),
                    weight_line("Title & seniority", "15%", "title_seniority", "Role family and level distance"),
                    weight_line("Experience", "10%", "experience", "Stated years vs the advertised minimum"),
                    spacing="3",
                    width="100%",
                ),
                empty_hint(VERDICT_CAVEAT, "triangle-alert"),
            ),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="4",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def weight_line(label: str, weight: str, key: str, hint: str) -> rx.Component:
    return rx.hstack(
        rx.box(width="8px", height="8px", border_radius="2px", background=rx.color(component_color(key), 9), flex_shrink="0"),
        rx.vstack(
            rx.text(label, size="2", weight="medium"),
            rx.text(hint, size="1", color_scheme="gray"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.badge(weight, variant="surface", color_scheme="gray"),
        width="100%",
        align="center",
        spacing="3",
    )


def recent_row(m) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(m.title, size="2", weight="medium"),
            rx.text(m.company + " · " + m.when, size="1", color_scheme="gray"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.badge(m.score.to_string(), color_scheme=m.verdict_color, variant="soft", radius="full", size="2"),
        width="100%",
        align="center",
        padding="0.7em 0.8em",
        border_radius="10px",
        background=rx.color("gray", 2),
    )


# ---------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------
def resume_section() -> rx.Component:
    tone = rx.cond(
        AppState.parsability_score >= 90, "grass",
        rx.cond(AppState.parsability_score >= 70, "amber", "tomato"),
    )
    return rx.vstack(
        page_header("Resume", "What the parser actually read, and how a real ATS would cope with the formatting."),
        rx.grid(
            card(
                card_title("Upload", "upload", "PDF or DOCX"),
                rx.upload(
                    rx.vstack(
                        rx.icon("cloud-upload", size=22, color=rx.color(ACCENT, 9)),
                        rx.text("Drop a resume here, or click to choose", size="2", weight="medium"),
                        rx.text("Parsed, formatting-checked and tagged on upload", size="1", color_scheme="gray"),
                        spacing="1",
                        align="center",
                    ),
                    id="resume_upload",
                    accept={
                        "application/pdf": [".pdf"],
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
                    },
                    max_files=1,
                    multiple=False,
                    on_drop=AppState.handle_resume_upload(rx.upload_files(upload_id="resume_upload")),
                    border=f"1px dashed {rx.color(ACCENT, 7)}",
                    border_radius="12px",
                    padding="1.6em",
                    width="100%",
                    cursor="pointer",
                    background=rx.color(ACCENT, 2),
                    _hover={"background": rx.color(ACCENT, 3)},
                ),
                rx.select(
                    AppState.resume_options,
                    value=AppState.selected_resume_label,
                    on_change=AppState.select_resume,
                    width="100%",
                ),
            ),
            card(
                card_title(
                    "ATS parsability", "scan-line", "Formatting only — never folded into the match score",
                    trailing=rx.badge(AppState.parsability_score.to_string() + " / 100", color_scheme=tone, variant="soft", radius="full", size="2"),
                ),
                rx.progress(value=AppState.parsability_score.to(int), max=100, color_scheme=tone, height="8px"),
                rx.text(AppState.parsability_caption, size="1", color_scheme="gray"),
                rx.foreach(
                    AppState.parsability_flags,
                    lambda f: rx.hstack(
                        rx.icon("triangle-alert", size=13, color=rx.color("amber", 9), flex_shrink="0"),
                        rx.text(f, size="1"),
                        spacing="2",
                        align="start",
                        padding="0.6em",
                        border_radius="8px",
                        background=rx.color("amber", 2),
                        width="100%",
                    ),
                ),
                empty_hint(
                    "Stored resumes keep the score they got when they were uploaded, so older rows predate detector changes.",
                ),
            ),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="4",
            width="100%",
        ),
        card(
            card_title(
                "Extracted skills", "tags", "What the matcher will compare against a posting",
                trailing=rx.badge(AppState.resume_skill_count.to_string() + " mentions", variant="surface", color_scheme="gray"),
            ),
            chips(AppState.resume_skills, "iris", "No skills extracted yet.", "check"),
        ),
        rx.grid(
            card(
                card_title("Titles found", "id-card"),
                chips(AppState.resume_titles, "cyan", "No job-title line found — the title component is scored neutral."),
            ),
            card(
                card_title("Education & experience", "graduation-cap"),
                chips(AppState.resume_education, "jade", "No degree line detected."),
                chips(AppState.resume_years, "amber", "No explicit 'N years' statement."),
            ),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="4",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------
# postings
# ---------------------------------------------------------------------
def postings_section() -> rx.Component:
    return rx.vstack(
        page_header("Job postings", "Paste a posting whole — required vs nice-to-have is read from its headings."),
        selection_bar(),
        rx.grid(
            card(
                card_title(
                    "Selected posting", "briefcase", AppState.selected_jd_label,
                    trailing=rx.badge(AppState.jd_required.length().to_string() + " required", color_scheme="tomato", variant="soft", radius="full"),
                ),
                rx.text("Required skills", size="2", weight="medium"),
                chips(AppState.jd_required, "tomato", "None extracted."),
                rx.text("Nice to have", size="2", weight="medium"),
                chips(AppState.jd_preferred, "amber", "None flagged as optional — the posting has no 'preferred' heading."),
                rx.text("Excerpt", size="2", weight="medium"),
                rx.box(
                    rx.text(AppState.jd_excerpt, size="1", color_scheme="gray", white_space="pre-wrap"),
                    max_height="12em",
                    overflow_y="auto",
                    padding="0.8em",
                    border_radius="10px",
                    background=rx.color("gray", 2),
                    width="100%",
                ),
            ),
            card(
                card_title("Add a posting", "plus", "Keep the requirements headings intact"),
                rx.input(
                    placeholder="Job title (optional — first line is used otherwise)",
                    value=AppState.jd_title,
                    on_change=AppState.set_jd_title,
                    width="100%",
                ),
                rx.input(
                    placeholder="Company (optional)",
                    value=AppState.jd_company,
                    on_change=AppState.set_jd_company,
                    width="100%",
                ),
                rx.text_area(
                    placeholder="Paste the full job posting here…",
                    value=AppState.jd_text,
                    on_change=AppState.set_jd_text,
                    rows="12",
                    width="100%",
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("save", size=15),
                        "Save posting",
                        on_click=AppState.save_pasted_jd,
                        disabled=AppState.busy,
                        color_scheme=ACCENT,
                    ),
                    rx.text(AppState.jd_text.length().to_string() + " characters", size="1", color_scheme="gray"),
                    spacing="3",
                    align="center",
                ),
            ),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="4",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------
# match results
# ---------------------------------------------------------------------
def component_row(c) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.tooltip(
                rx.hstack(
                    rx.box(width="8px", height="8px", border_radius="2px", background=rx.color(component_color(c.key), 9)),
                    rx.text(c.label, size="2", weight="medium"),
                    rx.icon("info", size=11, color=rx.color("gray", 8)),
                    spacing="2",
                    align="center",
                ),
                content=c.help,
            ),
            rx.spacer(),
            rx.badge("weight " + c.weight_pct.to_string() + "%", variant="surface", size="1", color_scheme="gray"),
            rx.text(c.score.to_string(), size="2", weight="bold", width="3.2em", text_align="right"),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.progress(value=c.score.to(int), max=100, color_scheme=component_color(c.key), margin_top="0.4em", height="6px"),
        width="100%",
        margin_bottom="0.85em",
    )


def contribution_strip() -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.foreach(
                AppState.components,
                lambda c: rx.tooltip(
                    rx.box(height="100%", width=c.contribution.to_string() + "%", background=rx.color(component_color(c.key), 9)),
                    content=c.label + ": " + c.contribution.to_string() + " points of the final score",
                ),
            ),
            rx.box(height="100%", flex="1", background=rx.color("gray", 4)),
            width="100%",
            height="10px",
            border_radius="999px",
            overflow="hidden",
        ),
        rx.flex(
            rx.foreach(
                AppState.components,
                lambda c: rx.hstack(
                    rx.box(width="8px", height="8px", border_radius="2px", background=rx.color(component_color(c.key), 9)),
                    rx.text(c.label, size="1", color_scheme="gray"),
                    spacing="1",
                    align="center",
                ),
            ),
            wrap="wrap",
            spacing="3",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def match_section() -> rx.Component:
    return rx.vstack(
        page_header("Match results", "Every number traceable to a component, with its weight."),
        rx.cond(
            AppState.has_result,
            rx.vstack(
                rx.grid(
                    card(
                        rx.hstack(
                            donut(AppState.final_score.to_string(), "out of 100", AppState.score_ring_css),
                            rx.vstack(
                                rx.badge(AppState.verdict, color_scheme=AppState.verdict_color, variant="solid", size="2", radius="full"),
                                rx.text(AppState.selected_jd_label, size="3", weight="bold"),
                                rx.text(AppState.selected_resume_label, size="1", color_scheme="gray"),
                                rx.hstack(
                                    rx.badge(AppState.matched_required.length().to_string() + " matched", color_scheme="grass", variant="soft", radius="full"),
                                    rx.badge(AppState.missing_required.length().to_string() + " missing", color_scheme="tomato", variant="soft", radius="full"),
                                    rx.badge(
                                        AppState.keyword_matched.to_string() + "/" + AppState.keyword_total.to_string() + " keywords",
                                        color_scheme="cyan", variant="soft", radius="full",
                                    ),
                                    spacing="2",
                                    wrap="wrap",
                                    margin_top="0.4em",
                                ),
                                spacing="1",
                                align="start",
                            ),
                            spacing="4",
                            align="center",
                            wrap="wrap",
                            width="100%",
                        ),
                    ),
                    card(
                        card_title("Breakdown", "layers", "Components with no signal are dropped and the rest renormalised"),
                        contribution_strip(),
                        rx.divider(),
                        rx.foreach(AppState.components, component_row),
                        rx.cond(
                            AppState.dropped.length() > 0,
                            empty_hint("Dropped, no signal in this pair: " + AppState.dropped.join(", "), "minus-circle"),
                            rx.fragment(),
                        ),
                        rx.cond(AppState.title_note != "", empty_hint(AppState.title_note, "id-card"), rx.fragment()),
                        rx.cond(AppState.experience_note != "", empty_hint(AppState.experience_note, "calendar"), rx.fragment()),
                    ),
                    columns=rx.breakpoints(initial="1", lg="2"),
                    spacing="4",
                    width="100%",
                ),
                rx.grid(
                    card(
                        card_title("Skills", "list-checks", "Required vs nice-to-have, read from the posting's headings"),
                        rx.text("Matched — required", size="2", weight="medium"),
                        chips(AppState.matched_required, "grass", "None of the required skills matched.", "check"),
                        rx.text("Missing — required", size="2", weight="medium"),
                        chips(AppState.missing_required, "tomato", "Nothing required is missing.", "x"),
                        rx.text("Matched — nice to have", size="2", weight="medium"),
                        chips(AppState.matched_preferred, "grass", "—", "check"),
                        rx.text("Missing — nice to have", size="2", weight="medium"),
                        chips(AppState.missing_preferred, "amber", "—", "x"),
                    ),
                    card(
                        card_title("Keywords", "text-search", "Distinctive posting terms found in the resume"),
                        rx.text(
                            AppState.keyword_matched.to_string() + " of " + AppState.keyword_total.to_string()
                            + " terms. Benefits, 'about us' and EEO sections are stripped first, so the query is the job, not the employer blurb.",
                            size="1",
                            color_scheme="gray",
                        ),
                        chips(AppState.keyword_terms, "cyan", "No matched terms.", "hash"),
                        rx.cond(
                            AppState.suggestions.length() > 0,
                            rx.vstack(
                                rx.text("Suggestions", size="2", weight="medium", margin_top="0.4em"),
                                rx.foreach(
                                    AppState.suggestions,
                                    lambda s: rx.hstack(
                                        rx.icon("lightbulb", size=13, color=rx.color("amber", 9), flex_shrink="0"),
                                        rx.text(s, size="1"),
                                        spacing="2",
                                        align="start",
                                        padding="0.6em",
                                        border_radius="8px",
                                        background=rx.color("amber", 2),
                                        width="100%",
                                    ),
                                ),
                                spacing="2",
                                width="100%",
                            ),
                            rx.fragment(),
                        ),
                    ),
                    columns=rx.breakpoints(initial="1", lg="2"),
                    spacing="4",
                    width="100%",
                ),
                card(
                    card_title("Gap analysis", "target", "Ordered by requirement, then by how often the posting repeats the term"),
                    rx.cond(
                        AppState.gaps.length() > 0,
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Skill"),
                                    rx.table.column_header_cell("Requirement"),
                                    rx.table.column_header_cell("Mentions"),
                                    rx.table.column_header_cell("Related skills you already have"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    AppState.gaps,
                                    lambda g: rx.table.row(
                                        rx.table.cell(rx.text(g.skill_name, size="2", weight="medium")),
                                        rx.table.cell(
                                            rx.badge(
                                                g.requirement,
                                                color_scheme=rx.cond(g.is_required, "tomato", "amber"),
                                                variant="soft",
                                                radius="full",
                                            )
                                        ),
                                        rx.table.cell(rx.text(g.mentions.to_string(), size="2")),
                                        rx.table.cell(
                                            rx.cond(
                                                g.adjacent != "",
                                                rx.text(g.adjacent, size="1"),
                                                rx.text("—", size="1", color_scheme="gray"),
                                            )
                                        ),
                                    ),
                                )
                            ),
                            variant="surface",
                            size="1",
                            width="100%",
                        ),
                        empty_hint("No gaps found for this posting."),
                    ),
                ),
                spacing="4",
                width="100%",
            ),
            card(
                rx.vstack(
                    rx.icon("target", size=26, color=rx.color(ACCENT, 8)),
                    rx.heading("No match scored yet", size="4"),
                    rx.text(
                        "Pick a resume and a posting, then score the pair. You'll get a weighted breakdown, matched and missing skills, and a gap list.",
                        size="2",
                        color_scheme="gray",
                        text_align="center",
                        max_width="32em",
                    ),
                    score_buttons("3"),
                    spacing="3",
                    align="center",
                    padding_y="2.5em",
                ),
            ),
        ),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------
# leaderboard
# ---------------------------------------------------------------------
def leaderboard_section() -> rx.Component:
    return rx.vstack(
        page_header("Leaderboard", "One resume against every stored posting, best first."),
        selection_bar(),
        rx.cond(
            AppState.leaderboard.length() > 0,
            card(
                card_title(
                    "Ranked postings", "trophy", "Rows appear as each posting finishes scoring",
                    trailing=rx.badge(AppState.leaderboard.length().to_string() + " scored", variant="surface", color_scheme="gray"),
                ),
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("#"),
                            rx.table.column_header_cell("Posting"),
                            rx.table.column_header_cell("Company"),
                            rx.table.column_header_cell("Score"),
                            rx.table.column_header_cell("Required skills"),
                            rx.table.column_header_cell("Verdict"),
                        )
                    ),
                    rx.table.body(
                        rx.foreach(
                            AppState.leaderboard,
                            lambda row, i: rx.table.row(
                                rx.table.cell(rx.text((i + 1).to_string(), size="1", color_scheme="gray")),
                                rx.table.cell(rx.text(row.title, size="2", weight="medium")),
                                rx.table.cell(rx.text(row.company, size="1", color_scheme="gray")),
                                rx.table.cell(
                                    rx.hstack(
                                        rx.text(row.score.to_string(), size="2", weight="bold", width="2.8em"),
                                        rx.progress(value=row.score.to(int), max=100, color_scheme=ACCENT, width="90px", height="6px"),
                                        spacing="2",
                                        align="center",
                                    )
                                ),
                                rx.table.cell(
                                    rx.hstack(
                                        rx.badge(row.matched.to_string(), color_scheme="grass", variant="soft", radius="full"),
                                        rx.badge(row.missing.to_string(), color_scheme="tomato", variant="soft", radius="full"),
                                        spacing="1",
                                    )
                                ),
                                rx.table.cell(rx.badge(row.verdict, color_scheme=row.verdict_color, variant="soft", radius="full")),
                            ),
                        )
                    ),
                    variant="surface",
                    size="1",
                    width="100%",
                ),
            ),
            card(
                rx.vstack(
                    rx.icon("trophy", size=26, color=rx.color(ACCENT, 8)),
                    rx.heading("Nothing ranked yet", size="4"),
                    rx.text(
                        "Scores this resume against every stored posting, one at a time. The first pass takes a couple of minutes against a remote database; later passes are much faster.",
                        size="2",
                        color_scheme="gray",
                        text_align="center",
                        max_width="34em",
                    ),
                    rx.button(
                        rx.icon("list-ordered", size=15),
                        "Rank all postings",
                        on_click=AppState.run_leaderboard,
                        disabled=AppState.busy | (AppState.resume_id == 0),
                        color_scheme=ACCENT,
                        size="3",
                    ),
                    spacing="3",
                    align="center",
                    padding_y="2.5em",
                ),
            ),
        ),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------
# page
# ---------------------------------------------------------------------
def index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.vstack(
                mobile_nav(),
                rx.cond(
                    AppState.error != "",
                    rx.callout(
                        AppState.error,
                        icon="triangle-alert",
                        color_scheme="tomato",
                        width="100%",
                        on_click=AppState.clear_error,
                        cursor="pointer",
                    ),
                    rx.fragment(),
                ),
                rx.match(
                    AppState.section,
                    ("overview", overview_section()),
                    ("resume", resume_section()),
                    ("postings", postings_section()),
                    ("match", match_section()),
                    ("leaderboard", leaderboard_section()),
                    overview_section(),
                ),
                spacing="4",
                width="100%",
                max_width="78em",
                align="stretch",
            ),
            padding=rx.breakpoints(initial="1.2em", md="2em"),
            width="100%",
            min_height="100vh",
            background=rx.color(SURFACE, 2),
        ),
        spacing="0",
        align="start",
        width="100%",
        on_mount=AppState.load_catalogues,
    )


app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color=ACCENT,
        gray_color=SURFACE,
        radius="large",
        panel_background="solid",
        scaling="100%",
    ),
)
app.add_page(index, route="/", title="Resume ↔ Job Matcher")
