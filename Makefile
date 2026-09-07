.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests tools/governance/src tools/typing/stubs

.PHONY: sync lock-check format format-check lint typecheck governance-check \
	program-status engineering-standards-check dependency-admission-check \
	dependency-audit artifact-supply-chain-check architecture-check ownership-check \
	change-risk-check evidence-check topology-check inventory-check \
	security-controls-check program-governance-check ci-secrets-check security \
	source-check integration-test performance-test test build wheel-smoke smoke \
	ci-full check

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

governance-check: engineering-standards-check dependency-admission-check artifact-supply-chain-check architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check

program-status:
	$(UV) run --frozen alpha-governance-program --write-status

engineering-standards-check:
	$(UV) run --frozen alpha-governance-engineering-standards

dependency-admission-check:
	$(UV) run --frozen alpha-governance-dependencies

dependency-audit:
	$(UV) run --frozen alpha-governance-dependencies audit

artifact-supply-chain-check:
	$(UV) run --frozen alpha-governance-artifacts

architecture-check:
	$(UV) run --frozen alpha-governance-architecture

ownership-check:
	$(UV) run --frozen alpha-governance-ownership

change-risk-check:
	$(UV) run --frozen alpha-governance-change-risk

evidence-check:
	$(UV) run --frozen alpha-governance-evidence

topology-check:
	$(UV) run --frozen alpha-governance-topology

inventory-check:
	$(UV) run --frozen alpha-governance-inventory

security-controls-check:
	$(UV) run --frozen alpha-governance-security

program-governance-check:
	$(UV) run --frozen alpha-governance-program

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
	$(UV) run --frozen --no-editable uv build --no-build-isolation --wheel tools/governance --out-dir dist
	$(UV) run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir dist

wheel-smoke:
	$(UV) run --frozen python -m alpha_research_governance.wheel_smoke

smoke: wheel-smoke

source-check: lock-check lint format-check typecheck governance-check security dependency-audit ci-secrets-check test

# Keep this hosted-facing alias while callers migrate off the retired scheduler.
ci-full: check

check: source-check wheel-smoke
