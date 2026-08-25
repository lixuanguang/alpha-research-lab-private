.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests

.PHONY: sync lock-check format format-check lint typecheck architecture-check ownership-check security test smoke build check

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
	$(UV) run --frozen python -m alpha_research.architecture_governance

ownership-check:
	$(UV) run --frozen python -m alpha_research.ownership_governance

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src

test:
	$(UV) run --frozen pytest -q

smoke:
	$(UV) run --frozen python -c "import alpha_research"

build:
	$(UV) build --no-sources

check: lock-check lint format-check typecheck architecture-check ownership-check security test smoke build
