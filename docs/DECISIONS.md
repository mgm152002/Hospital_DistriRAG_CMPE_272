# Design decisions

## 1. Outbox + Redis Streams instead of Temporal

**History.** DistriRAG grew out of the Antara project, which coordinated ingestion with Temporal workflows on a
two-node k3s cluster with KEDA autoscaling and SigNoz observability (about 36 pods, 24 GB of RAM).

**Decision.** Replace Temporal with a transactional outbox, a relay and Redis Streams consumer groups.

**Why.** The proposal names this mechanism, and it fits weak hardware: Redis uses under 10 MB, the relay is a loop,
and the whole stack runs in about 110 MB. The guarantees Temporal gave us are rebuilt explicitly and tested: the
outbox row commits with the state change (nothing published for rolled-back work, nothing lost for committed work);
workers acknowledge only after their transaction commits; deterministic ids and unique keys make redelivery harmless;
recovery reclaims, dead-letters and re-drives.

**Trade-off.** No durable timers or long-running workflow state; DistriRAG does not need them.

## 2. One Postgres with pgvector

Permission filters and vector search run in one SQL statement, so restricted chunks are never candidates; deletion
removes chunks, vectors and cached answers in one transaction. A separate vector database would scale further and is
not needed at hospital-policy scale (thousands of chunks).

## 3. Embeddings: hashing for weak hardware, MiniLM through ONNX otherwise

The `lite` profile uses a deterministic feature-hashing embedder: no download, no model memory. Retrieval quality is
lifted with clinical abbreviation expansion, down-weighting of words found in nearly every hospital document, and a
term-coverage text score; the eval reaches 100 % hit rate at 5 on the synthetic corpus. Other profiles use
`sentence-transformers/all-MiniLM-L6-v2` through fastembed/ONNX: no PyTorch, about 235 MB of RAM, baked into the image
for air-gapped use. Thresholds are calibrated per embedder (see RESULTS.md).

## 4. Rules first for clinical safety

The classifier and the output blocker are regular expressions kept in `assistant/rules.yaml`, not model judgements:
they are fast, auditable, testable, and they work when no model is configured. Diagnosis and order requests never reach
the model. A model draft is fully verified (citations, clinical check, PHI and secret redaction) before any token is
streamed to the screen.

## 5. Confidence is computed, never asked

`100 × (0.5 R + 0.3 C + 0.2 A)`: retrieval strength, verified-citation coverage and source agreement. An answer with no
verified citation is always Low.

## 6. Header sign-in for demos, OIDC for real use

The demo maps `X-User-Id` to a persona from `config/personas.yaml` (groups come from the file, never from the client).
`AUTH_MODE=oidc` reads groups from a signed token. Header mode is not authentication and must not face a network
you do not control.

## 7. One image, one process on weak hardware

`RUN_MODE=all` runs the API, relay, workers and recovery as asyncio tasks in one process sharing one connection pool.
The kill drill restarts a consumer task there; in the `full` profile it exits the worker process and Docker restarts it.

## 8. What the persona corpus changed (UX evaluation, 2026-11)

A 60-turn corpus across seven personas and fifteen scenarios (`evals/ux/`) found gaps the guardrail eval could not:
the safety nets held, but a bare patient name was stored, rephrased dose questions skipped the order filter, two
emergency phrasings got no banner, and a question the library cannot answer returned a cited non-answer. Each fix has
a unit test, an integration or regression test that replays the corpus, and (where visible) a UI test.

| Change | Rule it follows | Why this way |
| --- | --- | --- |
| Bare names, ages and bed/room numbers are PHI | A given name from `assistant/phi_names.py` plus a capitalised surname; `Last, First`; a surname after a bed or room number | Words that are also English or clinical vocabulary (Will, Mark, Grace) are left out of the name list: a false alarm on "Mark the incident" costs more trust than a rare miss, which a title, bed number or comma still catches |
| Retrieval never sees `[REDACTED-...]` | `PhiResult.search_text` drops the placeholders | The placeholder matched nothing and made a redacted question return "couldn't find this" |
| Dose, rate and titration paraphrases are patient orders | Extra rules in `assistant/rules.yaml` | Only the egress policy had stopped a model call for "heparin drip rate for a 90 kg pt" |
| Emergencies lead with who to call | `emergency_lead` quotes the sentence with the extension; the banner stays first | A definition of Code Blue does not help someone who needs the number |
| Relevance gate | Weak retrieval must share the question's distinctive words or name the topic in a heading; strong retrieval is trusted | The citation check proves a sentence matches its passage, not that the passage answers the question |
| Model hedges are recovered, not shown | A first sentence like "the passages do not state..." triggers quoted source text if the passages cover the question, "not found" if not | The free model declined on a question its own passage answered |
| Extractive fallbacks | When the model is unavailable, unverifiable or withheld by the egress policy, show the best verbatim sentence with its source number | Passage cards alone make the user do the reading; quoted answers are capped at Medium confidence |
| Confidence recalibrated | The hashing embedder's upper bound is 0.6 not 0.85, and one fully quoted source counts as agreement | 14 correct answers scored below High; MiniLM scoring is unchanged |
| Follow-ups borrow the previous question | A short question with a pronoun or leading "and/so/ok" searches with the last user question too | "Where do I document it?" names nothing, so retrieval could never find it |
| Operators get 403 on the assistant | `require_group("all-staff")` on chat and conversations | The UI hid it, the API did not. Search still returns an empty list for operators (an existing fault test relies on it) |
| Test leftovers removed, e2e cleans up | `make clean-demo`; `removeDocuments()` in the e2e hooks | Stamped e2e titles showed up in a front-desk user's search. A document that no test creates is reported, never deleted |

**Not done on purpose.** The disclaimer is still appended to every answer: it was not in the decision list and may be a
compliance requirement. The lexical gate and the follow-up rule are heuristics; the corpus and `--repeat` runs are how
we notice when one starts to misfire.
