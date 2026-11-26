# Measured results

Measured on 2026-11-25 on an Apple Silicon laptop under Docker (OrbStack), `lite` profile: hashing embedder, fake LLM,
synthetic corpus of 24 documents plus 4 second versions. Single runs unless stated.

## Weak-hardware footprint (`make footprint`)

| Container | Memory |
| --- | --- |
| app (api + relay + 2 embed workers + extract/finalize/delete workers + recovery, one process) | 62.6 MiB |
| postgres (pgvector, shared_buffers 64 MB) | 36.3 MiB |
| redis (AOF on) | 6.9 MiB |
| **Total** | **105.8 MiB** (limit 1 024 MiB) |

Runtime image: 322 MB (no PyTorch). Seeding the corpus: 23 documents READY in 3.2 s; 4 second versions in 4.1 s.

## Relevance calibration (`scripts/calibrate.py`, spec E12-4)

Best score of the expected document vs the best score for questions that should find nothing:

| Embedder | Expected document (p10 / median) | Should find nothing (max) | `MIN_RELEVANCE` chosen |
| --- | --- | --- | --- |
| hashing, before tuning | 0.196 / 0.434 | 0.231 | — (0.35 dropped too many good passages) |
| hashing + abbreviation expansion + generic-word weighting + term-coverage text score | 0.261 / 0.455 | 0.200 | **0.15** |
| MiniLM (ONNX) | not measured in this run | | 0.35 (spec default) |

Hybrid weight: `(1 − w)·cosine + w·(share of meaningful query terms present)`, w = 0.4 for hashing, 0.3 for MiniLM.

## Guardrail and retrieval eval (`python -m evals.run`, 85 cases, fake LLM)

| Metric | Result | Threshold |
| --- | --- | --- |
| Unsafe outputs (diagnosis or patient-specific order) | 0 | 0 |
| Permission leaks | 0 | 0 |
| PHI leaks (stored or answered) | 0 | 0 |
| Classification accuracy | 1.000 | ≥ 0.95 |
| Emergency and diagnosis-request accuracy | 1.000 | 1.0 |
| Retrieval hit rate at 5 | 1.000 | ≥ 0.90 |
| Citation validity | 1.000 | ≥ 0.95 |
| Version correctness | 1.000 | 1.0 |
| Expected behaviour (answer / refuse / banner / no sources) | 0.987 | ≥ 0.90 |

Findings the eval surfaced and that are now fixed (each has a regression test): diagnosis requests fell through to
"no sources" when retrieval was weak; "write a prescription" and "what dose … to hang" were not classified as orders;
heading-only PDF chunks were cited; cached answers lost their check results in the receipt.

## Fault injection (`tests/integration/test_faults.py`, 3 consecutive runs)

17/17 passed each run (≈57 s): SIGKILL of a worker process mid-batch, relay crash after XADD, Redis restart, Redis data
loss, duplicate delivery, API crash between file and database write, transient embedding failures, five kinds of
malformed file, dead-letter and replay, version visibility, unapproved uploads, permission isolation, idempotent
upload. Every test asserts zero duplicate chunks or vectors and zero lost documents.
