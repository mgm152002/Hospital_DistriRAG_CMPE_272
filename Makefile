TEST = docker compose -f deploy/docker-compose.test.yml
APP  = docker compose $(if $(wildcard .env),--env-file .env) -f deploy/docker-compose.yml
API_URL ?= http://host.docker.internal:8000
UX_API ?= http://localhost:8000

.PHONY: up up-full up-airgapped stop down logs ps seed seed-v2 eval build-test test test-offline lint test-integration test-web test-e2e \
        regression coverage-matrix footprint down-test ux-eval clean-demo

## Run ------------------------------------------------------------------------------------------------
up:            ## weak hardware: postgres + redis + one app process (about 1 GB RAM)
	$(APP) --profile lite up -d --build
up-full:       ## separate api / relay / 2 workers / recovery containers
	$(APP) --profile full up -d --build
up-airgapped:  ## full + local Ollama; put DEPLOYMENT_PROFILE=airgapped in .env
	EXTRAS=minilm $(APP) --profile airgapped up -d --build
stop:          ## stop containers, keep data volumes
	$(APP) --profile lite --profile full --profile airgapped stop
down:          ## remove containers and the network, keep data volumes
	$(APP) --profile lite --profile full --profile airgapped down
logs:
	$(APP) --profile lite --profile full logs -f --tail=100
ps:
	$(APP) --profile lite --profile full ps
seed:          ## upload and approve the synthetic corpus through the public API
	$(TEST) run --rm --no-deps -e API_URL=$(API_URL) unit python scripts/seed.py
ux-eval:       ## persona x scenario evaluation of the running stack (ARGS: --repeat 3, --gate, --min-pass 0.8, ...)
	python3 evals/ux/run.py --api $(UX_API) $(ARGS)
clean-demo:    ## list test leftovers in the demo database (add ARGS=--apply to delete them)
	$(TEST) run --rm --no-deps -e API_URL=$(API_URL) unit python scripts/clean_demo.py $(ARGS)
seed-v2:
	$(TEST) run --rm --no-deps -e API_URL=$(API_URL) unit python scripts/seed.py --v2
eval:          ## evaluate the running, seeded stack with its configured provider
	$(TEST) run --rm --no-deps unit python -m evals.run --api $(API_URL)

## Test -----------------------------------------------------------------------------------------------
build-test:
	$(TEST) build unit
test:
	$(TEST) run --rm unit $(if $(ARGS),pytest -q $(ARGS),)
test-offline:  ## limited dependency-free checks; full test suites still required for sign-off
	python3 scripts/verify_offline.py
lint:
	$(TEST) run --rm lint
test-integration:
	$(TEST) run --rm integration $(if $(ARGS),pytest -q -m integration $(ARGS),)
	$(TEST) down -v --remove-orphans
test-web:
	$(TEST) run --rm --no-deps web
test-e2e:      ## browser test of the demo storyline against a running stack (BASE_URL)
	$(TEST) run --rm --no-deps e2e
regression:
	$(TEST) run --rm integration pytest -q -m regression tests/regression
	$(TEST) down -v --remove-orphans
coverage-matrix:
	$(TEST) run --rm --no-deps unit python scripts/coverage_matrix.py
footprint:     ## starts the lite stack, seeds it and checks total memory (run on the host)
	python3 scripts/footprint.py
down-test:
	$(TEST) down -v --remove-orphans
