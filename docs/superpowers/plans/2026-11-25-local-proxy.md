# Local proxy routing implementation plan

**Goal:** Route DistriRAG's generated answers through the user's running CLIProxyAPI on port 8317 using `gpt-6-luna`.

**Design:** Reuse the OpenAI-compatible streaming client with a separate `local-proxy` provider. Docker reaches the
host proxy at `http://host.docker.internal:8317/v1`. Keep the proxy key server-side in the ignored `.env`; never use
the OpenRouter key for this endpoint. Proxy model/key preferences live under a separate namespace in the existing
private settings file. Existing OpenRouter preferences remain available if the deployment changes back.

The local proxy forwards to external accounts, so its provider remains external and uses the same passage
classification, network-switch, injection and citation checks. Restrict its requests to the configured origin and
the deployment host allowlist. Settings must show the active provider and its model catalog accurately.

**Implementation:** Work in the existing checkout because the running app depends on substantial uncommitted work.
Do not commit or move those changes as part of this task.

## Tasks

- [x] Add regressions for proxy preference separation, runtime model/key selection, network blocking and settings UI.
- [x] Add proxy configuration and a provider adapter; reuse streaming and keep the existing OpenRouter policy.
- [x] Update private preferences, runtime selection, settings API and UI for the configured provider.
- [x] Configure the local ignored environment using the proxy's existing client key without displaying it.
- [x] Run unit, integration and frontend checks; review the changes and rebuild the local app.
- [x] Verify the two-turn résumé conversation through the public API with `local-proxy` and `gpt-6-luna` receipts.

## Review focus

- Saved OpenRouter preferences must not override a proxy-configured deployment.
- Neither provider may receive the other's key, and responses/audits must contain no credentials.
- Disabling network access and the air-gapped profile must prevent proxy requests too.
- A proxy catalog outage must preserve the configured model and allow network access to be disabled.
- The résumé background fallback must remain useful if the proxy's upstream fails.

## Verification baseline

The preceding retrieval/provider changes passed 387 unit tests and 42 focused API tests. Local proxy unauthenticated
model listing returns 401; authenticated model listing succeeds from Docker and advertises `gpt-6-luna`.

## Current verification

- Direct GPT-6 Luna streaming probe through the proxy returned `ready` in 1.75 seconds.
- Native Python suite: 393 tests and 5 subtests pass. Mypy: 88 source files pass. Focused Ruff and diff checks pass.
- Frontend production build passes. All 88 frontend tests pass in the project's Node 20 container. The earlier native
  Node 26 run's two operations-board SSE failures do not reproduce in the supported container runtime.
- Focused code review found and resolved catalog validation accepting unverified candidate models/keys during an outage.
- The user approved restarting OrbStack. A graceful stop/start restored Docker. The rebuilt app is healthy on port
  8080; the pre-existing conductor-memory containers also restarted and are healthy.
- Live public-API verification: active provider `local-proxy`, model `gpt-6-luna`; `who is Manoj` returned a generated
  cited answer in 2.43 seconds and `what is his background` returned a generated cited answer in 2.32 seconds. Neither
  answer used fallback. The verification conversation and its login session were removed afterward.
- Docker unit suite passes: 393 tests plus 5 subtests. The complete integration suite passes: 153 tests.
