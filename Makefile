.DEFAULT_GOAL := check

UV := uv
BAZEL := bazel
BUILD_BACKEND ?= bazel
PYTHON_PATHS := src tests tools/governance/src
BAZEL_BUILD_TARGETS := //src/alpha_research:alpha_research //tools/governance/src/alpha_research_governance:all //tests/build/fixtures/sql:build_evidence //:docs_bundle

.PHONY: sync lock-check format format-check lint typecheck architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check security bazel-build bazel-test bazel-check integration-test rollback-test rollback-build rollback-check test smoke build check

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

bazel-build:
	$(BAZEL) build --config=ci $(BAZEL_BUILD_TARGETS)

bazel-test:
	UNDECLARED_HOST_SECRET=synthetic-host-only $(BAZEL) test --config=ci //:hermetic_build_tests

bazel-check: bazel-build bazel-test

integration-test:
	$(UV) run --frozen --no-editable pytest -q -m integration

rollback-test:
	$(UV) run --frozen --no-editable pytest -q

smoke:
	$(UV) run --frozen --no-editable python -c "import alpha_research"

rollback-build:
	$(UV) build --no-sources

rollback-check: lock-check lint format-check typecheck architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check security rollback-test integration-test smoke rollback-build

ifeq ($(BUILD_BACKEND),bazel)
build: bazel-build
test: bazel-test
check: bazel-check rollback-check
else ifeq ($(BUILD_BACKEND),uv)
build: rollback-build
test: rollback-test
check: rollback-check
else
$(error BUILD_BACKEND must be 'bazel' or 'uv')
endif
