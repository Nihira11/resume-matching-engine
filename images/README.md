# Screenshots

The Streamlit UI, captured 28 Sep 2026. All eight are used in the main
[`README.md`](../README.md) — this table records where each one sits and
what it is evidence of, so a retake can be dropped in without
re-deriving the captions.

| File | Used in the README under | Shows |
|---|---|---|
| [`01-overview-empty.png`](01-overview-empty.png) | "Getting it running" | The landing page with nothing loaded: two-click sample loaders, the session-scope notice, and what the five components measure. |
| [`02-overview-loaded.png`](02-overview-loaded.png) | "Getting it running" | The same page once samples are in: resume and posting selectors, Score / Rank buttons, session tiles. |
| [`03-resume-parsability.png`](03-resume-parsability.png) | "What the parser actually read" | Page one of the resume beside what the parser got out of it — 100/100 parsability, 42 skills, two job titles. |
| [`04-job-posting.png`](04-job-posting.png) | "Postings are read, not just pasted" | A posting split into 19 required and 9 nice-to-have skills by its own headings, with the original text kept beside them. |
| [`05-match-score.png`](05-match-score.png) | lead image, top of the README | 67.5 blended, **Strong fit**, with every component, weight and contribution. Experience was dropped (the posting states no minimum) and the weights renormalised — hence 44/22/17/17. |
| [`06-match-gaps.png`](06-match-gaps.png) | "Where the gaps are" | Missing skills by requirement then mention count, related skills the candidate already has, and the conditional suggestions. |
| [`07-leaderboard-clean-resume.png`](07-leaderboard-clean-resume.png) | "Ranked against every stored posting" | The ATS-clean resume against three postings: 67.5 / 56.0 / 39.9, all likely pass. |
| [`08-leaderboard-table-resume.png`](08-leaderboard-table-resume.png) | "It rejects things too" | The table-and-photo resume against the same three: 48.7 pass, 18.1 and 12.2 reject. The negative control. |

## Retaking them

Both sample resumes are fictional (`avery_chen_clean.pdf`,
`jordan_blake_tables.pdf`) and the three postings are the ones that ship
with the project, so nothing here exposes a real candidate or an
employer's copy. Keep it that way: never screenshot the page with a
`data/raw/` resume or a fetched posting selected.

Crop above the app — the macOS menu bar and the browser's tab and URL
bars carry the clock, the profile avatar and whatever extensions are
installed, and none of it is the project. The current set is cropped and
kept at the Retina capture width (3420px, ~500KB each). To halve the
repo's weight at no visible cost in a README, which renders them at
under 1000px anyway:

```bash
sips -Z 1600 images/*.png
```
