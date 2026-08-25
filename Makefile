.DEFAULT_GOAL := check

UV := uv
PYTHON_PATHS := src tests

.PHONY: sync lock-check format format-check lint typecheck security test smoke build check

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

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src

test:
	$(UV) run --frozen pytest -q

smoke:
	$(UV) run --frozen python -c "import alpha_research"

build:
	$(UV) build --no-sources

check: lock-check lint format-check typecheck security test smoke build
