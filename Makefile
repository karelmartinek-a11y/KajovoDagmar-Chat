SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
PYTHON := backend/.venv/bin/python
RUFF := backend/.venv/bin/ruff
MYPY := backend/.venv/bin/mypy
PYTEST := backend/.venv/bin/pytest
UV := uv
NPM := npm --prefix web
COMPOSE := docker compose -f deployment/compose.yaml
EVIDENCE := release/evidence/generated

.PHONY: bootstrap dev format format-check lint typecheck test test-integration test-backend-coverage test-contract test-e2e test-accessibility test-visual test-ai test-performance test-security build migrate compose-up compose-down compose-runtime-check backup-check restore-check sbom vulnerability-gate traceability acceptance toolchain-check source-check release-check acceptance-bootstrap test-voice-browser test-voice-android test-voice-chaos autonomous-voice-acceptance provider-contract-probe clean

$(EVIDENCE):
	mkdir -p $(EVIDENCE)

toolchain-check:
	python scripts/check_toolchain.py

bootstrap:
	$(UV) sync --project backend --frozen --all-extras --python 3.12
	$(NPM) ci --ignore-scripts

source-check:
	$(PYTHON) scripts/check_forbidden.py
	$(PYTHON) scripts/check_traceability.py --allow-unverified
	$(PYTHON) -m compileall -q backend deployment migrations scripts tests
	$(PYTHON) -m json.tool GENERATION_MANIFEST.json >/dev/null
	$(PYTHON) -m json.tool RELEASE_MANIFEST.schema.json >/dev/null
	PYTHONPATH=backend/src $(PYTHON) scripts/generate_contracts.py --check

format:
	$(RUFF) format backend/src tests scripts migrations deployment/backup_agent.py
	$(RUFF) check --fix backend/src tests scripts migrations deployment/backup_agent.py
	$(NPM) run format

format-check:
	$(RUFF) format --check backend/src tests scripts migrations deployment/backup_agent.py
	$(NPM) run format:check

lint:
	$(RUFF) check backend/src tests scripts migrations deployment/backup_agent.py
	$(NPM) run lint

typecheck:
	$(MYPY) backend/src tests scripts deployment/backup_agent.py
	$(NPM) run typecheck

test: | $(EVIDENCE)
	$(PYTEST) tests/unit tests/requirements
	$(NPM) run test
	cp web/coverage/coverage-summary.json $(EVIDENCE)/coverage-frontend.json

test-integration: | $(EVIDENCE)
	$(PYTEST) -m integration tests/integration --junitxml=$(EVIDENCE)/integration.xml

test-backend-coverage: | $(EVIDENCE)
	$(PYTEST) tests/unit tests/requirements tests/integration --junitxml=$(EVIDENCE)/backend-coverage-tests.xml --cov=backend/src/kajovodagmar --cov-branch --cov-report=term-missing --cov-report=xml:$(EVIDENCE)/coverage-backend.xml --cov-report=json:$(EVIDENCE)/coverage-backend.json
	$(PYTHON) scripts/check_backend_coverage.py $(EVIDENCE)/coverage-backend.json

test-contract: | $(EVIDENCE)
	$(PYTEST) tests/contract --junitxml=$(EVIDENCE)/contract.xml

test-e2e:
	$(NPM) run e2e

acceptance-bootstrap:
	ITERATIONS=0 ./scripts/autonomous_voice_acceptance.sh

test-voice-browser:
	ITERATIONS=1 ./scripts/autonomous_voice_acceptance.sh

test-voice-android:
	ANDROID_EMULATOR_REQUIRED=true ./scripts/android_voice_acceptance.sh

test-voice-chaos:
	ITERATIONS=$${ITERATIONS:-5} ./scripts/autonomous_voice_acceptance.sh

autonomous-voice-acceptance:
	ITERATIONS=$${ITERATIONS:-5} ./scripts/autonomous_voice_acceptance.sh

provider-contract-probe:
	@test "$${KAJOVODAGMAR_SERVER_PROBE:-}" = true || (echo "Server-side only: set KAJOVODAGMAR_SERVER_PROBE=true inside the deployment container." >&2; exit 1)
	$(PYTHON) -m kajovodagmar.diagnostics.voice_live_probe

test-accessibility: | $(EVIDENCE)
	$(PYTEST) tests/accessibility --junitxml=$(EVIDENCE)/accessibility.xml

test-visual: | $(EVIDENCE)
	$(PYTEST) tests/visual --junitxml=$(EVIDENCE)/visual.xml

test-ai: | $(EVIDENCE)
	$(PYTEST) -m ai_eval tests/ai_eval --junitxml=$(EVIDENCE)/ai-eval.xml

test-performance: | $(EVIDENCE)
	$(PYTEST) -m performance tests/performance --junitxml=$(EVIDENCE)/performance.xml

test-security: | $(EVIDENCE)
	$(PYTEST) -m security tests/security --junitxml=$(EVIDENCE)/security.xml
	gitleaks dir . --redact --report-format json --report-path $(EVIDENCE)/gitleaks.json
	backend/.venv/bin/bandit -q -r backend/src -c backend/pyproject.toml -f json -o $(EVIDENCE)/bandit.json
	backend/.venv/bin/pip-audit --format cyclonedx-json --output $(EVIDENCE)/python-vulnerability-report.cdx.json
	cd web && npm audit --audit-level=high --json > ../$(EVIDENCE)/npm-audit.json

build:
	$(NPM) run build
	$(UV) build --project backend --wheel --out-dir dist
	docker build --pull --tag kajovodagmar:release-candidate --file deployment/Dockerfile .
	docker image inspect kajovodagmar:release-candidate --format='{{json .RepoDigests}}' > $(EVIDENCE)/image-digests.json

migrate:
	$(PYTHON) -m alembic upgrade head

compose-up:
	$(COMPOSE) up -d

compose-down:
	$(COMPOSE) down

compose-runtime-check: | $(EVIDENCE)
	./scripts/check_compose_runtime.sh > $(EVIDENCE)/compose-runtime-check.txt

backup-check: | $(EVIDENCE)
	./scripts/backup.sh > $(EVIDENCE)/backup-check.json

restore-check:
	./scripts/restore_check.sh

sbom:
	./scripts/generate_sbom.sh

vulnerability-gate:
	./scripts/vulnerability_scan.sh

traceability:
	$(PYTHON) scripts/check_traceability.py --evidence-dir $(EVIDENCE)

acceptance:
	$(PYTEST) tests/acceptance --junitxml=$(EVIDENCE)/acceptance.xml

release-check:
	mkdir -p $(EVIDENCE)
	rm -f $(EVIDENCE)/release-check-results.json
	./scripts/release_check.sh

clean:
	rm -rf backend/.venv dist web/dist web/node_modules .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml release/evidence/generated
