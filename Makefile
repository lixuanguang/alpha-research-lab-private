.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests tools/governance/src

.PHONY: sync lock-check format format-check lint typecheck architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check security test smoke build check

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

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src tools/governance/src

test:
	$(UV) run --frozen --no-editable pytest -q

smoke:
	$(UV) run --frozen --no-editable python -c "import alpha_research"

build:
	$(UV) build --no-sources

check: lock-check lint format-check typecheck architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check security test smoke build
