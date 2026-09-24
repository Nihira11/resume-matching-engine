"""
Assemble the calibration evaluation set from fetched board postings.

    python -m scripts.build_eval_set --dry-run
    python -m scripts.build_eval_set

Picks a stratified sample across (level, domain) rather than the postings
that look most promising. A set of plausible matches can only show that
scores are high; it cannot show the engine separates anything. The
senior and unrelated buckets are the controls -- if a graduate data
resume does not score below a nursing manager posting, the blend is
broken regardless of how good the top of the ranking looks.

Ingests each posting and writes data/eval/labels.csv, which is the sheet
a human fills in. The tool's own scores are never written there: the
whole point is an opinion formed independently of them.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from src.ingestion.jd_pipeline import run as ingest_jd
from src.utils.db import connection

# (level, domain) -> how many to take. Weighted towards what the resume
# plausibly targets, with enough controls to measure separation.
QUOTAS = {
    ("entry", "relevant"): 3,
    ("entry", "other"): 2,
    ("mid", "relevant"): 10,
    ("mid", "other"): 2,
    ("senior", "relevant"): 6,
    ("mid", "unrelated"): 4,
    ("senior", "unrelated"): 5,
}

LABELS_PATH = Path("data/eval/labels.csv")


def parse(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = lines[0].strip() if lines else path.stem
    company = lines[1].strip() if len(lines) > 1 else ""
    location = lines[2].strip() if len(lines) > 2 else ""
    url = lines[3].strip() if len(lines) > 3 else ""
    parts = path.stem.split("__")
    level, domain = (parts[1].split("_", 1) if len(parts) > 2 else ("mid", "other"))
    return {
        "path": path,
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "level": level,
        "domain": domain,
        "text": path.read_text(encoding="utf-8"),
    }


def select(folder: Path, seed: int = 20260924) -> list[dict]:
    jobs = [parse(p) for p in sorted(folder.glob("*.txt"))]
    buckets: dict[tuple[str, str], list[dict]] = {}
    for job in jobs:
        buckets.setdefault((job["level"], job["domain"]), []).append(job)

    rng = random.Random(seed)
    chosen: list[dict] = []
    for key, quota in QUOTAS.items():
        pool = buckets.get(key, [])
        rng.shuffle(pool)
        # one posting per company per bucket: four near-identical Airwallex
        # roles would measure the same thing four times
        seen_companies: set[str] = set()
        for job in pool:
            if len(chosen) and sum(1 for c in chosen if (c["level"], c["domain"]) == key) >= quota:
                break
            if job["company"] in seen_companies:
                continue
            seen_companies.add(job["company"])
            chosen.append(job)
    return chosen


def already_loaded() -> set[str]:
    with connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT source_url FROM job_descriptions WHERE source_url IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the calibration evaluation set.")
    parser.add_argument("--folder", type=Path, default=Path("data/jds/board"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chosen = select(args.folder)
    print(f"selected {len(chosen)} postings\n")
    for job in chosen:
        print(f"  {job['level']:7} {job['domain']:10} {job['company'][:18]:18} {job['title'][:52]}")
    if args.dry_run:
        return

    loaded = already_loaded()
    rows = []
    for job in chosen:
        if job["url"] and job["url"] in loaded:
            print(f"  skip (already loaded): {job['title'][:50]}")
            continue
        jd_id = ingest_jd(
            job["text"],
            title=job["title"],
            company=job["company"],
            location=job["location"],
            source="job_board",
            source_url=job["url"],
        )
        rows.append(
            {
                "jd_id": jd_id,
                "title": job["title"],
                "company": job["company"],
                "level": job["level"],
                "domain": job["domain"],
                "url": job["url"],
                "label": "",
            }
        )

    print(f"\ningested {len(rows)} new postings")
    write_labels_sheet()


def write_labels_sheet() -> None:
    """One row per stored posting, including any loaded earlier.

    Existing labels are preserved: re-running after new postings arrive
    should not ask for judgements already given.
    """
    from scripts.fetch_board_jds import classify

    existing: dict[str, str] = {}
    existing_sources: dict[str, str] = {}
    if LABELS_PATH.exists():
        with LABELS_PATH.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                existing[row["jd_id"]] = row.get("label", "")
                existing_sources[row["jd_id"]] = row.get("label_source", "")

    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT jd_id, title, company, source_url FROM job_descriptions ORDER BY jd_id"
        )
        postings = cur.fetchall()

    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["jd_id", "title", "company", "level", "domain", "url", "label", "label_source"],
        )
        writer.writeheader()
        for jd_id, title, company, url in postings:
            level, domain = classify({"title": title or ""})
            label = existing.get(str(jd_id), "")
            source = existing_sources.get(str(jd_id), "")
            if not label and domain == "unrelated":
                # A data-science student is not a plausible hire for a nurse
                # practitioner or a field sales manager. Pre-filling these
                # costs nothing to verify and saves the labeller 9 of 40
                # judgements -- but it is recorded as 'auto', and the
                # headline metrics are reported on human labels alone so
                # the easy cases cannot inflate them.
                label, source = "no", "auto"
            writer.writerow(
                {
                    "jd_id": jd_id,
                    "title": title or "",
                    "company": company or "",
                    "level": level,
                    "domain": domain,
                    "url": url or "",
                    "label": label,
                    "label_source": source,
                }
            )
    print(f"labelling sheet: {LABELS_PATH} ({len(postings)} postings)")
    print("fill the 'label' column with: good / maybe / no")
    print("rows pre-filled 'no' (label_source=auto) are unrelated fields — correct any you disagree with")


if __name__ == "__main__":
    main()
