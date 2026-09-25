# Deployment

Status: **not deployed.** A `Dockerfile` is in the repo, the app runs
locally, and the access model that previously blocked deployment is now
in place. What follows is what deploying it would cost and what is left
to check.

## Access model: session scoping

Resumes carry names, phone numbers and addresses, so the original
behaviour — one shared dropdown listing every resume ever uploaded — was
the thing that made this undeployable.

Now (`db/migrations/003_session_scoping.sql`):

- every resume and posting is stamped with the Reflex client token
- the UI lists only rows carrying the current session's token, and a
  missing token lists nothing rather than everything
- the dashboard counts are scoped the same way, so a visitor is never
  told there are 41 postings when they added two
- **Delete my data now** removes a session's rows immediately, and a TTL
  sweep (24h, `service.purge_expired`) removes what nobody deleted

What this is not: an account system. There is no login, and anyone who
recovered a session token could read that session's data. For a public
demo that is proportionate; for anything holding real applications it is
not.

**Session data does not disappear when the tab closes.** No such signal
is dependable — a tab can be killed, a laptop can sleep — so the TTL is
the mechanism that actually runs, and the UI says so rather than
implying instant deletion.

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

## Build context: two problems found by reading the Dockerfile

Docker has still never been run here, so these came out of a read rather
than a build. Both were real, and both are fixed.

**`COPY app/ ./app/` would have baked real resumes into the image.**
Docker does not read `.gitignore`, so `app/uploaded_files/` — 532KB of
resumes people uploaded through the UI, with their names, phone numbers
and addresses — was inside the build context, along with `app/.web/`,
179MB of `node_modules` that `reflex init` regenerates anyway. There is
now a `.dockerignore`; it is the single most important file for this
deployment and the reason to check the image contents after the first
build rather than trusting the layer list:

```bash
docker run --rm resume-matcher ls /app/app          # expect no uploaded_files
docker run --rm resume-matcher du -sh /app/app/.web # expect a fresh build only
```

**The ESCO relation files were not copied at all.** Gap analysis reads
them at runtime, and `load_adjacency()` returns an empty map when they are
missing — so "related skills" suggestions would have silently disappeared
in the container with nothing in the logs. This is the same failure that
`DATA_ROOT` was introduced to stop, in a new place. `data/taxonomy/` is
now copied, but the CSVs are gitignored (37MB, ESCO licence), so a clean
clone copies only the `.gitkeep` and the feature degrades quietly. Fetch
them before building if suggestions matter, and check the feature in the
deployed app rather than assuming.

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

0. Install Docker. Nothing below can be verified without it, and the two
   problems above were found by reading, which does not generalise.
1. Build the image locally and fix whatever the build surfaces. Then check
   the image for uploaded resumes, using the commands above.
2. Deploy to Fly.io or Reflex Cloud, with `DATABASE_URL` set as a secret.
3. Re-check timings from the deployed region; if the database is far from
   the app, move one of them — round trips dominate, and the first score
   in a session already takes ~55s while models load.
4. Consider a scheduled sweep rather than the opportunistic one, so a
   site with no visitors still expires its data on time.
