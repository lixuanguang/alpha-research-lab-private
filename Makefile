.DEFAULT_GOAL := check

UV := uv
BAZEL := bazel
BUILD_BACKEND ?= bazel
CI_BASE_REF ?= HEAD
CI_HEAD_REF ?= HEAD
CI_EVENT_LOG ?= build/ci/continuous-integration-events.jsonl
CI_RUN_ID ?= local
CI_ENVIRONMENT ?= local
CI_EVIDENCE_URL ?=
PYTHON_PATHS := src tests tools/governance/src
BAZEL_BUILD_TARGETS := //src/alpha_research:alpha_research //tools/governance/src/alpha_research_governance:all //tests/build/fixtures/sql:build_evidence //:docs_bundle

.PHONY: sync lock-check format format-check lint typecheck engineering-standards-check dependency-admission-check dependency-audit artifact-supply-chain-check architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check ci-policy-check remote-execution-policy-check remote-build remote-test remote-quarantine remote-local-fallback-check ci-secrets-check ci-schema-check ci-fast ci-full security bazel-build bazel-test bazel-check integration-test performance-test rollback-test rollback-build rollback-check test smoke build check

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

ci-policy-check:
	$(UV) run --frozen alpha-governance-ci

remote-execution-policy-check:
	$(UV) run --frozen alpha-governance-remote-execution

remote-build:
	$(UV) run --frozen alpha-governance-remote-execution build --context $(REMOTE_CONTEXT)

remote-test:
	$(UV) run --frozen alpha-governance-remote-execution test --context $(REMOTE_CONTEXT) --shard-index $(REMOTE_SHARD_INDEX)

remote-quarantine:
	$(UV) run --frozen alpha-governance-remote-execution quarantine --context $(REMOTE_CONTEXT)

remote-local-fallback-check:
	$(BAZEL) build --config=remote-disabled-local $(BAZEL_BUILD_TARGETS)
	UNDECLARED_HOST_SECRET=synthetic-host-only $(BAZEL) test --config=remote-disabled-local //...

ci-secrets-check:
	$(UV) run --frozen alpha-governance-ci scan-secrets --all

ci-schema-check:
	$(UV) run --frozen alpha-governance-ci schema-check --base-ref $(CI_BASE_REF)

ci-fast:
	$(UV) run --frozen alpha-governance-ci fast --base-ref $(CI_BASE_REF) --head-ref $(CI_HEAD_REF) --event-log $(CI_EVENT_LOG) --run-id $(CI_RUN_ID) --environment $(CI_ENVIRONMENT) --evidence-url "$(CI_EVIDENCE_URL)"

ci-full:
	$(UV) run --frozen alpha-governance-ci full --base-ref $(CI_BASE_REF) --event-log $(CI_EVENT_LOG) --run-id $(CI_RUN_ID) --environment $(CI_ENVIRONMENT) --evidence-url "$(CI_EVIDENCE_URL)"

security:
	$(UV) run --frozen bandit -q -c pyproject.toml -r src tools/governance/src

bazel-build:
	$(BAZEL) build --config=ci $(BAZEL_BUILD_TARGETS)

bazel-test:
	UNDECLARED_HOST_SECRET=synthetic-host-only $(BAZEL) test --config=ci //:hermetic_build_tests

bazel-check: bazel-build bazel-test

integration-test:
	$(UV) run --frozen --no-editable pytest -q -m integration

performance-test:
	$(UV) run --frozen --no-editable pytest -q -m performance

rollback-test:
	$(UV) run --frozen --no-editable pytest -q

smoke:
	$(UV) run --frozen --no-editable python -c "import alpha_research"

rollback-build:
	$(UV) build --no-sources

rollback-check: lock-check lint format-check typecheck engineering-standards-check dependency-admission-check artifact-supply-chain-check architecture-check ownership-check change-risk-check evidence-check topology-check inventory-check security-controls-check program-governance-check ci-policy-check remote-execution-policy-check security rollback-test integration-test smoke rollback-build

ifeq ($(BUILD_BACKEND),bazel)
build: bazel-build
test: bazel-test
check: ci-full
else ifeq ($(BUILD_BACKEND),uv)
build: rollback-build
test: rollback-test
check: rollback-check
else
$(error BUILD_BACKEND must be 'bazel' or 'uv')
endif
