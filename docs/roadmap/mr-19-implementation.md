# MR 19 — Query selected data in bounded batches

Owner: repository founder. Status: implementation complete; final acceptance is
being recorded on 2026-09-17. Branch: `codex/mr-19-bounded-query`.
Base: freshly fetched `main` at `f4cb239`. MR 17, the sole prerequisite, merged
through PR #42 at `3deb34b`, an ancestor of that base. MR 18 is conditional and
not a prerequisite. Scope follows the [roadmap](README.md#m2-research-data-access-and-replay).

## Problem / change

`QueryReader` adds a working verified snapshot/reference consumer of `AsOfSelector`.
It accepts explicit input identity, instrument selection, half-open business bounds,
an inclusive knowledge cutoff and market columns. Typed batches carry query identity,
exact values, mandatory source/stream/instrument bindings, full applicable controls
and unprojectable quality/membership evidence. Selection precedes projection.
Empty results still return evidence. History mode retains earlier revision chains,
unknown original availability and membership history for MR 20's replay consumer.

The reference implementation retains canonical bytes under an explicit aggregate
byte budget. Output batch size bounds rows, including controls; it does not make
memory proportional to batch size. Complete existing admission, cross-partition
conflict checks and private per-query reconstruction remain intact. Cancellation
is cooperative before selection and between batches; closing the generator stops
iteration. There is no new backend, event stepping, EDA pipeline or publication adapter.

## Affected scope

Runtime changes are confined to `data/query.py`. `QueryReader` owns verified loading
and reference query lifetime; the three typed result containers are consumed by
its batch iterator immediately. Existing snapshot, admission, serialization,
configuration, revision and eligibility implementations remain unchanged. No wire
schema, runtime dependency, lock, declarative configuration or executable tooling changes.

The [API guide](../../src/alpha_research/data/README.md#bounded-reference-queries-mr-19),
[researcher guide](../../examples/README.md),
[NB 19 section 8](../../examples/research-foundations.ipynb) and
[installed consumer](../../tests/fixtures/mr19/query_consumer.py) exercise the same API.
The frozen P1 specification is preserved.

Against `f4cb239`, production code-bearing changes are **185 additions + 0 deletions
= 185 lines**, including imports, annotations, validation and codec use. Blank lines,
comments/docstrings and tests/notebook fixtures are excluded under the roadmap's
counting convention. The cohesive 35-line overage retains the aggregate input bound,
verified snapshot entry, binding-safe projection, query identity and explicit history
mode in one useful consumer. Splitting those declarations from their first consumer
or dropping history/control validation would leave MR 19 incomplete. No behavior was
compressed or invariant weakened to meet the preference. Declarative configuration,
dependencies and executable tooling: **zero changes**.

## Validation result

CPython 3.14.7, macOS arm64. Focused behavioral command:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_query.py tests/unit/data/test_asof.py tests/unit/data/test_revisions.py tests/unit/data/test_eligibility_selection.py tests/unit/data/test_quality.py tests/unit/data/test_datasets.py tests/unit/data/test_snapshots.py --tb=short
```

**112 passed, 3 deselected, no skips.** The three unchanged snapshot process-interruption
integration tests retain their earlier evidence; publication and its subprocess
boundaries did not change. The new query checks cover late availability and exclusion,
price-only scoped controls at the left boundary, retained original revisions after
membership withdrawal, window-retiring corrections, exact projection, stable batch-size
identity, empty evidence, cancellation/close/reuse, byte limits and original overlap
rejection. The first test attempt failed collection because a concurrent uv environment
sync removed installed modules during import. Serial environment updates followed by
`--no-sync` checks resolved the harness race; the failed attempt is not acceptance.

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/query.py tests/unit/data/test_query.py tests/fixtures/mr19 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src tests tools/governance/src tools/typing/stubs examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/query.py tests/unit/data/test_query.py tests/unit/data/test_asof.py tests/fixtures/mr19
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/query.py
uv run --frozen --no-sync alpha-governance-architecture
python3 /private/tmp/mr19-validation/verify.py
git diff --check
```

All passed. Formatting covered 162 files, strict typing four files and architecture
links 51 documents. The temporary verifier additionally checks changed component/example
README and notebook Markdown links, sequential execution counts, absence of cell errors,
notebook source identity and unchanged P1 bytes. Initial Ruff string-width/default-generic
findings and the consumer's reused variable annotation were corrected before acceptance.

Final committed-implementation wheel and fresh-kernel reproduction follow below.

## Risks / reversal

This is a capped in-memory reference reader. It reads every snapshot partition for
verification, then retains all canonical bytes; it provides no large-dataset
streaming, RSS ceiling, throughput target or mid-validation cancellation. Traced
Python allocations exclude native allocations and are not an RSS measurement.
History is a candidate input with full evidence, not a terminal eligible projection
or chronological replay. Later stepping must apply availability and membership.

Published snapshots still support the existing archive path. Captured trades and
instrument-less controls use admitted synthetic canonical fixtures. No new source
acceptance, historical membership, complete coverage, M2 completion, P1 result,
deployment or release acceptance is claimed. The existing QuantLib release
restriction remains unchanged. Hosted full merge checks remain required.

Revert this branch before dependent consumers merge; no stored-data migration or
deletion is needed. Preserve raw objects and prior snapshot/history identities.
**MR 20 — Replay with shared event stepping** is next; MR 18 remains conditional
on a measured workload and neither package was started here.
