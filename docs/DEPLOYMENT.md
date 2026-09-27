# Deployment

Target: **Streamlit Community Cloud** — free, no credit card, deploys from
a GitHub repo, and needs no Docker.

## Steps

1. Push this repo to GitHub (public, or private with Streamlit granted
   access).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. **New app** → pick the repo and branch → main file `streamlit_app.py`.
4. **Advanced settings → Secrets**, paste:

   ```toml
   DATABASE_URL = "postgresql://postgres.xxx:PASSWORD@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
   ```

   Percent-encode any special characters in the password (`&` → `%26`,
   `@` → `%40`, `#` → `%23`). Streamlit exposes secrets as environment
   variables, which is what `src/utils/db.py` reads.
5. Deploy. The first build installs torch and downloads MiniLM, so expect
   several minutes.

## What the app needs at runtime

- **Postgres with pgvector.** Supabase works; use the session pooler
  string. Co-locate if you can — round trips dominate scoring time.
- **`DATABASE_URL`** as a secret. Nothing else is required; the Adzuna
  keys are optional and only affect posting *search*.
- **Committed data files**, both small and both already in the repo:
  `data/processed/bm25_corpus_stats.json` (the keyword component is
  silently dropped without it) and `data/processed/esco_adjacency.json.gz`
  (the "related skills" suggestions disappear without it).

`data/taxonomy/*.csv` are **not** needed — they are 36MB and ESCO-licensed,
so the derived adjacency map ships instead. See
`scripts/build_adjacency_cache.py`.

## Memory

Roughly 400MB resident once warm:

| Component | Cost |
|---|---|
| PyTorch (CPU wheel) | ~190MB |
| MiniLM weights | ~110MB |
| spaCy tokenizer + taxonomy index | ~15MB |
| ESCO adjacency map | ~70MB |

Community Cloud's allowance is comfortably above that. It was not
comfortably above the 1.1GB the previous host used, which is the whole
story below.

## Why not the previous hosts

Worth recording, because each was a dead end for a different reason and
the reasons are not obvious from the marketing pages.

**Hugging Face Spaces** — Docker Spaces now require a PRO subscription.
Free accounts get static Spaces only. A write token does not change it;
the API returns `402 Payment Required` at repo creation.

**Reflex Cloud (free tier)** — 1GB RAM, one CPU, suspends when idle,
~3 minute cold start. The app was OOM-killed four times in 25 minutes.
The cause was not the app's own footprint: Reflex sizes its worker pool
as `cpu_count * 2 + 1`, so one CPU meant **three** backend workers, each
loading its own copy of torch, MiniLM and the skill matcher. `GRANIAN_WORKERS=1`
fixed the OOM, but cold starts and idle suspension remained, and the
platform twice got stuck at `pending worker...` needing a manual stop and
start through its API.

Three real bugs were found while chasing that and are fixed regardless of
host: a 99,400-pattern spaCy `PhraseMatcher` costing 313MB (now a token
n-gram dict), a 150KB resume preview being serialised to Redis on every
click (now loaded on demand), and the database password being printed to
the page in error banners (now redacted by `service.safe_error`).

**Google Cloud Run** would work — 2GB, scales to zero, generous free
tier — but it requires a billing account with a card even to stay within
the free tier.

## Checks worth running after deploying

- Open the app in **two tabs**. Session scoping means each gets its own
  data; neither should see the other's.
- Load the sample resumes, then a posting, then score. The first score is
  slow (model load); later ones are seconds.
- Confirm no connection string appears anywhere on the page if something
  errors.
