"""
Derive the ESCO skill-adjacency map and commit it, gzipped.

    python -m scripts.build_adjacency_cache

Needs the two ESCO CSVs in data/taxonomy/. Re-run whenever they change or
MIN_ADJACENCY_CO_OCCURRENCES moves; the output is committed, so the
result of this script -- not its inputs -- is what ships.

Why the derived map rather than the CSVs: the relations file is 26.7MB,
which is over Reflex Cloud's 25MiB per-file limit, and both CSVs are
gitignored under ESCO's licence terms. Every deployment therefore lost the
"related skills" suggestions without saying anything, because
_load_adjacency() returns an empty map when the files are missing. The
gzipped map is 3.9MB, loads in 0.26s against 1.7s to parse the CSVs, and
is byte-identical.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from src.matching.config import ESCO_ADJACENCY_CACHE_PATH, ESCO_RELATIONS_PATH, ESCO_SKILLS_PATH


def main() -> None:
    for path in (ESCO_SKILLS_PATH, ESCO_RELATIONS_PATH):
        if not Path(path).exists():
            raise SystemExit(
                f"missing {path}\n"
                "The ESCO CSVs are gitignored; download them into data/taxonomy/ "
                "before rebuilding the cache (see docs/DATASETS.md)."
            )

    # imported here so the missing-file check above runs first, and so the
    # cache being absent cannot make this script read its own output
    from src.matching import gap_analysis

    gap_analysis._adjacency = None
    cache_path = Path(ESCO_ADJACENCY_CACHE_PATH)
    if cache_path.exists():
        cache_path.unlink()

    adjacency = gap_analysis._load_adjacency()
    if not adjacency:
        raise SystemExit("adjacency map came out empty -- check the CSVs")

    payload = json.dumps(adjacency, separators=(",", ":")).encode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache_path, "wb", compresslevel=6) as handle:
        handle.write(payload)

    size = cache_path.stat().st_size
    print(f"{len(adjacency)} labels, {len(payload) / 1_000_000:.1f}MB raw "
          f"-> {size / 1_000_000:.1f}MB at {cache_path}")

    # read it back the way the app will, so a broken write fails here
    gap_analysis._adjacency = None
    reloaded = gap_analysis._load_adjacency()
    if reloaded != adjacency:
        raise SystemExit("cache did not round-trip -- not writing it off as fine")
    print("round-trip verified against the CSV-derived map")


if __name__ == "__main__":
    main()
