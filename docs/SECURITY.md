# Security: OWASP Top 10 for LLM applications

| Risk | Control in DistriRAG | Where | Test |
| --- | --- | --- | --- |
| LLM01 Prompt injection | Instructions in retrieved passages are stripped before the prompt; the system prompt allows answers only from numbered passages; the receipt reports stripping | `assistant/injection.py`, `assistant/prompt.py` | `test_injection_stripped_before_llm`, eval A07 |
| LLM02 Sensitive information disclosure | PHI screening and redaction on questions and answers; secret redaction on answers; logs drop text fields; operators never see document text | `assistant/phi.py`, `common/logging.py` | `test_phi.py`, `test_phi_never_reaches_provider`, AT-19 |
| LLM03 Supply chain | Pinned base images; model baked at build time; `pip-audit` and `npm audit` in CI; no PyTorch | `Dockerfile`, CI `audit` job | CI |
| LLM04 Data and model poisoning | Only documents approved by a compliance officer (not the uploader) are indexed; a poisoned fixture is part of the tests | `documents/service.py` | `test_self_approval_*`, `test_unapproved_not_indexed` |
| LLM05 Improper output handling | Answers are text with citation numbers; the UI never injects HTML (highlights are character ranges) | `web/src/components/SourceCard.tsx` | `source card marks highlights without injecting HTML` |
| LLM06 Excessive agency | The assistant has no tools and cannot change data; diagnoses and orders are refused before the model | `assistant/answer.py` | AT-16, AT-17, eval |
| LLM07 System prompt leakage | The system prompt holds no secrets; the eval checks it is not echoed | `assistant/prompt.py` | eval A07 |
| LLM08 Vector and embedding weaknesses | Permission, approval and version filters inside the vector SQL; at most two passages per document | `search/query.py` | `test_permission_isolation`, AT-08 |
| LLM09 Misinformation | Answers only from cited passages; uncited sentences removed; computed confidence; disclaimer on every answer | `assistant/citations.py`, `assistant/confidence.py` | `test_guards.py`, eval |
| LLM10 Unbounded consumption | Upload size limit; question length limit; provider concurrency cap, timeouts and retries; Redis `noeviction` with a memory cap | `common/config.py`, `common/llm/*` | `test_reject_types_and_size` |

Outside the LLM list: an egress guard refuses calls to hosts outside `ALLOWED_HOSTS`; the audit log is append-only
(a database trigger); compliance-unsafe configurations refuse to start.
