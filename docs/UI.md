# UI

Streamlit, in `streamlit_app.py`. Five sections — Overview, Resume, Job
postings, Match results, Leaderboard — selected from a sidebar radio, so
each page answers one question instead of one long scroll answering all
of them.

Run it:

```bash
streamlit run streamlit_app.py
```

## Why not Reflex

The UI was Reflex until the project tried to deploy it. Reflex is a good
framework; it is a poor fit for an app whose backend holds a 400MB model
stack, and four separate failures traced back to that mismatch:

| Symptom | Cause |
|---|---|
| Backend OOM-killed repeatedly on a 1GB host | `get_num_workers()` returns `cpu_count * 2 + 1`. One CPU meant **three** workers, each loading its own torch, MiniLM and 14k-term matcher — ~1.1GB. |
| Every tab click took 1–3 seconds | Reflex serialises the whole state to Redis per event. The state carried a 150KB base64 resume preview, so an image rode along with each click. `Lock ... held too long time_taken=1.149s` on an event that sets one string. |
| Every host needed a reverse proxy | Frontend on 3000, backend on 8000; platforms expose one port. |
| Cold starts looked like a dead app | Websocket-only, so until the backend answers, every control is inert with no feedback. |

Streamlit removes all four: one port, no websocket state machine, no
Redis, and one process. `@st.cache_resource` holds the model across
reruns, which is the thing that was hardest to arrange before.

The trade is that Streamlit re-executes the script top to bottom on every
interaction, so anything expensive must be cached or kept in
`st.session_state`. That is a constraint worth having here — it makes the
cost of each interaction obvious instead of hiding it behind a state
diff.

## Session scoping

Resumes carry names, phone numbers and addresses, so every row is stamped
with a per-browser token (`st.session_state.token`, a UUID) and nothing is
listed without one. `service.list_resumes("")` returns nothing rather than
everything — it fails closed. A 24-hour TTL sweep removes what nobody
deleted, and **Delete my data now** removes a session's rows immediately.

Uploads are written to `data/uploads/`, parsed, and **deleted straight
away**: the extracted text and the preview image live in the database, so
the file itself is not needed again and is personal data. The directory
is gitignored regardless, so a crash between write and delete cannot leak
one into version control.

## Error messages

Everything user-visible goes through `service.safe_error`. psycopg2 puts
the whole connection string into its exceptions, and a deployed instance
once printed the database password to the front page for anyone who
loaded it. The sanitiser redacts URI credentials and the configured
`DATABASE_URL`; three tests cover it.

## What each section does

- **Overview** — quick-start loaders (two sample resumes, five live
  postings fetched from company job boards, three fictional postings),
  headline metrics, and recent matches.
- **Resume** — upload, the rendered first page, the ATS parsability score
  with its flags, and the skills and titles the parser actually read.
- **Job postings** — paste a posting whole; required vs nice-to-have is
  read from its headings.
- **Match results** — the blended score, the fit band and percentile, and
  every component with its weight and contribution. Dropped components
  are named rather than silently zeroed.
- **Leaderboard** — one resume against every posting in the session,
  scored one at a time so the table fills in as results land.
