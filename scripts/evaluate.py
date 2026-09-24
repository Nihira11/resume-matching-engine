"""
Score the evaluation set and measure whether the blend separates anything.

    python -m scripts.evaluate --score          # run matches, write scores.csv
    python -m scripts.evaluate                  # report from the stored scores

Two kinds of evidence, because human labels are scarce and opinions are
one person's:

1. Structural controls, which need no labelling. A graduate data resume
   should outscore a chef's resume on a data posting, and should lose to
   nobody in particular on a nursing posting. That gives a ranking task
   with a known answer for every pair, built from the level/domain of the
   posting and the field of each contrast resume.

2. Human labels (data/eval/labels.csv), when filled in: good / maybe / no.
   These are what the verdict thresholds should actually be set against,
   since "would you apply for this" is the question the tool claims to
   answer.

Reported, never assumed: if the controls fail, the weights are wrong, and
no threshold fixes that.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from resume_matcher import service  # noqa: E402
from src.utils.db import connection  # noqa: E402

SCORES_PATH = Path("data/eval/scores.csv")
LABELS_PATH = Path("data/eval/labels.csv")

# The resume under test, and deliberate mismatches from other fields.
PRIMARY_RESUME = 7
CONTRAST_RESUMES = {8: "healthcare", 9: "sales", 10: "chef", 11: "finance director", 12: "IT director"}

COMPONENTS = ["skill_overlap", "keyword_bm25", "title_seniority", "experience", "semantic"]


# ---------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------
def score_all(resume_ids: list[int]) -> list[dict]:
    with connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT jd_id, title, company FROM job_descriptions ORDER BY jd_id")
        postings = cur.fetchall()

    rows = []
    total = len(resume_ids) * len(postings)
    done = 0
    for resume_id in resume_ids:
        for jd_id, title, company in postings:
            view = service.score_pair(resume_id, jd_id)
            by_key = {c["key"]: c["score"] for c in view["components"]}
            rows.append(
                {
                    "resume_id": resume_id,
                    "jd_id": jd_id,
                    "title": title or "",
                    "company": company or "",
                    "final": view["final_score"],
                    **{k: by_key.get(k, "") for k in COMPONENTS},
                    "matched_required": len(view["matched_required"]),
                    "missing_required": len(view["missing_required"]),
                }
            )
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{total} pairs scored")
    return rows


def write_scores(rows: list[dict]) -> None:
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = ["resume_id", "jd_id", "title", "company", "final", *COMPONENTS,
              "matched_required", "missing_required"]
    with SCORES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {SCORES_PATH}")


def read_scores() -> list[dict]:
    if not SCORES_PATH.exists():
        sys.exit(f"{SCORES_PATH} not found — run with --score first")
    with SCORES_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["resume_id"] = int(row["resume_id"])
        row["jd_id"] = int(row["jd_id"])
        for key in ["final", *COMPONENTS]:
            row[key] = float(row[key]) if row[key] not in ("", None) else None
    return rows


def read_labels() -> dict[int, dict]:
    if not LABELS_PATH.exists():
        return {}
    with LABELS_PATH.open(newline="", encoding="utf-8") as handle:
        return {int(r["jd_id"]): r for r in csv.DictReader(handle)}


# ---------------------------------------------------------------------
# statistics, written out rather than imported: the point is to show the
# measure, and each is a few lines
# ---------------------------------------------------------------------
def auc(positive: list[float], negative: list[float]) -> float | None:
    """P(a random positive scores above a random negative). 0.5 = no signal."""
    if not positive or not negative:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None

    def rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = shared
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def best_threshold(positive: list[float], negative: list[float]) -> tuple[float, float]:
    """Cut-off maximising Youden's J (sensitivity + specificity - 1)."""
    candidates = sorted({*positive, *negative})
    best, best_j = 0.0, -1.0
    for cut in candidates:
        tpr = sum(p >= cut for p in positive) / len(positive)
        fpr = sum(n >= cut for n in negative) / len(negative)
        j = tpr - fpr
        if j > best_j:
            best, best_j = cut, j
    return best, best_j


# ---------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------
def report_structural(rows: list[dict], labels: dict[int, dict]) -> None:
    print("\n=== Structural controls (no human labels needed) ===")
    primary = [r for r in rows if r["resume_id"] == PRIMARY_RESUME]
    if not primary:
        print("  no rows for the primary resume")
        return

    buckets: dict[str, list[float]] = {}
    for row in primary:
        meta = labels.get(row["jd_id"])
        if not meta:
            continue
        buckets.setdefault(f"{meta['level']}/{meta['domain']}", []).append(row["final"])
    print("\n  mean final score by posting type (primary resume):")
    for key in sorted(buckets):
        values = buckets[key]
        print(f"    {key:18} n={len(values):2}  mean {sum(values)/len(values):5.1f}  "
              f"range {min(values):4.1f}-{max(values):4.1f}")

    relevant = [v for k, vals in buckets.items() if "relevant" in k for v in vals]
    unrelated = [v for k, vals in buckets.items() if "unrelated" in k for v in vals]
    separation = auc(relevant, unrelated)
    if separation is not None:
        print(f"\n  relevant vs unrelated postings: AUC {separation:.2f} "
              f"({'good' if separation > 0.8 else 'weak' if separation > 0.6 else 'no signal'})")

    print("\n  does the right resume win each posting? (primary vs contrast resumes)")
    wins = contested = 0
    for jd_id in sorted({r["jd_id"] for r in rows}):
        meta = labels.get(jd_id)
        if not meta or meta["domain"] != "relevant":
            continue
        contested += 1
        pair = {r["resume_id"]: r["final"] for r in rows if r["jd_id"] == jd_id}
        if PRIMARY_RESUME not in pair:
            continue
        if pair[PRIMARY_RESUME] >= max(v for k, v in pair.items() if k != PRIMARY_RESUME):
            wins += 1
    if contested:
        print(f"    primary resume ranks first on {wins}/{contested} relevant postings "
              f"({wins/contested:.0%})")

    print("\n  contrast resumes on unrelated postings (they should win these):")
    for resume_id, field in CONTRAST_RESUMES.items():
        mine, theirs = [], []
        for jd_id in sorted({r["jd_id"] for r in rows}):
            meta = labels.get(jd_id)
            if not meta or meta["domain"] != "unrelated":
                continue
            scores = {r["resume_id"]: r["final"] for r in rows if r["jd_id"] == jd_id}
            if PRIMARY_RESUME in scores and resume_id in scores:
                mine.append(scores[PRIMARY_RESUME])
                theirs.append(scores[resume_id])
        if theirs:
            better = sum(t > m for t, m in zip(theirs, mine))
            print(f"    {field:16} beats the data resume on {better}/{len(theirs)} unrelated postings")


def report_labels(rows: list[dict], labels: dict[int, dict]) -> None:
    filled = {jd: meta for jd, meta in labels.items() if meta.get("label", "").strip()}
    print(f"\n=== Human labels ({len(filled)} of {len(labels)} postings labelled) ===")
    if len(filled) < 8:
        print("  not enough labels yet — fill data/eval/labels.csv with good / maybe / no")
        return

    primary = {r["jd_id"]: r for r in rows if r["resume_id"] == PRIMARY_RESUME}
    scale = {"good": 2, "maybe": 1, "no": 0}
    pairs = [
        (primary[jd]["final"], scale[meta["label"].strip().lower()])
        for jd, meta in filled.items()
        if jd in primary and meta["label"].strip().lower() in scale
    ]
    if not pairs:
        print("  labels present but no scores for them")
        return

    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    print(f"  rank correlation with your judgement: rho = {rho:.2f}" if rho is not None else "")

    good = [s for s, l in pairs if l == 2]
    no = [s for s, l in pairs if l == 0]
    separation = auc(good, no)
    if separation is not None:
        print(f"  'good' vs 'no' separation: AUC {separation:.2f}")
        cut, j = best_threshold(good, no)
        print(f"  best single cut-off: {cut:.1f} (Youden J {j:.2f})")

    print("\n  per-component AUC (which signal actually tracks your judgement):")
    for key in COMPONENTS:
        g = [r["final"] and r[key] for jd, r in primary.items()
             if jd in filled and filled[jd]["label"].strip().lower() == "good" and r[key] is not None]
        n = [r[key] for jd, r in primary.items()
             if jd in filled and filled[jd]["label"].strip().lower() == "no" and r[key] is not None]
        value = auc([x for x in g if x is not None], n)
        print(f"    {key:16} {'n/a' if value is None else f'{value:.2f}'}")

    print("\n  biggest disagreements:")
    ranked = sorted(pairs, key=lambda p: p[0], reverse=True)
    for jd, meta in sorted(filled.items(), key=lambda kv: primary.get(kv[0], {}).get("final", 0), reverse=True):
        if jd not in primary:
            continue
        label = meta["label"].strip().lower()
        score = primary[jd]["final"]
        if (label == "no" and score > (ranked[len(ranked)//3][0] if ranked else 0)) or (
            label == "good" and score < (ranked[-len(ranked)//3][0] if ranked else 100)
        ):
            print(f"    {score:5.1f}  labelled '{label:5}'  {meta['title'][:52]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate and calibrate the matching engine.")
    parser.add_argument("--score", action="store_true", help="re-run all matches")
    parser.add_argument("--resumes", type=int, nargs="*", default=None)
    args = parser.parse_args()

    if args.score:
        resume_ids = args.resumes or [PRIMARY_RESUME, *CONTRAST_RESUMES]
        print(f"scoring resumes {resume_ids} against every stored posting…")
        write_scores(score_all(resume_ids))

    rows = read_scores()
    labels = read_labels()
    report_structural(rows, labels)
    report_labels(rows, labels)


if __name__ == "__main__":
    main()
