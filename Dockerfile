# syntax=docker/dockerfile:1.7
# ---- Python dependencies (no PyTorch; MiniLM runs through ONNX only with EXTRAS=minilm) ----
FROM python:3.12-slim AS deps
ARG EXTRAS=""
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml .
RUN python - <<'PY' > /tmp/req.txt
import os, tomllib
p = tomllib.load(open("pyproject.toml", "rb"))["project"]
deps = list(p["dependencies"])
for extra in filter(None, os.environ.get("EXTRAS", "").split(",")):
    deps += p["optional-dependencies"][extra]
print("\n".join(deps))
PY
RUN pip install --upgrade pip && pip install -r /tmp/req.txt

# ---- Development / test image: source is mounted at /app ----
FROM deps AS dev
RUN python - <<'PY' > /tmp/dev.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["optional-dependencies"]["dev"]))
PY
RUN pip install -r /tmp/dev.txt
ENV PYTHONPATH=/app
CMD ["pytest", "-q"]

# ---- Frontend build (static files served by FastAPI; fonts are bundled, so it works air-gapped) ----
FROM node:20-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY web/ ./
RUN npm run build

# ---- Runtime image (one image, every role: python -m run {api|relay|worker|recovery|all}) ----
FROM deps AS runtime
ARG EXTRAS=""
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 MODEL_CACHE_DIR=/models BLOB_ROOT=/data/blobs STATIC_DIR=/app/web/dist
RUN useradd --create-home --uid 10001 app && mkdir -p /models /data/blobs /data/settings && \
    chmod 700 /data/settings && chown -R app /models /data
# MiniLM (ONNX, ~90 MB) is downloaded at build time so the air-gapped profile needs no internet at run time.
RUN case ",$EXTRAS," in *,minilm,*) python -c "from fastembed import TextEmbedding; \
    TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/models')" && chown -R app /models;; esac
WORKDIR /app
COPY --chown=app common ./common
COPY --chown=app api ./api
COPY --chown=app pipeline ./pipeline
COPY --chown=app search ./search
COPY --chown=app assistant ./assistant
COPY --chown=app documents ./documents
COPY --chown=app config ./config
COPY --chown=app deploy/sql ./deploy/sql
COPY --chown=app corpus/bad ./corpus/bad
COPY --chown=app evals/ux/corpus.json ./evals/ux/corpus.json
COPY --chown=app run.py ./
COPY --from=web-build --chown=app /web/dist ./web/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
  CMD python -c "import os,urllib.request; r=os.environ.get('ROLE','all'); \
  r in ('api','all') and urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["python", "-m", "run", "all"]
