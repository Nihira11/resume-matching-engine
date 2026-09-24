"""
Pull job postings, with their full text, from company job boards.

    python -m scripts.fetch_board_jds --out data/jds/board
    python -m scripts.fetch_board_jds --summary-only

Why not Adzuna, which is already wired up: its API truncates every
description at 500 characters -- mostly company blurb, with none of the
requirements the matcher scores against -- and its listing pages return
403 to scripted requests. Greenhouse, Lever and Ashby publish the whole
posting as JSON, which is what calibration needs.

Only employers who hire in Australia for the roles this project targets
(quant, data, AI, finance) plus, deliberately, roles that do not fit at
all: senior positions and unrelated fields. An evaluation set of only
plausible matches cannot show whether the engine separates anything.

Nothing is scored here and nothing is labelled -- this writes text files.
"""
from __future__ import annotations

import argparse
import html
import re
import time
from pathlib import Path

import httpx

HEADERS = {"User-Agent": "resume-matching-engine/0.1 (portfolio project)"}
TIMEOUT = 20

# (provider, board token, display name)
BOARDS = [
    ("greenhouse", "imc", "IMC Trading"),
    ("greenhouse", "janestreet", "Jane Street"),
    ("greenhouse", "akunacapital", "Akuna Capital"),
    ("greenhouse", "towerresearchcapital", "Tower Research Capital"),
    ("greenhouse", "squarepointcapital", "Squarepoint Capital"),
    ("greenhouse", "cultureamp", "Culture Amp"),
    ("greenhouse", "block", "Block"),
    ("greenhouse", "quantium", "Quantium"),
    ("greenhouse", "eucalyptus", "Eucalyptus"),
    ("greenhouse", "airtrunk", "AirTrunk"),
    ("greenhouse", "prospa", "Prospa"),
    ("greenhouse", "vivcourt", "VivCourt"),
    ("greenhouse", "octopusdeploy", "Octopus Deploy"),
    ("greenhouse", "kaluza", "Kaluza"),
    ("ashby", "airwallex", "Airwallex"),
    ("ashby", "zip", "Zip"),
    ("lever", "immutable", "Immutable"),
    ("lever", "deputy", "Deputy"),
    ("lever", "pexa", "PEXA"),
]

AUSTRALIA = re.compile(r"australia|sydney|melbourne|brisbane|perth|adelaide|canberra|\bnsw\b|\bvic\b", re.I)

ENTRY = re.compile(
    r"\b(intern|internship|graduate|grad\b|new grad|campus|entry[- ]level|junior|trainee|"
    r"analyst i\b|associate|placement|student|2026|2027)\b", re.I,
)
SENIOR = re.compile(r"\b(senior|staff|principal|lead|head of|director|manager|vp|vice president|chief)\b", re.I)

RELEVANT = re.compile(
    r"\b(quant|quantitative|data scien|data analy|analytics|machine learning|\bml\b|\bai\b|"
    r"artificial intelligence|research|risk|trading|trader|financ|actuar|statistic|"
    r"business analy|business intelligence|economi|python|software engineer)\b", re.I,
)
# fields the resume has no claim to -- the negative controls
UNRELATED = re.compile(
    r"\b(nurse|nursing|clinical|physician|pharmac|recruit|talent|people|culture|"
    r"marketing|brand|content|social media|sales|account executive|customer success|"
    r"customer support|legal|counsel|facilit|office manager|design|ux|ui|copywrit|community|"
    r"partnership|procurement|warehouse|driver|technician|electrician|construction)\b", re.I,
)


def strip_html(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"</(p|div|h[1-6]|ul|ol|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def fetch_greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    data = httpx.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    return [
        {
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "text": strip_html(j.get("content", "")),
            "url": j.get("absolute_url", ""),
        }
        for j in data.get("jobs", [])
    ]


def fetch_lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = httpx.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    out = []
    for j in data:
        body = j.get("descriptionPlain") or strip_html(j.get("description", ""))
        for section in j.get("lists", []):
            body += "\n\n" + strip_html(section.get("text", "")) + "\n" + strip_html(section.get("content", ""))
        out.append(
            {
                "title": j.get("text", ""),
                "location": (j.get("categories") or {}).get("location", ""),
                "text": body.strip(),
                "url": j.get("hostedUrl", ""),
            }
        )
    return out


def fetch_ashby(token: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    data = httpx.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    return [
        {
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "text": (j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))).strip(),
            "url": j.get("jobUrl", ""),
        }
        for j in data.get("jobs", [])
    ]


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def classify(job: dict) -> tuple[str, str]:
    """(level, domain) -- the axes the evaluation set needs to span."""
    title = job["title"]
    level = "senior" if SENIOR.search(title) else ("entry" if ENTRY.search(title) else "mid")
    # relevant wins a tie: "Options Quant Support Analyst" is a quant role
    # that happens to contain "support", and auto-labelling it unrelated
    # would have thrown away a posting the resume actually targets
    if RELEVANT.search(title):
        domain = "relevant"
    elif UNRELATED.search(title):
        domain = "unrelated"
    else:
        domain = "other"
    return level, domain


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def collect() -> list[dict]:
    jobs = []
    for provider, token, company in BOARDS:
        try:
            found = FETCHERS[provider](token)
        except Exception as exc:  # noqa: BLE001 -- a dead board shouldn't stop the run
            print(f"  {company}: failed ({type(exc).__name__})")
            continue
        kept = []
        for job in found:
            if not AUSTRALIA.search(job.get("location", "")):
                continue
            if len(job.get("text", "")) < 400:
                continue
            job["company"] = company
            job["level"], job["domain"] = classify(job)
            kept.append(job)
        print(f"  {company:24} {len(kept):3} Australian postings (of {len(found)})")
        jobs.extend(kept)
        time.sleep(0.4)  # be polite to public endpoints
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch full-text job postings from company boards.")
    parser.add_argument("--out", type=Path, default=Path("data/jds/board"))
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    print("Fetching boards…")
    jobs = collect()

    buckets: dict[tuple[str, str], list[dict]] = {}
    for job in jobs:
        buckets.setdefault((job["level"], job["domain"]), []).append(job)

    print(f"\n{len(jobs)} Australian postings with full text")
    for key in sorted(buckets):
        print(f"  {key[0]:7} / {key[1]:10} {len(buckets[key]):3}")

    if args.summary_only:
        return

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for job in jobs:
        name = f"{slug(job['company'])}__{job['level']}_{job['domain']}__{slug(job['title'])}.txt"
        body = f"{job['title']}\n{job['company']}\n{job['location']}\n{job.get('url', '')}\n\n{job['text']}"
        (args.out / name).write_text(body, encoding="utf-8")
        written += 1
    print(f"\nwrote {written} files to {args.out}")


if __name__ == "__main__":
    main()
