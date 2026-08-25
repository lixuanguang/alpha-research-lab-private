.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests
SOURCE_ENV := PYTHONPATH=src

.PHONY: sync lock-check format format-check lint typecheck architecture-check ownership-check change-risk-check security test smoke build check

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
	$(SOURCE_ENV) $(UV) run --frozen python -m alpha_research.architecture_governance

ownership-check:
	$(SOURCE_ENV) $(UV) run --frozen python -m alpha_research.ownership_governance

change-risk-check:
	$(SOURCE_ENV) $(UV) run --frozen python -m alpha_research.change_risk

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src

test:
	$(SOURCE_ENV) $(UV) run --frozen pytest -q

smoke:
	$(SOURCE_ENV) $(UV) run --frozen python -c "import alpha_research"

build:
	$(UV) build --no-sources

check: lock-check lint format-check typecheck architecture-check ownership-check change-risk-check security test smoke build
