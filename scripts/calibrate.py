"""
Search weights and verdict thresholds against the labelled evaluation set.

    python -m scripts.calibrate

Works offline from data/eval/scores.csv: the per-component scores are
already stored, so a candidate weighting is just a re-blend, and hundreds
can be compared without touching the database or the models.

Two guards against fooling ourselves on 40 postings:

* Leave-one-out cross-validation. A weighting chosen on all 40 and scored
  on all 40 will always look better than it is. Every reported figure is
  from folds where the held-out posting took no part in the choice.
* A coarse grid, not a fitted model. With this few labels, five free
  parameters can memorise the set. The grid moves weights in steps of
  0.05 around the current values, and the recommendation is only taken
  when it beats the current weights by a clear margin.
"""
from __future__ import annotations

import csv
import itertools
from pathlib import Path

SCORES_PATH = Path("data/eval/scores.csv")
LABELS_PATH = Path("data/eval/labels.csv")
PRIMARY_RESUME = 7
COMPONENTS = ["skill_overlap", "keyword_bm25", "title_seniority", "experience", "semantic"]
CURRENT = {"skill_overlap": 0.40, "keyword_bm25": 0.15, "title_seniority": 0.15,
           "experience": 0.10, "semantic": 0.20}


def load() -> list[dict]:
    labels = {int(r["jd_id"]): r for r in csv.DictReader(LABELS_PATH.open())}
    rows = []
    for row in csv.DictReader(SCORES_PATH.open()):
        if int(row["resume_id"]) != PRIMARY_RESUME:
            continue
        jd_id = int(row["jd_id"])
        meta = labels.get(jd_id)
        if not meta or not meta["label"].strip():
            continue
        rows.append(
            {
                "jd_id": jd_id,
                "label": meta["label"].strip().lower(),
                "label_source": meta.get("label_source", ""),
                "title": meta["title"],
                "components": {
                    k: (float(row[k]) / 100 if row[k] not in ("", None) else None)
                    for k in COMPONENTS
                },
            }
        )
    return rows


def blend(components: dict[str, float | None], weights: dict[str, float]) -> float:
    present = {k: v for k, v in components.items() if v is not None}
    total = sum(weights[k] for k in present)
    if not present or total == 0:
        return 0.0
    return 100 * sum(v * weights[k] / total for k, v in present.items())


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return 0.5
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def label_auc(rows: list[dict], weights: dict[str, float]) -> float:
    good = [blend(r["components"], weights) for r in rows if r["label"] == "good"]
    no = [blend(r["components"], weights) for r in rows if r["label"] == "no"]
    return auc(good, no)


def ranked_auc(rows: list[dict], weights: dict[str, float]) -> float:
    """good+maybe above no -- the full ordering, not just the extremes."""
    yes = [blend(r["components"], weights) for r in rows if r["label"] in ("good", "maybe")]
    no = [blend(r["components"], weights) for r in rows if r["label"] == "no"]
    return auc(yes, no)


def candidates(title_cap: float = 1.0) -> list[dict[str, float]]:
    """Coarse grid around the current weights, normalised to sum to 1.

    title_cap exists because title/seniority separates the labels
    perfectly (AUC 1.00), and that number cannot be taken at face value:
    the labels were drafted with "senior role -> no" as a rule of thumb,
    so the component is partly predicting the labelling procedure rather
    than the candidate's fit. Letting the search lean on it would bake
    that circularity into the shipped weights.
    """
    options = {
        "skill_overlap": [0.30, 0.40, 0.50],
        "keyword_bm25": [0.05, 0.10, 0.15],
        "title_seniority": [0.10, 0.15, 0.20],
        "experience": [0.05, 0.10],
        "semantic": [0.15, 0.20, 0.25],
    }
    out = []
    for combo in itertools.product(*options.values()):
        weights = dict(zip(options, combo))
        total = sum(weights.values())
        normalised = {k: v / total for k, v in weights.items()}
        if normalised["title_seniority"] <= title_cap + 1e-9:
            out.append(normalised)
    return out


def best_thresholds(rows: list[dict], weights: dict[str, float]) -> tuple[float, float]:
    """(pass, borderline): pass separates good from the rest, borderline
    separates anything worth a look from the clear noes."""
    scored = [(blend(r["components"], weights), r["label"]) for r in rows]
    values = sorted({round(s, 1) for s, _ in scored})

    def youden(cut: float, positive: set[str]) -> float:
        pos = [s for s, l in scored if l in positive]
        neg = [s for s, l in scored if l not in positive]
        if not pos or not neg:
            return -1
        return sum(s >= cut for s in pos) / len(pos) - sum(s >= cut for s in neg) / len(neg)

    pass_cut = max(values, key=lambda c: youden(c, {"good"}))
    # the borderline band has to sit strictly below the pass mark, or
    # "borderline" is an empty category that never fires
    lower = [v for v in values if v < pass_cut] or [pass_cut]
    borderline_cut = max(lower, key=lambda c: youden(c, {"good", "maybe"}))
    return pass_cut, borderline_cut


def loo_threshold_quality(rows: list[dict], weights: dict[str, float]) -> float:
    """Accuracy of the pass/borderline bands under leave-one-out."""
    correct = 0
    for i in range(len(rows)):
        train = rows[:i] + rows[i + 1:]
        pass_cut, border_cut = best_thresholds(train, weights)
        score = blend(rows[i]["components"], weights)
        predicted = "good" if score >= pass_cut else ("maybe" if score >= border_cut else "no")
        correct += predicted == rows[i]["label"]
    return correct / len(rows)


def main() -> None:
    rows = load()
    reviewed = [r for r in rows if r["label_source"] == "reviewed"]
    print(f"{len(rows)} labelled postings ({len(reviewed)} human-reviewed, "
          f"{len(rows) - len(reviewed)} auto-filled unrelated fields)\n")

    print("current weights:")
    print(f"  good-vs-no AUC        {label_auc(rows, CURRENT):.3f}")
    print(f"  (good+maybe)-vs-no    {ranked_auc(rows, CURRENT):.3f}")
    print(f"  human-reviewed only   {label_auc(reviewed, CURRENT):.3f}")
    pass_cut, border_cut = best_thresholds(rows, CURRENT)
    print(f"  thresholds from data  pass {pass_cut:.0f} / borderline {border_cut:.0f}"
          f"   (shipped: 70 / 45)")
    print(f"  LOO band accuracy     {loo_threshold_quality(rows, CURRENT):.0%}")

    current_value = (ranked_auc(rows, CURRENT) + label_auc(rows, CURRENT)) / 2
    for label, cap in (("unconstrained", 1.0), ("title capped at 0.15", 0.15)):
        print(f"\nsearching weights ({label})…")
        scored = sorted(
            (((ranked_auc(rows, w) + label_auc(rows, w)) / 2, index, w)
             for index, w in enumerate(candidates(cap))),
            key=lambda item: item[0],
        )
        best_value, _, best_weights = scored[-1]
        print(f"  best {best_value:.3f} vs current {current_value:.3f}")
        print("  weights: " + ", ".join(f"{k} {v:.2f}" for k, v in best_weights.items()))
        print(f"  LOO band accuracy: {loo_threshold_quality(rows, best_weights):.0%}"
              f"  (current weights: {loo_threshold_quality(rows, CURRENT):.0%})")
        pass_cut, border_cut = best_thresholds(rows, best_weights)
        print(f"  thresholds: pass {pass_cut:.0f} / borderline {border_cut:.0f}")
        if best_value - current_value < 0.02:
            print("  -> margin under 2 points: not worth re-tuning on 40 postings.")

    print("\nper-component, on its own (good vs no):")
    for key in COMPONENTS:
        solo = {k: (1.0 if k == key else 0.0) for k in COMPONENTS}
        print(f"  {key:16} {label_auc(rows, solo):.2f}")


if __name__ == "__main__":
    main()
