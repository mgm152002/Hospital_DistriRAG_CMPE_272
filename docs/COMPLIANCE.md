# Compliance and data protection

DistriRAG runs on **synthetic data only**. The controls below are built and tested so that a future deployment with
real data starts from a sound base, but real protected health information (PHI) needs the steps in the last section
first.

## Where a question goes, by profile

| Profile | Question text | Document passages | Leaves the network? |
| --- | --- | --- | --- |
| `lite` | PHI-redacted, stored in Postgres for 30 days | not sent anywhere (no model, or the fake model) | No |
| `airgapped` | redacted, sent to Ollama on the same host | all classifications, to the local model | No (egress guard enforced) |
| `hybrid` | redacted, sent to the external provider | only `public` and `internal` (`EXTERNAL_MAX_CLASSIFICATION`) | Yes, to the configured provider only |
| `cloud` | redacted, sent to the managed provider | up to `confidential` by default | Yes |

Restricted passages are never sent to an external provider; when every useful passage is withheld, the user gets the
passages without a generated answer, and the receipt says why. Each external call is audited (`egress.llm_call`).

Both search and chat redact the question before retrieval, so identifiers do not reach the embedder. Search refuses
identifiers with `400 phi_detected` when `PHI_MODE=block`. Before including conversation history in a new prompt, the
server rechecks every cited chunk against the current active version, document ACL, retirement/deletion state and
the provider's classification limit. An ineligible turn is omitted in full. Egress audit details record the
classifications of both current passages and included history; a classification-blocked call records `called=false`
and the withheld counts. A `called=true` entry records an attempted provider invocation, including failed attempts.

See [VERIFICATION.md](VERIFICATION.md) for the current verification limits and outstanding sign-off work.

## Data inventory

| Data | Stored in | Kept for | Deleted by |
| --- | --- | --- | --- |
| Original files and extracted text | blob store (`originals/`, `text/`) | until the document is deleted | compliance deletion (receipt in audit) |
| Chunks and vectors | Postgres | as above | as above |
| Conversations (redacted) | Postgres | `CHAT_RETENTION_DAYS` (30) | daily retention job, or the user |
| Idempotency keys | Postgres | 24 hours | daily retention job |
| Audit log | Postgres (append-only trigger) | `AUDIT_RETENTION_DAYS` (365) | daily retention job only |
| Logs | container stdout | per host policy | host |
| OpenRouter credential and chat preferences | ignored server `.env`; replacements in a mode-600 private settings file/volume | until replaced by an administrator | credential rotation / deployment administrator |
| Local accounts (email, display name, groups, salted scrypt hash) | Postgres `user_accounts` | until account administration removes them | deployment administrator |
| Hashed session tokens | Postgres `auth_sessions`; opaque token in HttpOnly, SameSite=Lax cookie | 12 hours by default | sign-out revocation or daily expired-session purge |
| Hashed login-throttle identifiers | Postgres `auth_attempts` | 1 day (15-minute throttle window) | daily retention job |

## HIPAA Security Rule safeguards (technical, 45 CFR 164.312)

| Safeguard | Control | Status |
| --- | --- | --- |
| Access control | Group-based document ACLs enforced in SQL; roles for upload, approval, operations; registration grants all-staff only | Built (demo uses local cookie sessions) |
| Audit controls | Append-only audit of uploads, approvals, searches, questions (redacted), egress, deletions, drills, retention | Built |
| Integrity | Approval with separation of duties; content hash per version; versions immutable once uploaded | Built |
| Person or entity authentication | Local salted-scrypt passwords, revocable sessions, Origin checks on mutations and sign-in throttling; server-side OIDC token validation | Local accounts built; full browser SSO redirect/token flow remains future |
| Transmission security | Caddy terminates TLS in the cloud guide; `sslmode=require` enforced in the cloud profile | Built for cloud; local demo is HTTP |
| Encryption at rest | Provider disk and object-store encryption | Deployment responsibility |

## Before any real PHI

1. Sign a Business Associate Agreement with every external provider and set `baa_signed: true` only then; providers
   that keep prompts (free OpenRouter models) are refused when `SYNTHETIC_DATA_ONLY=false`.
2. Complete a risk assessment and penetration test.
3. Complete browser OIDC sign-in with your identity provider; disable header mode, demo accounts and public registration.
4. Encrypt backups; define backup retention and restore tests.
5. Review the PHI detector against your own data; consider `PHI_MODE=block`.
6. Set retention periods with your privacy officer.
