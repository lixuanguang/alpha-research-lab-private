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

### Correction review slice

The second slice adds `Correction` with its first consumer, explicit `reject` and
`evidenced` policies, immutable predecessor links and effective knowledge bounded
by capture, predecessor and correction availability. Missing/invalid evidence,
unknown links, multiple successors/predecessors, cycles and reversed correction
clocks fail. Unknown original archive knowledge stays unknown; evidence may establish
the corrected version's availability. The policy supports linear distinct-payload
histories; an identical-payload reversion needs additional source revision evidence
and fails rather than silently rewriting history.

Production code-bearing changes against the duplicate slice `cbd54ff`:
**103 additions + 6 deletions = 109**. The first consumer and all required validation
stay in each independently usable slice. The combined MR is above the 150-line
preference; splitting the review into these two working commits keeps both below it.

The same four-file Ruff lint/format and strict-mypy checks passed. Focused tests in
`tests/unit/data/test_revisions.py` and `tests/unit/pipelines/test_occurrences.py`
passed **24 tests**, with no skips/deselections. The complete affected regression
selection passed **109 tests, 1 integration deselection**. A retained external
consumer at `tests/fixtures/mr10/admit_revisions.py` passes Ruff and strict mypy;
its installed execution and the fresh-kernel NB 10 run are recorded below when run.
