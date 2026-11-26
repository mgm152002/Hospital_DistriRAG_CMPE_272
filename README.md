# DistriRAG

DistriRAG indexes approved hospital policies and procedures through a reliable outbox → Redis Streams pipeline, and
lets staff find them with source-aware search and a guarded clinical-reference assistant. Every result shows its source
document and version; the assistant cites every claim, shows a confidence score, and never diagnoses or prescribes.

All documents in this repository are **synthetic**. DistriRAG is a reference tool: it does not diagnose patients,
recommend treatment, or replace clinical judgement.

## Run it (weak hardware is fine)

```bash
cp .env.example .env      # lite profile: no models to download, no keys
make up                   # postgres + redis + one app process, about 110 MB of RAM in use
make seed                 # upload and approve the 24 synthetic hospital documents
open http://localhost:8000
```

The login page supports email/password sign-in, registration and seven fictional demo accounts. Port 8000 busy?
Set `PORT=8080` in `.env`, run `make up`, then `API_URL=http://host.docker.internal:8080 make seed`.

## Accounts and the admin panel

Choose a demo card to enter immediately, or use its email and the default demo password `DemoAccess!2026`.

| Account | Email | Use it for |
| --- | --- | --- |
| Alex Morgan | `alex@distrirag.demo` | Admin analytics, document uploads, new versions and comparisons |
| Taylor Brooks | `taylor@distrirag.demo` | Approval/rejection queue, analytics, audit and compliance |
| Sam Lee | `sam@distrirag.demo` | Nursing search and assistant |
| Dr. Priya Rao | `priya@distrirag.demo` | Physician search and assistant |
| Jordan Kim | `jordan@distrirag.demo` | Pharmacy search and assistant |
| Riley Chen | `riley@distrirag.demo` | General staff search and assistant |
| Casey Diaz | `casey@distrirag.demo` | Pipeline monitoring and recovery |

**Alex uploads; Taylor approves or rejects.** Each new version needs approval. The current published version remains
available until the replacement is fully indexed. The admin panel shows document/version counts, pending approvals,
failures, accounts, usage trends, category distribution, activity, version history and a text comparison.

Registration grants general-staff access only. Sessions persist through refresh and are revoked on sign-out.
Passwords use salted scrypt; session cookies are HttpOnly and SameSite=Lax. `AUTH_MODE=local` enables accounts;
`header` retains the original persona demo and `oidc` retains server-side identity-provider validation.
Disable `DEMO_ACCOUNTS_ENABLED` outside a synthetic demo. `REGISTRATION_ENABLED` controls public registration;
`AUTH_SESSION_HOURS` defaults to 12 and `AUTH_COOKIE_SECURE=true` is required behind HTTPS. Set the demo password
before the first startup if desired; changing it later does not reset existing accounts.

| Profile | Answers from | Embeddings | Use it for |
| --- | --- | --- | --- |
| `lite` (default) | none (passages only) or `LLM_PROVIDER=fake` | hashing, no download | weak laptops, CI, demos without a model |
| `airgapped` | local Ollama | MiniLM (ONNX, baked into the image) | no network at all |
| `hybrid` | external API, behind the egress policy | MiniLM | a small cloud VM |
| `cloud` | managed API | MiniLM | managed database and storage |

## What is inside

- **Pipeline:** upload → approval (by a different person) → outbox row in the same transaction → relay → Redis Streams
  → workers (extract, chunk, embed in batches of 16, finalize) → pgvector. A version becomes searchable only when every
  chunk is embedded, and replaces the previous version atomically.
- **Reliability:** ACK after commit, deterministic chunk ids, idempotency keys, reclaim with exponential backoff,
  dead letters after 5 deliveries, re-drive of stuck versions from Postgres, and recovery drills in the UI.
- **Assistant guardrails:** PHI screening, rules-first question classifier, emergency banner, permission-filtered
  retrieval, egress policy by document classification, injection stripping, citation verification, a
  diagnosis/order blocker, a computed confidence score, and a receipt on every answer.
- **Frontend:** search, assistant, document reader with version history, library and upload wizard, compliance
  (approvals, audit log, data and egress, deletions), and a live pipeline board with recovery drills.

## OpenRouter chatbot settings

Sign in as **Alex** or **Taylor** and open **Settings** to choose a free model or replace the API key. Leave the
replacement field blank to keep the saved key. Changes apply to new questions without a restart; the setting is
shared across the application. Other staff can view the active settings.

**Network access** has an **Allow external AI network access** switch. Off blocks both chatbot and model-catalog
requests to OpenRouter, including requests queued before a settings change. Local search remains available. On permits
the official `openrouter.ai` HTTPS host; it does not permit arbitrary hosts. Air-gapped deployments lock the switch off.
Requests already sent before switching off may finish. The saved key is preserved while network access is off.

The default is `openrouter/free`, OpenRouter's [automatic free-model router](https://openrouter.ai/docs/guides/routing/routers/free-router).
The model picker lists only explicit free variants with zero catalog prices. Every OpenRouter chat request also
sets zero price caps, and no paid fallback model is sent. Rate limits or outages use the existing passages-only
fallback. Document classification, PHI screening and clinical guardrails continue to apply.

For initial setup, set `LLM_PROVIDER=openrouter-free`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL=openrouter/free` and
include `openrouter.ai` in `ALLOWED_HOSTS` in the ignored `.env`. Keep `SYNTHETIC_DATA_ONLY=true`. The API key is never
returned by the settings API or embedded in frontend files. Replacements are kept in a mode-600 server settings file;
Docker persists it in the private `chat_settings` volume. The local default directory is the ignored `data/settings/`.

To route answers through **CLIProxyAPI**, set `LLM_PROVIDER=local-proxy`,
`LOCAL_PROXY_BASE_URL=http://host.docker.internal:8317/v1`, `LOCAL_PROXY_MODEL=gpt-6-luna`, and
`LOCAL_PROXY_API_KEY` to the proxy's client key in `.env`. Add `host.docker.internal` to `ALLOWED_HOSTS`, then run
`make up`. A process running directly on macOS can use `http://127.0.0.1:8317/v1` instead. Settings will show the proxy's
models and store proxy model/key changes separately from OpenRouter. The network switch and document-classification
checks still apply because the proxy forwards requests to upstream accounts. Proxy requests use those accounts' quota;
OpenRouter's free-model policy applies only when OpenRouter is the active provider.

## Tests

Fresh checks and remaining proposal sign-off work are recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md).

`make lint` · `make test` · `make test-integration` · `make regression` · `make test-web` · `make test-e2e`
(Playwright against a running stack) · `make coverage-matrix` · `make footprint`.

## Documents

| Document | Covers |
| --- | --- |
| [docs/PROPOSAL.md](docs/PROPOSAL.md) | The revised proposal: requirements, epics, acceptance tests |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, document and question flows, profiles |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Why each major choice was made |
| [docs/SECURITY.md](docs/SECURITY.md) | OWASP Top 10 for LLM applications, mapped to controls |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | Data flows, HIPAA safeguards, what real PHI would require |
| [docs/RESULTS.md](docs/RESULTS.md) | Measured footprint, calibration, eval and fault results |
| [evals/ux/README.md](evals/ux/README.md) | Persona x scenario UX corpus, how to run it, and how its runs are logged |
| [docs/DEMO.md](docs/DEMO.md) | The 12-minute demo script and fallbacks |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, tests, folder map, owners |
| [deploy/cloud/README.md](deploy/cloud/README.md) | One small VM with HTTPS for under $25/month |

## Evaluating the assistant

```bash
make ux-eval ARGS="--gate"                # 60 persona turns against the running, seeded stack (UX_API, default :8000)
make ux-eval ARGS="--repeat 3 --export-grading 20"   # variance, plus a CSV for clinicians to grade by hand
make clean-demo                           # list test leftovers in the demo database; ARGS=--apply deletes them
```

Each run is written to `evals/ux/runs/<run id>/` with the commit, model, corpus hash and every streamed event.
`make regression` replays the same corpus in-process (no model, real Postgres) and gates on retrieval, refusals,
redaction, emergency banners and access.
