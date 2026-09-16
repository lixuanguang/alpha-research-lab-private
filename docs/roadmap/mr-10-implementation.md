# MR 10 — Trade duplicate and correction admission

Owner: repository founder. Status: in progress on 2026-09-16. Scope is only
[MR 10](README.md#canonical-datasets-and-publication).

## Problem / change

Started from fetched, clean `main` at `a66b49a` (MR 09, PR #33), satisfying the
sole MR 10 prerequisite, and created `codex/mr-10-trade-revisions`.
Economic identity must survive inserted source rows and repeated raw acquisitions.

## Affected scope

The first review slice introduces duplicate admission with its saved-input pipeline
consumer. `TradeRevision.admit` consumes a complete bounded occurrence batch and
returns one immutable envelope per source/venue/instrument/stream/trade ID, retaining
all distinct raw lineage. It rejects conflicting payloads with retained diagnostics.
No correction acceptance or publication is claimed by this first slice.

Production code-bearing size against `a66b49a`: **115 additions + 0 deletions = 115**.
No dependencies or declarative configuration change. Counts exclude docstrings,
comments, blank lines, tests and notebook evidence, per the roadmap.

## Validation result

First-slice commands (repository root, CPython 3.14.7):

```sh
uv run --frozen --no-editable ruff check src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py
uv run --frozen --no-editable ruff format tests/unit/pipelines/test_occurrences.py
uv run --frozen --no-sync pytest -q tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py
uv run --frozen --no-sync mypy --strict src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py
uv run --frozen --no-sync alpha-governance-engineering-standards
```

**12 tests passed**, no skips/deselections. Strict typing and engineering rules pass.
The temporary split initially retained unsupported correction keywords in one
pipeline test; removing those restored the intended duplicate-only entry point.
The final correction slice will add its explicit policy/evidence parameters with
its working consumer. Full MR acceptance, installed-wheel and NB 10 evidence follow
in this record. Maintained example sources remain unchanged and tracked; generated
run, checkpoint and kernel paths remain ignored.

## Risks / reversal

Bounded in-memory batches only. Archive knowledge remains absent; no empirical
availability, coverage, eligibility, quality, publication or P1 result is claimed.
Revert this MR's commits before dependent consumers merge; raw objects and saved
acquisition manifests are unchanged. Preserve the frozen P1 specification.
