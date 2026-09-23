import sys
from pathlib import Path

import reflex as rx

# Reflex runs with app/ as the working directory, but the UI imports the
# pipeline from src/ in the repo root. Same interpreter, one path entry --
# cheaper than packaging src/ just to satisfy the dev server.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

config = rx.Config(
    app_name="resume_matcher",
)
