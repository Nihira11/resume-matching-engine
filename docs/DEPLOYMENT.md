# Deployment

Status: **not deployed.** A `Dockerfile` is in the repo and the app runs
locally; what follows is the honest assessment of what deploying it
costs, and the one thing that must be fixed first.

## Blocker: there is no authentication

Every resume ever uploaded appears in the dropdown, to anyone with the
URL. Resumes contain names, phone numbers, email addresses and home
suburbs. Putting this on a public URL as it stands would publish other
people's personal data, and there is nothing in the app to stop it.

Before any public deployment, one of:

1. **Keep it private** — deploy behind HTTP basic auth or an allowlist,
   as a demo for specific people. Smallest change.
2. **Scope data per session** — a session key on `resumes`, filtered in
   every query. Correct, and a day's work with the query surface as it
   stands.
3. **Demo mode** — deploy with sample resumes only and disable upload.
   Shows the engine without holding anyone's data.

Option 3 is the honest default for a portfolio piece.

## Size

The image is dominated by the model stack:

| Component | Size |
|---|---|
| PyTorch (CPU wheel) | ~200MB (the default build is ~400MB; nothing here uses a GPU) |
| MiniLM weights, baked in at build | 87MB |
| Reflex + frontend toolchain | ~150MB |
| Everything else | ~50MB |

Roughly **500MB**, which rules out the smallest free tiers. No spaCy
model is installed: extraction runs on `spacy.blank("en")`, saving the
500MB `en_core_web_lg` download that the original scaffold assumed.

## Hosting options

| Option | Fit | Notes |
|---|---|---|
| **Reflex Cloud** (`reflex deploy`) | Simplest | Purpose-built for Reflex; check the current tier's image-size and memory limits against ~500MB before committing |
| **Fly.io** | Good | `fly launch` reads the Dockerfile; 512MB RAM is tight for torch, 1GB is comfortable |
| **Railway / Render** | Workable | Dockerfile deploys fine; free tiers sleep, and a cold start pays the model load again |
| **Hugging Face Spaces** | Poor fit | Docker Spaces would work, but the app needs an external Postgres and the free tier is public by default |

## Runtime requirements

- **Postgres with pgvector.** Supabase works; use the session pooler
  connection string. Note that the pooler adds ~550ms per round trip from
  outside its region, which dominates scoring time — a first score takes
  ~20s, most of it waiting on the network. Co-locating the app with the
  database would help more than any code change.
- **Environment:** `DATABASE_URL` is required. `ADZUNA_APP_ID` /
  `ADZUNA_APP_KEY` are optional (posting *search* only).
- **Data files:** `data/processed/bm25_corpus_stats.json` ships in the
  repo and is copied into the image. Without it the keyword component is
  silently dropped. `data/taxonomy/esco_*.csv` are **not** in the repo
  (ESCO's licence) — without them, gap analysis loses its "related
  skills" suggestions but everything else works.
- **`DATA_ROOT`** overrides where those files are looked up, for images
  that lay the tree out differently.

## Local build

Docker is not installed on the development machine, so the Dockerfile has
been written but never built. That is worth stating plainly rather than
implying it is tested:

```bash
docker build -t resume-matcher .
docker run -p 3000:3000 -p 8000:8000 --env-file .env resume-matcher
```

Expect the first build to take several minutes, mostly torch.

## What would need doing, in order

1. Pick an access model from the three above — this is the blocker.
2. Build the image locally and fix whatever the build surfaces.
3. Deploy to Fly.io or Reflex Cloud, with `DATABASE_URL` set as a secret.
4. Re-check timings from the deployed region; if the database is far from
   the app, move one of them.
