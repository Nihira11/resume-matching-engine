"""
Remove the parts of a job posting that describe the employer, not the job.

Real postings are often half boilerplate: company history, benefits,
privacy notices, EEO statements. None of it says anything about whether a
candidate fits, but all of it gets scored. BM25 ranks query terms by
rarity, so "carers" and "parental" out-rank "sql"; the semantic score
averages over JD chunks, so a benefits chunk no resume covers pulls every
candidate down equally.

Section-based, like split_requirement_sections: a boilerplate heading
switches mode until a content heading switches it back. Text before any
heading is kept, since the role summary usually sits there.
"""
from __future__ import annotations

import re

from src.matching.config import (
    JD_BOILERPLATE_HEADING_MARKERS,
    JD_BOILERPLATE_LINE_PATTERN,
    JD_CONTENT_HEADING_MARKERS,
)

_BOILERPLATE_LINE_RE = re.compile(JD_BOILERPLATE_LINE_PATTERN, re.IGNORECASE)
# "About Mistral", "About GloBird Energy" -- but not "About the role",
# "About you" or "About the job"
_ABOUT_EMPLOYER_RE = re.compile(r"^about\b(?!.*\b(?:role|you|job|position|team)\b)")
_HEADING_MAX_CHARS = 60


def heading_kind(line: str) -> str | None:
    """'boilerplate', 'content', or None if the line isn't a heading."""
    stripped = line.strip().rstrip(":").strip()
    if not stripped or len(stripped) > _HEADING_MAX_CHARS or stripped.endswith("."):
        return None
    lowered = stripped.lower()
    if (
        any(marker in lowered for marker in JD_BOILERPLATE_HEADING_MARKERS)
        or lowered.startswith("why ")
        or _ABOUT_EMPLOYER_RE.match(lowered)
    ):
        return "boilerplate"
    if any(marker in lowered for marker in JD_CONTENT_HEADING_MARKERS):
        return "content"
    return None


def strip_boilerplate(text: str) -> str:
    """JD text with employer-description sections and EEO lines removed.

    Falls back to the original text if stripping would leave nothing -- a
    posting that is all boilerplate by this measure is more likely a
    heading-detection miss than a real empty job.
    """
    if not text:
        return ""
    kept: list[str] = []
    in_boilerplate = False
    for line in text.splitlines():
        kind = heading_kind(line)
        if kind is not None:
            in_boilerplate = kind == "boilerplate"
        if not in_boilerplate and not _BOILERPLATE_LINE_RE.search(line):
            kept.append(line)
    result = "\n".join(kept)
    return result if result.strip() else text
