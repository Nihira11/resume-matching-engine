# UI (Reflex)

Status: working end-to-end against the live pipeline — upload or pick a
resume, pick or paste a posting, score it, read the breakdown, or rank one
resume against every stored posting.

```bash
cd app
reflex run          # http://localhost:3000
```

## Shape

Three files, split by what they depend on:

| File | Role | Depends on |
|---|---|---|
| `service.py` | pipeline calls + shaping results for display | `src/`, the database |
| `state.py` | Reflex state, event handlers, typed row models | `service.py` |
| `resume_matcher.py` | components and layout | `state.py` |

`service.py` exists so the display logic is testable without a Reflex app
context: `tests/test_ui_service.py` pushes a hand-built `MatchScore`
through the same formatter the page uses, so a field renamed in the engine
fails a test instead of silently rendering blank.
`tests/test_ui_state.py` drives the event handlers with the pipeline
stubbed — selection, validation, busy/error handling, and result mapping —
with no database, no spaCy and no embedding model.

## Decisions

**Everything slow runs as a background event.** First score loads spaCy's
large model, builds the ~14k-term PhraseMatcher and loads MiniLM, then
embeds and writes chunks to pgvector. A normal handler would block the
websocket and freeze the page for the better part of a minute. Handlers
set `busy` and a `status` line naming the stage, then do the blocking work
in `asyncio.to_thread`.

**Upload is the exception**, because Reflex rejects a background upload
handler outright — the file has to be read while the request is alive. So
`handle_resume_upload` saves the bytes and returns
`AppState.process_resume(path)`, which is the background half.

**State vars are flat and typed, not one result dict.** `rx.foreach`
cannot iterate a var it only knows as `Any`, which is exactly what
indexing an untyped `dict` state var produces. Rows are plain dataclasses
(`ComponentRow`, `GapRow`, `BoardRow`) — `rx.Base` was removed in Reflex
0.9.

**The verdict is shown with its caveat attached.** Thresholds are
uncalibrated and every real posting scored so far lands below "borderline"
(see `validation-results.md`), so the UI says to compare postings against
each other rather than trusting one score. Writing the caveat into the
component is deliberate: the number is the first thing anyone reads.

**Components are listed by contribution, not raw score.** A component
scoring 50 at 17% weight matters less than one scoring 44 at 44%, and the
weight is printed next to each bar so the ordering is checkable.

**ATS parsability sits in the resume panel, not the results.** It is a
property of the file, not of the pair, and folding it into the match score
would hide that a resume can match perfectly on content and still be
shredded by a real parser.

## Reflex 0.9 notes

Written against `reflex==0.9.6.post1` (pinned in `requirements.txt`).
Four API details cost time and will matter on upgrade:

- `rx.Base` is gone; use dataclasses for typed state models.
- Implicit `set_<var>` handlers are gone; write them explicitly.
- `segmented_control.on_change` passes `str | list[str]`, so the handler
  has to accept both.
- `App(theme=...)` is deprecated in favour of a `RadixThemesPlugin` config
  in `rxconfig.py`; still functional, worth moving before 1.0.

`rxconfig.py` puts the repo root on `sys.path` so the app can import
`src/` while Reflex runs from `app/`.

## Speed

The database is hosted and every query costs ~550ms round trip, which
dominated everything: a single score took 39s and ranking 13 postings took
8 minutes. Four changes, none of which alter a score:

| Change | Where |
|---|---|
| Pooled connections instead of connect-per-call | `src/utils/db.py` |
| One batched UPDATE instead of one per skill | `profiles.refresh_is_required` |
| `run_match(preloaded=…)` accepts profiles/vectors the caller holds | `match_pipeline.py` |
| Per-session cache of profiles, vectors and requirement refreshes | `service.py` |

| | Before | After |
|---|---|---|
| First score (cold models) | ~39s | ~20s |
| Re-score, warm | ~12s | ~1.5s |
| Score a new posting | ~39s | ~12s |
| Rank 13 postings | ~8 min | ~2 min cold, ~23s warm |

Cache correctness: `service.clear_caches()` runs on every ingest, which is
the only way stored rows change while the app is running. Re-extraction
from the CLI (`scripts/reextract_entities.py`) does not notify a running
app — restart it after that.

The leaderboard scores one posting at a time and pushes each row as it
lands, sorted, so the table fills in rather than blocking behind a
spinner for the whole set.

## Not done yet

- **No filtering or sorting in the leaderboard.** It is sorted by score
  server-side; column sorting would need client-side state.
- **Adzuna search is not wired in.** Postings are pasted or loaded by
  `scripts/add_jd.py`. The API truncates descriptions at 500 characters,
  which is not enough to score against, so the UI deliberately doesn't
  offer it as a shortcut.
- **No auth and no per-user separation.** Every resume in the database is
  visible in the dropdown. Fine locally; a blocker for deployment.
- **Chunk embeddings are cached, but not invalidated.**
  `service.ensure_embeddings` embeds a document only when pgvector holds
  no chunks for it, which is what makes the leaderboard tolerable. Editing
  a stored document's text in place would leave stale vectors — re-ingesting
  writes a new row with a new id, so that case doesn't arise today.
