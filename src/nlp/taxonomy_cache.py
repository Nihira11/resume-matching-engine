"""
Local cache of skills_taxonomy rows.

The matcher needs every skill name and alias -- 14k rows, ~10MB with the
alias arrays -- and pulling them from the hosted database took 8.8 of the
13 seconds it cost to build the PhraseMatcher, every time a process
started. The rows change only when a loader script runs.

Validated rather than trusted: a signature query (row count + highest id +
newest alias change is not tracked, so count and max id) is one round trip,
and the cache is rebuilt when it disagrees. A stale cache would silently
score against an old taxonomy, which is worse than the 8 seconds.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.utils.db import get_connection

CACHE_PATH = Path("data/processed/skills_taxonomy_cache.json")


def _signature() -> list[int]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*), COALESCE(max(skill_id), 0) FROM skills_taxonomy")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return [int(row[0]), int(row[1])]


def _fetch_rows() -> list[tuple]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT skill_id, skill_name, aliases, source FROM skills_taxonomy")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def load_taxonomy_rows(use_cache: bool = True) -> list[tuple]:
    """(skill_id, skill_name, aliases, source) for every taxonomy row."""
    if not use_cache:
        return _fetch_rows()

    signature = _signature()
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if cached.get("signature") == signature:
                return [
                    (r[0], r[1], r[2], r[3]) for r in cached["rows"]
                ]
        except (json.JSONDecodeError, KeyError, TypeError, IndexError):
            pass  # unreadable cache is just a cache miss

    rows = _fetch_rows()
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps({"signature": signature, "rows": [list(r) for r in rows]})
        )
    except OSError:
        pass  # a read-only data dir shouldn't break extraction
    return rows


def clear_cache() -> None:
    CACHE_PATH.unlink(missing_ok=True)
