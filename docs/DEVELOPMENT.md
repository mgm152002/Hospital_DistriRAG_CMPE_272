# Developing DistriRAG

Everything runs in Docker: you never need Python, Postgres or Redis on your machine.

## Prerequisites

- Docker Desktop, OrbStack or Docker Engine with Compose v2 (give it 2 GB of RAM or more)
- `make`, `git`, and `curl`
- Node 20 only if you work on `web/` outside Docker

## First run (5 commands)

```bash
git clone https://github.com/mgm152002/Cmpe273_DistriRag.git distrirag && cd distrirag
cp .env.example .env                 # DEPLOYMENT_PROFILE=lite: no models, no keys
make up                              # postgres + redis + one app process
make seed                            # upload and approve the synthetic hospital corpus
open http://localhost:8000           # sign in as Sam (nurse)
```

Port 8000 taken? `PORT=8080 make up` and `API_URL=http://host.docker.internal:8080 make seed`.

## Profiles

| Command | What runs | RAM |
| --- | --- | --- |
| `make up` | `lite`: postgres, redis, one `app` process running api + relay + workers + recovery | about 1 GB |
| `make up-full` | separate `api`, `relay`, 2 × `worker`, `recovery` containers | about 1.5 GB |
| `make up-airgapped` | `full` + Ollama with a local model; MiniLM embeddings baked into the image | 6–8 GB |

Switch the LLM or storage with `.env` (see `.env.example` and `config/providers.yaml`). The app refuses to start with
an unsafe combination (for example an external provider in the air-gapped profile).

## Tests

| Command | What it runs |
| --- | --- |
| `make test` | unit tests (no services) |
| `make lint` | ruff + mypy |
| `make test-integration` | Postgres, Redis, S3 (SeaweedFS) and Azurite in containers; API, pipeline, recovery, fault tests |
| `make regression` | acceptance scenarios AT-01…AT-24, API contract snapshot, guardrail eval gate |
| `make coverage-matrix` | fails if any **Must** requirement has no test |
| `make footprint` | starts the lite stack, seeds it, checks total memory ≤ 1 GB |
| `cd web && npm test` | frontend unit tests (Vitest) |

Run one file: `make test ARGS=tests/unit/test_phi.py` or `make test-integration ARGS=tests/integration/test_search.py`.

## Folder map and owners

| Folder | Holds | Owner |
| --- | --- | --- |
| `common/` | config/profiles, db, ids, audit, providers (blob, embed, llm), egress guard, logging, metrics | B |
| `pipeline/` | outbox, relay, streams, consumer, stages, recovery, drills | B |
| `documents/`, `api/` | intake, approval, read models, HTTP routes | A |
| `search/`, `assistant/` | hybrid search, guardrails, chat pipeline | A |
| `web/` | React frontend | C |
| `corpus/`, `evals/`, `tests/` | synthetic data, eval set, tests | C |
| `deploy/` | SQL, compose files, cloud guide | B |

Rules: business rules are pure functions (no I/O imports, enforced by `tests/unit/test_architecture.py`); every
test file names the requirement IDs it covers in its docstring (`Covers: RL-4, CR-3`).
