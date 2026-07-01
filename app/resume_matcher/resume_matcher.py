"""
Reflex entrypoint. Run with: reflex run (from the app/ directory)
"""
import reflex as rx
from .state import AppState


def index() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.heading("Resume-Job Matching System", size="8"),
            rx.text("Pipeline not yet connected.", color="gray"),
            spacing="4",
            padding="4em",
        ),
        height="100vh",
    )


app = rx.App()
app.add_page(index, route="/", title="Resume Matcher")
