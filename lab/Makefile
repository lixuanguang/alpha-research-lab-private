# ──────────────────────────────────────────────────────────────────────────────
# Alpha Research Lab — Top-level Makefile
# ──────────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON   ?= python
UV       ?= uv
CARGO    ?= cargo

# Experiment variables (override from CLI: make run EXP=... CONFIG=...)
EXP      ?= macro_equities
CONFIG   ?= experiments/macro_equities/configs/baseline.yaml
RUN      ?=

# ── setup ─────────────────────────────────────────────────────────────────────
.PHONY: setup

setup:  ## Install Python deps + (optional) build Rust
	$(UV) pip install -e ".[dev]"
	@echo "── Building Rust crates (optional) ──"
	-$(CARGO) build --manifest-path crates/lab_rs/Cargo.toml 2>/dev/null \
		&& echo "  Rust build OK" \
		|| echo "  Rust toolchain not found — skipping (optional)"

# ── test ──────────────────────────────────────────────────────────────────────
.PHONY: test

test:  ## Run Python + Rust test suites
	$(PYTHON) -m pytest python/tests/ -v --tb=short
	$(CARGO) test --manifest-path crates/lab_rs/Cargo.toml

# ── run ───────────────────────────────────────────────────────────────────────
.PHONY: run

run:  ## Run an experiment: make run EXP=macro_equities CONFIG=path/to/config.yaml
	$(PYTHON) scripts/run_experiment.py --exp $(EXP) --config $(CONFIG)

# ── report ────────────────────────────────────────────────────────────────────
.PHONY: report

report:  ## Generate report: make report RUN=<run_id>
ifndef RUN
	@echo "ERROR: RUN is required.  Usage: make report RUN=<run_id>"
	@exit 1
endif
	$(PYTHON) scripts/make_report.py --run_id $(RUN)

# ── lint / format (convenience) ──────────────────────────────────────────────
.PHONY: lint format

lint:  ## Run ruff linter
	$(UV) run ruff check python/ scripts/

format:  ## Auto-format with ruff
	$(UV) run ruff format python/ scripts/

# ── clean ─────────────────────────────────────────────────────────────────────
.PHONY: clean

clean:  ## Remove build artefacts
	rm -rf .pytest_cache __pycache__ dist/ target/
	find . -type d -name '__pycache__' -exec rm -rf {} +

# ── help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
