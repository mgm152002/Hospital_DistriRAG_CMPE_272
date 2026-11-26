# DistriRAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the base repo into DistriRAG: a hospital knowledge pipeline (outbox → relay → Redis Streams → workers → pgvector) with source-aware search, a guarded clinical-reference assistant, compliance controls, a React UI, and containers that run on weak hardware.

**Architecture:** One Python image runs `api`, `relay`, `worker`, `recovery`, or `all` (every role as asyncio tasks in one process, used on weak hardware). PostgreSQL + pgvector is the source of truth; Redis Streams carries work. The React app is built into the same image and served by FastAPI. Business rules are pure functions behind ports; I/O lives in adapters (the existing rule, kept by `tests/test_architecture.py`).

**Tech Stack:** Python 3.12, FastAPI, psycopg 3 + psycopg_pool, redis-py 5 (asyncio), pypdf, pydantic-settings, httpx, fastembed (ONNX MiniLM, optional), boto3 / azure-storage-blob (optional), prometheus-client; React 18 + Vite + TypeScript + Tailwind + TanStack Query, Vitest + Testing Library + vitest-axe, Playwright; Docker Compose; GitHub Actions.

**Spec:** "DistriRAG Hospital — Revised Proposal & Build Plan" — https://claude.ai/artifact/VcF5j5pr59Ekw6G7EsgcD4 (requirement IDs FR-, RL-, CR-, AG-, DP-, CP-, UX-, TS-; work items E0-1…E14-3; acceptance tests AT-01…AT-24). Copy exported to `docs/PROPOSAL.md` in Task 25.

## Global Constraints

- Python 3.12 in containers (`python:3.12-slim`); the host Python is never required. Node 20 for `web/`.
- All tests run in containers: `make test` (unit), `make test-integration`, `make test-web`, `make test-e2e`, `make regression`.
- **Weak hardware:** the `lite` profile (`RUN_MODE=all`, `EMBED_PROVIDER=hashing`, `LLM_PROVIDER=none`, `BLOB_PROVIDER=local`) must run Postgres + Redis + app in **≤ 1 GB RAM total and 2 CPUs**, with no model downloads and no GPU. No PyTorch anywhere; MiniLM runs through fastembed/ONNX only when `EMBED_PROVIDER=minilm`.
- Postgres tuned for small hosts in compose: `shared_buffers=64MB`, `max_connections=40`, `work_mem=4MB`. Redis: `--appendonly yes --appendfsync everysec --maxmemory 128mb --maxmemory-policy noeviction`.
- Embedding dimension 384 for both `hashing` and `minilm` (`EMBEDDING_DIM=384`).
- Uploads: `.txt`, `.md`, `.pdf` only, ≤ 10 MB (`MAX_UPLOAD_BYTES=10485760`).
- Chunking: 800 characters, 100 overlap; embed batches of 16 chunks.
- Retries: at most 5 deliveries; reclaim idle threshold `min(60000 * 2**(deliveries-1), 600000)` ms; stuck re-drive after 600 s (`STUCK_AFTER_SECONDS`).
- `MIN_RELEVANCE=0.35`; confidence `100*(0.5R+0.3C+0.2A)`, bands High ≥ 75, Medium 50–74, Low < 50; R rescales `MIN_RELEVANCE→0`, `0.85→1`, clamped.
- Assistant disclaimer, verbatim: `Reference only. Verify against the source and use clinical judgement.` Banner: `Reference tool. Does not diagnose or replace clinical judgement.`
- Synthetic data only; every corpus file starts with `SYNTHETIC — FOR DEMONSTRATION ONLY — NOT CLINICAL GUIDANCE`.
- Personas/groups exactly as spec Section 3 (`priya`, `sam`, `jordan`, `riley`, `alex`, `taylor`, `casey`).
- Each task's tests carry a docstring `Covers: <IDs>`, read by `make coverage-matrix`.
- Commit after every task with message `E<n>-<m>: <summary>`, ending with the Co-Authored-By line.

## Review Focus

1. **Out-of-order versions:** v2 and v3 both approved, v3 finishes first, then v2 finalizes — v2 must not replace v3. Finalize activates only if `version_number` > the current active version's number; otherwise it marks itself `SUPERSEDED`. Test: `test_finalize_never_downgrades_active_version` (Task 6).
2. **Odd filenames and types:** `POLICY.PDF`, a file with no extension, `.md` uploaded with `application/octet-stream`, a filename with `../` or spaces. Expected: case-insensitive extension check, content sniffing decides, filename is sanitized in the blob key. Test: `test_upload_filename_variants` (Task 8).
3. **Infrastructure down at request time:** Redis down while approving must still return `202` (only the outbox is written); Postgres down returns `503 {"error_code":"db_unavailable"}`, never a stack trace. Tests: `test_approve_succeeds_with_redis_down`, `test_db_down_returns_503` (Task 8/12).
4. **Degenerate queries:** empty after trimming, only stop words, 500+ characters, emoji or non-English. Expected: `422` for empty/too long; others return normally (possibly zero results), never a 500. Test: `test_search_degenerate_queries` (Task 9).
5. **Messy document text:** Markdown with no headings, a single 50 KB line, CRLF line endings, NUL bytes inside a `.txt`, a PDF where some pages are empty. Expected: NUL → `invalid_encoding`; others chunk without empty chunks. Test: `test_chunker_messy_inputs` (Task 6).

---

## File Structure

```text
common/        config.py  db.py  ids.py  models.py  audit.py  logging.py  metrics.py  egress.py  migrate.py
common/blob/   __init__.py (BlobStore, make_blob_store)  local.py  s3.py  azure.py
common/embed/  __init__.py (Embedder, make_embedder)  hashing.py  minilm.py
common/llm/    __init__.py (LLMProvider, ProviderInfo, make_llm, load_providers)  openai_compat.py  ollama.py  fake.py
pipeline/      streams.py  outbox.py  relay.py  consumer.py  recovery.py  events.py
pipeline/stages/ extract.py  chunk.py  embed.py  finalize.py  delete.py
api/           app.py  deps.py  auth.py  errors.py  idempotency.py
api/routes/    documents.py  search.py  chat.py  compliance.py  ops.py  system.py
search/        query.py  snippet.py
assistant/     rules.yaml  classify.py  phi.py  citations.py  clinical.py  confidence.py  egress_policy.py  prompt.py  answer.py  cache.py
config/        providers.yaml  personas.yaml
run.py         python -m run {api|relay|worker|recovery|all}
web/           React app (src/components, src/pages, src/api, e2e/)
corpus/        *.md|*.txt|*.pdf  manifest.yaml  bad/  build_pdfs.py
evals/         cases.yaml  run.py
scripts/       seed.py  coverage_matrix.py
tests/         unit/  integration/  regression/  fakes.py  conftest.py
deploy/        sql/001_distrirag.sql  docker-compose.yml  docker-compose.test.yml  postgres.conf  cloud/README.md  cloud/Caddyfile
.github/workflows/ci.yml   Dockerfile   Makefile   pyproject.toml   .env.example
```

Deleted from the base codebase (Task 1): `agent/`, `gateway/`, `reconciler/`, `ingest/` (logic moved), `loadtest/`, `api/ops/flood.py`, `api/static/`, `common/temporal_client.py`, `common/worker_runtime.py`, `common/queue_stats.py`, `common/names.py`, `common/queues.py`, `common/retry.py`, `deploy/k3s`, `deploy/signoz`, `deploy/instana`, `deploy/aws`, `deploy/local`, `deploy/compose`, `deploy/sql/00*.sql`, `demo/`, `evals/fixtures`, `scripts/*.sh` except none, and tests for those.

---

### Task 1: Bootstrap — clean the base codebase, tooling, test containers (E0-1, E0-4 skeleton)

**Files:** Delete the list above. Create `pyproject.toml` (rewrite), `deploy/docker-compose.test.yml`, `Dockerfile` (dev stage only for now), `Makefile`, `tests/conftest.py`, `tests/unit/test_smoke.py`. Keep `tests/test_architecture.py` (move to `tests/unit/`), updated to the new package list.

**Interfaces:** Produces `make test` → `docker compose -f deploy/docker-compose.test.yml run --rm unit`; `make test-integration` → `run --rm integration` (with `postgres` = `pgvector/pgvector:pg16`, `redis` = `redis:7-alpine`, env `DATABASE_URL`, `REDIS_URL`).

- [ ] Step 1: Move keepers before deleting: `ingest/services.py::split_pages` → `pipeline/stages/chunk.py`; `ingest/pdf.py` → `pipeline/stages/extract.py`; `agent/guard.py` injection stripping + secret redaction → `assistant/guards_legacy.py` (renamed in Task 10); `api/auth.py` kept; `common/storage.py` → `common/blob/s3.py`; `evals/run.py` kept.
- [ ] Step 2: Delete the rest; rewrite `pyproject.toml` with extras `minilm=[fastembed]`, `s3=[boto3]`, `azure=[azure-storage-blob]`, `dev=[pytest, pytest-asyncio, pytest-cov, ruff, mypy, hypothesis]`; ruff line length 110; pytest `asyncio_mode=auto`, markers `integration`, `regression`.
- [ ] Step 3: `tests/unit/test_smoke.py::test_packages_import` imports every package; `test_no_temporal_imports` greps the tree for `temporalio` and asserts none.
- [ ] Step 4: `make test` → PASS; `make lint` (ruff + mypy in container) → clean.
- [ ] Step 5: Commit `E0-1: Remove Temporal, k8s and IT-helpdesk code; containerized test tooling`.

### Task 2: Settings and deployment profiles (E0-3, DP-1, DP-6, CP-4)

**Files:** `common/config.py`, `.env.example`, `config/providers.yaml`, `tests/unit/test_config.py`.

**Interfaces:** Produces `Settings` (pydantic-settings) with fields: `deployment_profile: Literal['lite','airgapped','hybrid','cloud']='lite'`, `run_mode`, `database_url`, `redis_url`, `llm_provider: str`, `embed_provider: Literal['hashing','minilm']`, `embedding_dim=384`, `blob_provider: Literal['local','s3','azure']`, `blob_root='/data/blobs'`, `external_max_classification`, `allowed_hosts: list[str]`, `synthetic_data_only=True`, `phi_mode: Literal['redact','block']='redact'`, `chat_retention_days=30`, `audit_retention_days=365`, `min_relevance=0.35`, `confidence_weights=(0.5,0.3,0.2)`, `auth_mode: Literal['header','oidc']='header'`, `max_upload_bytes`, `reclaim_base_idle_ms=60000`, `stuck_after_seconds=600`, `max_deliveries=5`, `worker_concurrency=1`, `llm_max_concurrency=4`. `get_settings() -> Settings` (cached). `PROFILE_DEFAULTS: dict[str, dict]` applied before env overrides. `validate_compliance(s: Settings, providers: dict[str, ProviderInfo]) -> None` raises `ComplianceConfigError(str)`.

- [ ] Step 1: Tests: `test_profile_defaults_lite` (hashing, none, local, run_mode all); `test_env_overrides_profile`; `test_airgapped_refuses_external_provider`; `test_retaining_provider_requires_synthetic`; `test_cloud_requires_sslmode`; `test_config_view_masks_secrets` (`Settings.public_view()` masks keys containing `key|secret|password|url` credentials).
- [ ] Step 2: Run → FAIL. Step 3: implement. Step 4: Run → PASS. Step 5: Commit `E0-3: Deployment profiles and startup compliance checks`.

### Task 3: Schema, migrations, ids, repositories (E1, RL-1, CR-4)

**Files:** `deploy/sql/001_distrirag.sql` (spec §7.2 plus `ops_events(id bigserial, kind text, version_id uuid, detail jsonb, created_at)` and `answer_cache(key text primary key, answer jsonb, version_ids uuid[], created_at)`), `common/migrate.py`, `common/db.py`, `common/ids.py`, `common/models.py`, `common/audit.py`, `tests/unit/test_ids.py`, `tests/integration/test_schema.py`, `tests/integration/test_repos.py`.

**Interfaces:**
- `common.ids.chunk_id(version_id: str, index: int) -> str` (uuid5, namespace `6f1c2d5e-0000-4000-8000-d15791a90001`).
- `common.models`: `VersionStatus` StrEnum (`PENDING_APPROVAL, REJECTED, QUEUED, PROCESSING, READY, SUPERSEDED, FAILED`), `Stage` (`EXTRACT, CHUNK, EMBED, FINALIZE`), `Classification` (ordered: `public<internal<confidential<restricted`, with `rank()`), `CATEGORIES: tuple[str, ...]` (spec FR-3), `User(user_id, groups: frozenset[str], display_name)`.
- `common.db.create_pool(url, min_size=1, max_size=5) -> AsyncConnectionPool`; `vector_literal(v) -> str`.
- `common.migrate.migrate(url) -> list[str]` (applied names; advisory lock 4242).
- `common.audit.record(conn, actor: str, action: str, target: str|None=None, detail: dict|None=None) -> None`.
- Repos live with their feature (Tasks 6, 8); this task only adds SQL + helpers.

- [ ] Step 1: Tests: `test_chunk_id_deterministic`; integration `test_migrate_is_idempotent` (second run applies `[]`); `test_app_role_cannot_update_audit`; `test_self_approval_check_constraint`; `test_chunk_unique_per_version`.
- [ ] Step 2–4: fail → implement → pass. Step 5: Commit `E1: Schema, migrator, deterministic ids`.

### Task 4: Providers — blob, embeddings, LLM, egress guard (E8-1, E8-2, E8-3, E8-4, E4-5, DP-2..5)

**Files:** `common/blob/*`, `common/embed/*`, `common/llm/*`, `common/egress.py`, `config/providers.yaml`, tests `tests/unit/test_embed.py`, `test_llm.py`, `test_egress.py`, `tests/integration/test_blob.py` (local + MinIO + Azurite services in the test compose).

**Interfaces:**
- `BlobStore` Protocol: `async put(key: str, data: bytes, content_type: str) -> None`, `async get(key) -> bytes`, `async delete_prefix(prefix) -> int`, `async exists(key) -> bool`, `async list_prefix(prefix) -> list[str]`. `make_blob_store(s: Settings) -> BlobStore`. `safe_key(*parts) -> str` (strips `..`, slashes in parts, control chars).
- `Embedder` Protocol: `dim: int`, `async embed(texts: list[str]) -> list[list[float]]` (unit-normalized). `HashingEmbedder(dim=384)` = signed feature hashing of lowercase word unigrams + bigrams (blake2b), L2-normalized — deterministic, no downloads; also the test fake. `MiniLMEmbedder` wraps `fastembed.TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/models')`, runs in `asyncio.to_thread`. `make_embedder(s)`.
- `ProviderInfo(name, kind, base_url, model, api_key_env, external: bool, baa_signed: bool, retains_data: bool, region: str, max_concurrency: int)`; `load_providers(path='config/providers.yaml') -> dict[str, ProviderInfo]`.
- `LLMProvider` Protocol: `info: ProviderInfo`; `async stream(messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]`; raises `ProviderUnavailable`. Implementations: `OpenAICompatible` (httpx SSE `/chat/completions`, 30 s timeout, 2 retries on 429/5xx, semaphore cap), `Ollama` (`/api/chat` stream), `FakeLLM(script: Callable[[list[dict]], str])` default echoes a cited answer built from passage `[1]`, and `NoLLM` (always raises `ProviderUnavailable`). `make_llm(s, providers) -> LLMProvider`.
- `EgressGuard(allowed_hosts: list[str], enforce: bool)`; `check(url: str) -> None` raises `EgressBlocked`; `httpx_hook` for `event_hooks={'request':[...]}`.

- [ ] Step 1: Tests: `test_hashing_embedder_deterministic_and_normalized`; `test_hashing_similar_texts_closer` (hand-hygiene sentence pairs); `test_fake_llm_streams_tokens`; `test_openai_compat_retries_then_raises` (httpx MockTransport 503×3); `test_egress_blocks_unlisted_host`; `test_egress_allows_listed_host`; `test_safe_key_strips_traversal`; integration `test_blob_roundtrip[local|s3|azure]`.
- [ ] Step 2–4. Step 5: Commit `E8: Pluggable blob, embedding and LLM providers with egress guard`.

### Task 5: Outbox, relay, streams, consumer framework (E3, RL-2..5)

**Files:** `pipeline/streams.py`, `pipeline/outbox.py`, `pipeline/relay.py`, `pipeline/consumer.py`, `pipeline/events.py`, tests `tests/unit/test_consumer.py`, `tests/integration/test_outbox_relay.py`, `test_consumer_redis.py`.

**Interfaces:**
- `streams`: `EXTRACT='ingest.extract'`, `EMBED='ingest.embed'`, `FINALIZE='ingest.finalize'`, `DELETE='docs.delete'`; `GROUPS={EXTRACT:'extractors', EMBED:'embedders', FINALIZE:'finalizers', DELETE:'deleters'}`; `dlq(stream) -> f'{stream}.dlq'`; `async ensure_groups(redis) -> None`.
- `outbox.enqueue(conn, stream: str, event_type: str, dedupe_key: str, payload: dict) -> None` (ON CONFLICT DO NOTHING; `NOTIFY outbox`).
- `relay.relay_once(pool, redis, batch: int = 100) -> int`; `relay.run(pool, redis, stop: asyncio.Event)` (LISTEN + 1 s poll; backoff 0.5→10 s). Message fields: `event_id`, `type`, `payload` (JSON).
- `consumer`: `PermanentError(code: str, message: str)`, `TransientError`; `Handler = Callable[[Ctx, dict], Awaitable[None]]`; `Ctx(pool, redis, blobs, embedder, settings, consumer_name)`; `Consumer(ctx, stream, group, handlers: dict[str, Handler])` with `async step() -> bool` (claim due → read one → handle → ack) and `run(stop)`. On `PermanentError`: handler-provided `on_permanent(ctx, payload, err)` records FAILED, then `XACK`. On other exceptions: no ACK, log.
- `events.emit(conn, kind: str, version_id: str|None, detail: dict) -> None` writes `ops_events`.

- [ ] Step 1: Tests: unit `test_ack_only_after_commit` (fake redis + handler whose commit raises → no ack); `test_permanent_error_acks_once`; `test_transient_error_leaves_pending`. Integration: `test_rollback_leaves_no_outbox_row`; `test_dedupe_key_single_row`; `test_relay_publishes_500_rows_under_5s`; `test_relay_holds_rows_while_redis_down`; `test_two_relays_no_double_publish_in_same_pass`.
- [ ] Step 2–4. Step 5: Commit `E3: Transactional outbox, relay and Redis Streams consumer framework`.

### Task 6: Ingestion stages (E4-1..E4-6, RL-6, CR-1, CR-3, CR-6)

**Files:** `pipeline/stages/{extract,chunk,embed,finalize,delete}.py`, `pipeline/repo.py` (version/chunk SQL), tests `tests/unit/test_extract.py`, `test_chunk.py`, integration `test_stages.py`. Fixtures from Task 15 `corpus/bad/` (create minimal ones here if Task 15 not done: generate in `tests/fixtures/make_bad.py`).

**Interfaces:**
- `extract.extract_pages(data: bytes, filename: str, content_type: str) -> list[str]` raising `PermanentError` codes: `unsupported_type`, `pdf_encrypted`, `pdf_malformed`, `pdf_no_text_layer` (avg < 20 chars/page), `invalid_encoding` (UTF-8 failure or NUL), `empty_document`.
- `chunk.Piece(page: int, section: str|None, text: str)`; `chunk.split(pages: list[str], markdown: bool, size=800, overlap=100) -> list[Piece]` (Markdown heading path `A > B`; CRLF normalized; no empty pieces).
- Handlers: `handle_approved(ctx, payload)` (extract+chunk; one txn writes chunks via `chunk_id`, `chunks_total`, `stage=EMBED`, `embed_batches`, outbox `batch.ready` per 16 with `dedupe_key=f'embed:{vid}:{n}'`), `handle_batch(ctx, payload)`, `handle_embedded(ctx, payload)` (finalize; activates only if `version_number > active.version_number`, else `SUPERSEDED`; clears `answer_cache` rows overlapping the document's version ids; audit `version.published`), `handle_delete(ctx, payload)`. `on_permanent` sets `FAILED`, `error_code`, `error`, audit `version.failed`. Each handler emits `ops_events` (`stage.started`, `stage.done`).

- [ ] Step 1: Tests: `test_each_bad_fixture_maps_to_error_code` (parametrized); `test_chunker_messy_inputs` (Review Focus 5); `test_markdown_sections`; integration `test_extract_handler_idempotent`; `test_concurrent_batches_one_finalize`; `test_duplicate_batch_delivery_no_new_vectors`; `test_finalize_requires_all_embeddings`; `test_finalize_supersedes_previous`; `test_finalize_never_downgrades_active_version` (Review Focus 1); `test_zero_chunks_fail_not_ready`; `test_delete_purges_everything_and_is_rerunnable`.
- [ ] Step 2–4. Step 5: Commit `E4: Extract, chunk, embed, finalize and delete handlers`.

### Task 7: Recovery (E5, E9-4, RL-7, RL-8, CP-6)

**Files:** `pipeline/recovery.py`, integration `tests/integration/test_recovery.py`.

**Interfaces:** `due_idle_ms(deliveries: int, base: int) -> int`; `async reclaim_due(redis, stream, group, consumer, base_idle_ms) -> list[tuple[str, dict]]` (XPENDING extended + XCLAIM; emits `message.reclaimed` with old/new consumer, idle, deliveries); `async dead_letter(ctx, stream, group, max_deliveries) -> int`; `async replay_dead_letter(pool, dead_letter_id: int) -> None` (outbox with `:replay:{n}`); `async redrive_stuck(pool, redis, stuck_after_s) -> int`; `async purge_orphan_blobs(pool, blobs, older_than_s=86400) -> int`; `async purge_retention(pool, s) -> dict[str, int]`; `run(ctx, stop)` loops (15 s DLQ, 60 s re-drive, daily retention/orphans). Consumer (Task 5) calls `reclaim_due` before reading.

- [ ] Step 1: Tests: unit `test_due_idle_backoff` (1→60000, 2→120000, 3→240000, 10→600000); integration `test_reclaim_after_consumer_dies`; `test_dead_letter_after_max_deliveries_marks_failed`; `test_replay_reaches_ready`; `test_redrive_after_flushall`; `test_retention_removes_only_expired`; `test_orphan_blob_removed`.
- [ ] Step 2–4. Step 5: Commit `E5: Reclaim with backoff, dead letters, re-drive, retention`.

### Task 8: Auth, intake, idempotency, approval, document reads (E2, FR-1..7, FR-12, FR-13, CR-5)

**Files:** `api/app.py` (`create_app(settings=None, overrides=None) -> FastAPI`), `api/deps.py`, `api/auth.py` (personas from `config/personas.yaml`; header mode `X-User-Id`; OIDC kept), `api/errors.py` (JSON errors `{error_code, detail}`; DB/Redis outages → 503), `api/idempotency.py`, `api/routes/documents.py`, `api/routes/system.py` (`/healthz`, `/readyz`, `/api/me`, `/api/system/config`), `documents/repo.py`, `documents/service.py`, tests `tests/unit/test_upload_validation.py`, integration `tests/integration/test_documents_api.py`.

**Interfaces:** `validate_upload(filename: str, content_type: str|None, data: bytes, max_bytes: int) -> tuple[str, str]` returns `(kind in {'pdf','md','txt'}, sha256)` or raises `UploadError(code, status)`; service functions `create_document(conn, user, meta: DocumentMeta, file) -> VersionRef`, `create_version(...)`, `approve(conn, user, version_id, comment) -> None` (raises `Forbidden('self_approval')`, `Conflict('not_pending')`), `reject`, `retire`, `request_delete`. `VersionRef(document_id, version_id, version_number, status)`. `GET /api/me` returns user, groups, roles, sample questions, profile.

- [ ] Step 1: Tests (each with `Covers:`): `test_upload_filename_variants` (Review Focus 2); `test_reject_types_and_size`; `test_nurse_cannot_upload`; `test_upload_creates_pending_with_audit`; `test_idempotent_upload_replay_and_conflict`; `test_new_version_increments`; `test_self_approval_forbidden`; `test_concurrent_approvals_one_wins`; `test_approve_writes_outbox_row`; `test_approve_succeeds_with_redis_down` (Review Focus 3); `test_non_reader_gets_404`; `test_status_reports_progress`; `test_retire_hides_from_listing`; `test_db_down_returns_503`.
- [ ] Step 2–4. Step 5: Commit `E2: Intake, versions, idempotency and approval API`.

### Task 9: Search (E6, FR-8, FR-9, CR-2, CR-7)

**Files:** `search/query.py`, `search/snippet.py`, `api/routes/search.py`, tests unit `test_snippet.py`, integration `test_search.py`.

**Interfaces:** `async search(conn, embedder, user: User, q: str, categories: list[str]|None, departments: list[str]|None, top_k=8) -> list[SearchHit]`; `SearchHit(chunk_id, document_id, title, version_id, version_number, category, department, classification, section, page, score: float, snippet: str, highlights: list[tuple[int,int]])`. Hybrid score `0.7*vector + 0.3*normalized ts_rank_cd` (generated `tsvector` column added in a `002_search.sql` migration); max 2 hits per document. `best_window(text, terms, width=300) -> tuple[str, list[tuple[int,int]]]`. Route validates `q` length 2–500 (after strip) → 422 `invalid_query`; PHI-redacts the query (Task 10 `phi.screen`) before audit `search.performed`.

- [ ] Step 1: Tests: `test_snippet_highlights_terms`; `test_permission_isolation_by_persona`; `test_pending_and_superseded_never_returned`; `test_results_carry_title_and_version`; `test_category_filter`; `test_max_two_per_document`; `test_search_degenerate_queries` (Review Focus 4); `test_query_audit_is_redacted`.
- [ ] Step 2–4. Step 5: Commit `E6: Source-aware hybrid search`.

### Task 10: Guardrail functions (E7-1, E7-5, E7-6, E9-1, E9-2, AG-1..7, CP-2, CP-3)

**Files:** `assistant/rules.yaml`, `assistant/{classify,phi,citations,clinical,confidence,egress_policy,injection}.py` (injection = moved legacy guard), tests `tests/unit/test_classify.py`, `test_phi.py`, `test_citations.py`, `test_clinical.py`, `test_confidence.py`, `test_egress_policy.py`, `tests/unit/data/phi_cases.yaml` (40 strings).

**Interfaces:**
- `classify(text: str) -> Classification(label: Label, matched_rules: list[str], method: Literal['rule','llm','default'])`; `Label` = `policy_lookup|clinical_reference|diagnostic_support|diagnosis_request|patient_order|emergency|out_of_scope`. Rule precedence: emergency > diagnosis_request > patient_order > diagnostic_support > out_of_scope > clinical_reference > policy_lookup default.
- `phi.screen(text: str) -> PhiResult(redacted: str, findings: list[PhiFinding(type, start, end)])`; types `NAME, MRN, SSN, PHONE, EMAIL, DOB, ADDRESS`; replacement `[REDACTED-<TYPE>]`.
- `citations.verify(answer: str, passages: list[Passage]) -> CitationReport(kept_text: str, cited_ids: list[int], coverage: float, removed: int)`; overlap ≥ 0.30 of content words.
- `clinical.check(answer: str, passages: list[Passage]) -> SafetyVerdict(blocked: bool, reasons: list[str])` (quoted-and-cited exception).
- `confidence.score(passage_scores: list[float], coverage: float, distinct_docs: int, s: Settings) -> Confidence(score: int, band: Literal['High','Medium','Low'], r: float, c: float, a: float)`.
- `egress_policy.decide(info: ProviderInfo, passages: list[Passage], s: Settings) -> EgressDecision(allowed: list[Passage], withheld: dict[str,int], decision: Literal['local','external_ok','fallback_passages_only'])`.
- `injection.strip(text) -> str`, `redact_secrets(text) -> str`.
- `Passage(index: int, chunk_id, title, version_number, section, page, classification, text, score, document_id)` defined in `assistant/types.py`.

- [ ] Step 1: Tests: classifier table from spec §2.4 examples + 30 more (100% emergency & diagnosis-request); PHI set recall ≥ 0.95, FP ≤ 0.10; citations keep/remove/invalid index; clinical blocks "the patient likely has sepsis", "give 2 g ceftriaxone", allows quoted cited criteria; confidence perfect=100, no citations ≤ 50 Low, single doc A=0.6, clamping; egress table every classification × {local, external}.
- [ ] Step 2–4. Step 5: Commit `E7/E9: Classifier, PHI screening, citation and clinical guards, confidence, egress policy`.

### Task 11: Chat orchestration and SSE (E7-2..4, E7-7..9, FR-10, FR-11, AG-8..10, RL-10)

**Files:** `assistant/prompt.py` (system prompt verbatim from spec E7-3), `assistant/answer.py`, `assistant/cache.py`, `assistant/history.py`, `api/routes/chat.py`, `config/personas.yaml` (samples, category order), tests unit `test_prompt.py` (snapshot), `test_answer_pipeline.py` (fakes), integration `test_chat_api.py`.

**Interfaces:** `async answer(question: str, user: User, conversation_id: str|None, deps: ChatDeps) -> AsyncIterator[ChatEvent]`; `ChatEvent(type: Literal['classification','banner','phi','sources','token','final'], data: dict)`; final data `{answer, citations, confidence, band, parts, receipt, conversation_id, fallback}`. Receipt keys exactly: `classification, phi_redacted, provider, model, external, egress_decision, passages_withheld, checks{citations,clinical,injection}, fallback, latency_ms`. Refusal copy: `I can't make a diagnosis or patient-specific recommendation. These are the relevant hospital documents.`; no-source copy: `I couldn't find this in approved documents you can access.`; outage copy: `The answer service is unavailable; here are the most relevant passages.`; emergency banner: `If this is happening now, activate the Rapid Response / Code team per hospital procedure.` `POST /api/chat` returns `text/event-stream`; `GET/DELETE /api/conversations/{id}`.

- [ ] Step 1: Tests: `test_prompt_snapshot`; `test_low_relevance_skips_llm`; `test_injection_stripped_before_llm`; `test_diagnosis_request_refused_with_passages`; `test_emergency_banner_first`; `test_provider_outage_passages_only`; `test_restricted_passages_withheld_from_external`; `test_phi_never_reaches_provider`; `test_event_order`; `test_history_last_six_turns_redacted`; `test_delete_conversation`; `test_cache_invalidated_on_new_version`.
- [ ] Step 2–4. Step 5: Commit `E7: Guarded chat with streaming, receipts and history`.

### Task 12: Compliance and operations endpoints (E9-3, E9-5, E3-5, E11-2, E5-2 replay, UX-6, UX-8)

**Files:** `api/routes/compliance.py` (`/api/audit`, `/api/audit.csv`, `/api/egress`, `/api/deletions`, approve queue `GET /api/versions?status=PENDING_APPROVAL`), `api/routes/ops.py` (`/api/ops/streams`, `/api/ops/events?since=`, `/api/pipeline/events` SSE, `/api/ops/dead-letters`, `/api/ops/dead-letters/{id}/replay`, `POST /api/ops/drills/{name}` for `kill-worker|restart-redis|poison-file|provider-outage|retention-now`), `pipeline/drills.py`, tests integration `test_ops_api.py`, `test_compliance_api.py`.

**Interfaces:** Drills run without the Docker socket: `kill-worker` sets a Redis key `drill:kill:<consumer>` that the targeted worker checks before XACK and then `os._exit(137)` (in `RUN_MODE=all` it cancels and restarts that consumer task instead); `restart-redis` sends `SHUTDOWN SAVE` to Redis; compose `restart: always` brings it back and AOF preserves the streams; clients reconnect with backoff; `provider-outage` sets `drill:provider_outage` TTL 30 s read by embedder and LLM wrappers; `poison-file` uploads `corpus/bad/scanned.pdf` as alex and approves as taylor. Each drill emits `drill.*` ops events and audit `drill.run`. Operators get no chunk text from any ops endpoint.

- [ ] Step 1: Tests: `test_streams_endpoint_matches_redis`; `test_events_since`; `test_pipeline_sse_emits_stage_changes`; `test_operator_cannot_read_text`; `test_audit_filters_and_csv`; `test_deletion_receipt_counts`; `test_provider_outage_drill_sets_ttl`; `test_kill_worker_drill_worker_exits_and_reclaimed` (integration with subprocess worker).
- [ ] Step 2–4. Step 5: Commit `E9/E11: Compliance views, ops streams, events and drills`.

### Task 13: Observability (E11-1)

**Files:** `common/logging.py` (JSON, never logs text/question fields), `common/metrics.py` (metric names exactly from spec E11-1), `/metrics` mount, tests `tests/unit/test_logging.py`, integration `test_metrics.py`.

- [ ] Step 1: Tests: `test_log_record_drops_text_fields`; `test_metrics_exposed_after_ingest_and_chat`; `test_readyz_503_when_redis_down`.
- [ ] Step 2–4. Step 5: Commit `E11: Structured logs, Prometheus metrics, readiness`.

### Task 14: Runner, image and compose profiles (E0-2, E0-5, DP-6, DP-7)

**Files:** `run.py`, `Dockerfile` (stages: `web-build` node:20-alpine → `runtime` python:3.12-slim; build args `EXTRAS=""|"minilm"|"minilm,s3,azure"`; when `minilm` in extras, pre-download model to `/models`; non-root user; `HEALTHCHECK`), `deploy/docker-compose.yml` (profiles `lite` default: `postgres`, `redis`, `app` with `RUN_MODE=all`, memory limits pg 256m, redis 160m, app 512m; `full`: `api`, `relay`, `worker`×2, `recovery`; `airgapped`: + `ollama`; `sso`: + keycloak), `deploy/postgres.conf`, `Makefile` targets (`up`, `up-full`, `down`, `seed`, `seed-v2`, `test*`, `regression`, `eval`, `logs`, `coverage-matrix`, `reindex`, `restore-demo`), rewrite `docs/DEVELOPMENT.md`, tests `tests/integration/test_runner.py` (`RUN_MODE=all` processes a document end-to-end in one process).

- [ ] Step 1: Test `test_run_mode_all_end_to_end`; regression test `tests/regression/test_footprint.py` (marked `footprint`, run by `make footprint`): starts `lite` compose, seeds, asserts `docker stats` sum ≤ 1024 MiB and seed completes ≤ 5 min.
- [ ] Step 2–4. Step 5: Commit `E0-2: Single image, run modes and lite/full/airgapped compose profiles`.

### Task 15: Synthetic corpus and seed (E12-1, E12-2, TS-1)

**Files:** 24 documents + 4 v2 files in `corpus/` per spec E12-1 table (PDFs generated reproducibly by `corpus/build_pdfs.py` using `fpdf2` at build time inside the test/tools container), `corpus/manifest.yaml`, `corpus/manifest.schema.json`, `corpus/bad/*` (scanned.pdf = image-only, encrypted.pdf, corrupt.pdf, empty.txt, binary-renamed.md, poisoned-injection.md), `scripts/seed.py` (uses the public API with persona headers; `--v2` flag), tests `tests/unit/test_corpus.py`.

- [ ] Step 1: Tests: `test_manifest_valid_and_files_exist`; `test_every_file_has_synthetic_banner`; `test_categories_and_groups_known`; `test_v2_differs_from_v1`.
- [ ] Step 2–4 (write documents). Step 5: Commit `E12: Synthetic hospital corpus, bad fixtures and seed script`.

### Task 16: Web scaffold and design system (E10-1, E10-2, UX-9)

**Files:** `web/` (Vite React TS, Tailwind with tokens from spec E10 table, `src/api/client.ts` (fetch wrapper with persona header + SSE reader `streamChat()`), `src/api/types.ts` generated by `npm run gen:api` from `/openapi.json`, components `Button, Badge, SourceCard, ConfidenceMeter, GuardrailReceipt, SafetyBanner, DataTable, Stepper, ProgressBar, EmptyState, ErrorState, Toast, Skeleton`, route `/design`), `web/Dockerfile.test`, compose service `web-test`.

- [ ] Step 1: Vitest tests per component (render states + `vitest-axe` no violations); `ConfidenceMeter` shows band colour and R/C/A; `SourceCard` renders highlights as `<mark>` without `dangerouslySetInnerHTML`.
- [ ] Step 2–4: `make test-web` → PASS; `npm run build` in image. Step 5: Commit `E10-1/2: Web scaffold and design system`.

### Task 17: Shell, sign-in, Search, Reader (E10-3, E10-4, E10-6, UX-1, UX-2, UX-4)

**Files:** `web/src/app/{Shell,PersonaPicker,RoleGuard}.tsx`, `web/src/pages/{SearchPage,ReaderPage,ForbiddenPage}.tsx`, hooks, tests.

- [ ] Step 1: Tests (MSW): `persona picker lists 7 personas with roles`; `nav shows only permitted areas` (casey: no Search); `search syncs URL and renders cards`; `slash focuses search`; `reader scrolls to ?chunk and shows superseded banner`.
- [ ] Step 2–4. Step 5: Commit `E10-3/4/6: Shell, search and document reader`.

### Task 18: Assistant UI (E10-5, UX-3)

**Files:** `web/src/pages/AssistantPage.tsx`, `web/src/features/chat/*`, tests.

- [ ] Step 1: Tests: `streams tokens then final`; `citation chip highlights source`; `emergency banner renders above answer`; `low confidence collapses answer`; `PHI chip shown`; `passages-only shows notice not error`; `samples per persona`; `aria-live announces completion`.
- [ ] Step 2–4. Step 5: Commit `E10-5: Assistant page`.

### Task 19: Library, upload wizard, version detail, compliance pages (E10-7, E10-8, UX-5, UX-6)

**Files:** `web/src/pages/{LibraryPage,UploadWizard,VersionPage,ApprovalsPage,AuditPage,DataEgressPage,DeletionsPage}.tsx`, tests.

- [ ] Step 1: Tests: `wizard validates type and size client-side`; `idempotency key reused on double submit`; `error_code shown in plain words` (map in `src/copy/errors.ts`); `approve disabled on own upload with tooltip`; `reject requires reason`; `audit filters and CSV link`; `delete requires typing title`.
- [ ] Step 2–4. Step 5: Commit `E10-7/8: Library, upload, compliance pages`.

### Task 20: Operations board, recovery panel, accessibility pass (E10-9, E10-10, UX-7, UX-8, UX-10)

**Files:** `web/src/pages/OpsPage.tsx`, `web/src/features/ops/*`, error boundary + 401/403/404/429/5xx states, tests.

- [ ] Step 1: Tests: `cards move columns on SSE events`; `streams strip polls`; `drill asks confirmation and shows timeline`; `verify summary shows 0 duplicates`; `429 shows Retry-After countdown`; `reduced motion disables animation`.
- [ ] Step 2–4. Step 5: Commit `E10-9/10: Ops board, recovery panel, accessibility`.

### Task 21: Fault-injection integration suite (E13-2, E13-3, TS-2, RL-9)

**Files:** `tests/integration/harness.py` (`Stack` with `start_worker() -> Popen`, `kill(proc)`, `restart_redis()` via the test compose's Docker-in-test-runner: the integration container mounts `/var/run/docker.sock` only in `docker-compose.test.yml`; fallback `SHUTDOWN SAVE` + wait), `tests/integration/test_faults.py` with every row of spec E13-3.

- [ ] Step 1: Write the 13 tests named in spec E13-3; each asserts final state + no duplicates. Step 2: run 3× (`make test-integration REPEAT=3`) → PASS. Step 3: Commit `E13: Fault-injection integration tests`.

### Task 22: Evals, regression suite, coverage matrix (E12-3, E12-4, TS-5)

**Files:** `evals/cases.yaml` (≥ 74 cases, spec E12-3 mix), `evals/run.py` (reports spec §10.2 metrics; non-zero exit on miss), `tests/regression/test_eval_gate.py` (runs eval in-process against a seeded test DB with `HashingEmbedder` + `FakeLLM`), `tests/regression/test_api_contract.py` (OpenAPI snapshot at `tests/regression/openapi.snapshot.json`; changes require `UPDATE_SNAPSHOTS=1`), `tests/regression/test_acceptance.py` (AT-01…AT-24 as automated scenarios), `scripts/coverage_matrix.py`.

- [ ] Step 1: Write cases and the three regression modules. Step 2: `make regression` → PASS; `make coverage-matrix` → every Must covered. Step 3: Record calibration numbers in `docs/RESULTS.md`. Step 4: Commit `E12/E13: Eval gate, acceptance and contract regression suites`.

### Task 23: End-to-end UI tests (E13-4)

**Files:** `web/e2e/demo.spec.ts`, `web/playwright.config.ts`, compose service `e2e` (`mcr.microsoft.com/playwright:v1.49.0-jammy`) against the `lite` stack.

- [ ] Step 1: Spec walks demo script §9.2 steps 2–6 (with FakeLLM). Step 2: `make test-e2e` → PASS. Step 3: Commit `E13-4: Playwright demo e2e`.

### Task 24: CI (E0-4, E13-5, TS-4)

**Files:** `.github/workflows/ci.yml` jobs `lint`, `unit`, `integration` (service containers), `web`, `regression`, `docker` (build lite + full images), nightly `e2e`; caches; `pip-audit`/`npm audit` warn-only.

- [ ] Step 1: Validate locally with `act`-free check: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` and the same make targets pass. Step 2: Commit `E0-4: GitHub Actions CI`.

### Task 25: Cloud deployment and docs (E14, E9-6, CP-8, CP-10)

**Files:** `deploy/cloud/README.md`, `deploy/cloud/Caddyfile`, `deploy/cloud/.env.cloud.example`, `deploy/cloud/backup.sh`, rewrite `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (ADR: Redis Streams + outbox replaced Temporal; hashing/MiniLM; rules-first guardrails), `docs/SECURITY.md`, `docs/COMPLIANCE.md`, `docs/DEMO.md`, `docs/PROPOSAL.md` (export of spec).

- [ ] Step 1: `tests/unit/test_docs.py::test_no_legacy_terms` (no `Temporal`, `Kubernetes`, `helpdesk` outside DECISIONS.md history section). Step 2: PASS. Step 3: Commit `E14: Cloud deployment guide and documentation`.
