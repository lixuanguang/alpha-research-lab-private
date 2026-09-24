.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests tools/governance/src tools/typing/stubs
LOCAL_SERVICES_ENV ?= secrets/local-services.env

.PHONY: sync lock-check format format-check lint typecheck governance-check \
	engineering-standards-check dependency-admission-check \
	dependency-audit architecture-check \
	ci-secrets-check security \
	source-check integration-test performance-test test build wheel-smoke check \
	local-services-up local-services-status local-services-down

# Local development only. Compose reads credentials and retained project names
# from the ignored environment file; no values are embedded in these commands.
local-services-up:
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/lakefs/compose.yaml up -d
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/clearml/compose.yaml up -d

local-services-status:
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/lakefs/compose.yaml ps
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/clearml/compose.yaml ps

local-services-down:
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/clearml/compose.yaml down
	docker compose --env-file "$(LOCAL_SERVICES_ENV)" -f configs/development/lakefs/compose.yaml down

sync:
	$(UV) sync --frozen

lock-check:
	$(UV) lock --check

format:
	$(UV) run --frozen ruff format $(PYTHON_PATHS)

format-check:
	$(UV) run --frozen ruff format --check $(PYTHON_PATHS)

lint:
	$(UV) run --frozen ruff check $(PYTHON_PATHS)

typecheck:
	$(UV) run --frozen mypy --strict $(PYTHON_PATHS)
	$(UV) run --frozen python -m mypy.stubtest --mypy-config-file=tools/typing/stubtest.toml --ignore-missing-stub QuantLib exchange_calendars pandas

governance-check: engineering-standards-check dependency-admission-check architecture-check

engineering-standards-check:
	$(UV) run --frozen alpha-governance-engineering-standards

dependency-admission-check:
	$(UV) run --frozen alpha-governance-dependencies

dependency-audit:
	$(UV) run --frozen alpha-governance-dependencies audit

architecture-check:
	$(UV) run --frozen alpha-governance-architecture

ci-secrets-check:
	$(UV) run --frozen alpha-governance-ci scan-secrets --all

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src tools/governance/src

test:
	$(UV) run --frozen --no-editable pytest -q -m 'not performance'

integration-test:
	$(UV) run --frozen --no-editable pytest -q -m integration

performance-test:
	$(UV) run --frozen --no-editable pytest -q -m performance

build:
	$(UV) run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir dist

wheel-smoke:
	$(UV) run --frozen python -m alpha_research_governance.wheel_smoke

source-check: lock-check lint format-check typecheck governance-check security dependency-audit ci-secrets-check test

check: source-check wheel-smoke
