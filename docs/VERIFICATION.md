# Verification — 2026-11-26

## Final state

| Check | Result |
| --- | --- |
| GitHub Actions CI on `main` | All jobs green: lint, unit, integration, regression, web, both image builds, dependency audit |
| Backend lint and mypy | Passed; 87 source files |
| Backend unit suite | 410 passed, 5 subtests passed |
| Integration suite (real Postgres, Redis, SeaweedFS S3, Azurite) | 153 passed |
| Regression suite (acceptance AT-01…AT-24, API contract snapshot, eval gates) | 36 passed |
| Frontend suite (Vitest) | 95 passed; production build passes |
| Requirement coverage matrix | 68/68 *Must* requirements covered |
| Dependency audit | `pip-audit` clean; `npm audit --audit-level=high` clean (2 moderate react-router advisories remain) |
| GCP deployment | Continuous deployment from `main` to Compute Engine; `/readyz` reports Postgres and Redis ready at http://35.184.233.38 |
| Live corpus | 24 synthetic documents uploaded, approved and READY in 6.6 s through the public API |

`PHI_MODE=block` is the default: a question containing patient identifiers is refused before search. Tests that cover
the redact path (identifiers removed, question still answered) set `phi_mode="redact"` explicitly.

The sections below record the earlier local verification of 2026-11-25. They are kept for traceability; the counts
in them predate the final state above.

# Local verification — 2026-11-25

The local app ran in Docker at **http://localhost:8080**. These results describe the working tree at that date.

## Login and administration

- Local email/password registration and login, seven synthetic demo accounts, persistent cookie sessions and sign-out.
- Salted scrypt passwords; hashed opaque session tokens; expiry/revocation; login throttling; unsafe-method Origin checks.
- Registration grants all-staff only. Local auth ignores identity headers; disabling demo accounts invalidates demo access.
- Admin dashboard with actual document, version, account, pending/failure and usage counts, trends, categories and activity.
- Document upload and version management, independent approval/rejection, version timeline and text comparisons.
- Browser verification proves v1 publication, v2 comparison/publication and v3 rejection while v2 stays active.
- Review findings fixed: stale authenticated UI after logout following refresh, and cookie-authenticated mutation Origin
  validation. OIDC identity bootstrap compatibility is retained.

## Fresh evidence

| Check | Result |
| --- | --- |
| Backend lint and mypy | Passed; 81 source files |
| Backend unit suite | 181 passed, 5 subtests passed |
| Full integration suite (real Postgres/Redis and storage emulators) | 121 passed |
| Regression suite (acceptance, API schema, guardrail eval) | 25 passed |
| Frontend suite | 63 passed |
| TypeScript/Vite production build | Passed |
| Playwright auth/admin flow | 2 passed: registration/login/persistence/logout; upload/approve/version comparison/reject |
| Production Docker build and `make up` | Passed; container serves port 8080 |
| Live readiness and auth | `/readyz` 200; local mode; seven demo cards; header impersonation 401 |
| Live permissions and revocation | Alex analytics 200; Sam analytics 403; logged-out session 401 |
| Seed script with local cookie authentication | Passed using public API |
| OpenRouter credential/source scan | Secret absent from source; `.env` ignored and mode 0600 |

The intentional API additions are recorded in the OpenAPI snapshot. Requirement-ID references alone do not establish
full behavioral coverage, deployment compliance or real-provider acceptance.

## OpenRouter and network settings

The supplied key remains in ignored `.env`. The Settings page supports catalog-verified free models, write-only key
replacement and a persisted external AI network switch. The default is `openrouter/free`; every request has zero
price caps and no paid-model fallback. The dynamic guard checks at HTTP dispatch, including retries and queued
requests. Catalog downloads are also blocked when off; local providers remain usable. Air-gapped mode cannot enable it.

The actual key was validated successfully, and a live answer returned citations, passed output guards and scored
77 confidence. Network switching was checked through API and browser. After the auth rebuild, the live Settings API
still reports a configured key, `openrouter/free`, and enabled network access without returning the credential.

## Reliability and safety follow-up retained

- PHI redaction before search/chat retrieval and PHI block mode for search.
- Cache binding to current source versions, groups, role, model and conversation context.
- End-of-sentence citations and stricter source-quotation checks for clinical answers.
- Revalidation of history against source access, versions, deletion/retirement and classification before reuse.
- Egress audit details include historical classifications and blocked decisions.
- Document locking during finalization, including first publication; static file traversal protection.

## Section lookup regression follow-up

The question “what is the Rapid Response Team Activation Criteria” retrieved Purpose and How to call, omitting
Activation criteria because the two-passages-per-document limit was applied after ranking. The full-text index
includes the inherited document title in every section, giving them identical lexical coverage; the shorter
introductory passages then won on cosine similarity. Half of the lexical score now measures coverage of the nearest
section heading, with inherited titles excluded from that component. Chunks without headings retain their lexical
score. Permission, active-version, approval and citation checks are unchanged; no re-index is needed.

New integration cases reproduce criteria, how-to-call and purpose questions against the actual synthetic corpus,
checking both ranked search and the guarded answer. Two failed before the fix; all three pass afterward. Fresh
lint/mypy, 181 unit tests (plus 5 subtests), 121 integration tests and 25 regression tests passed. The rebuilt app was
checked in Chrome with the exact question and the real free OpenRouter provider: it returned the activation-criteria
passage, a cited answer, confidence 68, and passed citation/clinical/injection checks without a fallback.

## Remaining original-proposal gaps

- Application and retention database roles are not separated. The audit trigger uses a session setting rather than
  the proposal's database privilege separation.
- Cloud defaults disable generic host enforcement; storage SDK/OIDC traffic is not wrapped by the common HTTP guard.
  Hybrid internal database/broker connections do not yet satisfy TLS for every connection.
- Embeddings expose hashing and local MiniLM; Ollama and OpenAI-compatible embedding adapters remain absent.
- Backend OIDC validation and existing identity bootstrap are supported; full browser SSO redirect/token integration
  remains unfinished. Local registration has no email-verification or password-recovery workflow.
- The live GCP deployment is a single `e2-medium` VM over plain HTTP; HTTPS needs a domain (`GCP_DOMAIN`). GitHub
  required checks (branch protection), full real-provider acceptance, current Lighthouse scores, timed rehearsals and
  a backup recovery recording remain unverified.

These are outstanding proposal work; successful local login/admin tests do not close them.
