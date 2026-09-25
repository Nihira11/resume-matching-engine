# Reflex app + matching engine.
#
# Two things dominate the image: PyTorch (a CPU-only wheel, ~200MB
# against ~400MB for the default build, and nothing here uses a GPU) and
# the MiniLM weights (~87MB), which are baked in at build time so the
# first request doesn't pay for a download.
#
# No spaCy model is installed on purpose: extraction runs on
# spacy.blank("en") -- tokenizer and PhraseMatcher only -- so the 500MB
# en_core_web_lg download is not needed at runtime.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# unzip/curl are needed by Reflex to fetch its frontend toolchain at
# build time; the rest are build deps for psycopg2 and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl unzip libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first, so the heavy layer caches independently of app code
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN pip install -r requirements.txt

# bake the embedding model into the image
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/processed/bm25_corpus_stats.json ./data/processed/

# The quick-start loaders on the overview page read these at runtime.
COPY data/samples/ ./data/samples/

# ESCO relations drive the "related skills" suggestions in gap analysis.
# They are gitignored (37MB) so a clean clone has only the .gitkeep, and
# the copy still succeeds -- load_adjacency() returns an empty map when
# the files are absent and every suggestion silently disappears. That is
# the same failure DATA_ROOT was introduced to stop, so if suggestions
# matter in the deployed app, fetch the CSVs before building and check
# the feature after deploying rather than assuming it works.
COPY data/taxonomy/ ./data/taxonomy/

# Last, because app code changes most often and everything above caches.
# .dockerignore keeps app/uploaded_files (real resumes) and app/.web
# (179MB of node_modules) out of the image -- see the comments there.
COPY app/ ./app/

WORKDIR /app/app

# Reflex needs the repo root importable (see app/rxconfig.py) and the
# working directory is app/, so data paths resolve from the parent
ENV PYTHONPATH=/app
ENV DATA_ROOT=/app

RUN reflex init

EXPOSE 3000 8000

CMD ["reflex", "run", "--env", "prod"]
