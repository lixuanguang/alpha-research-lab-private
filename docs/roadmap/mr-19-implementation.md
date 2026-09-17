# MR 19 — Query selected data in bounded batches

Owner: repository founder. Status: implemented and locally verified for review on 2026-09-17. Branch: `codex/mr-19-bounded-query`.
Base: freshly fetched `main` at `f4cb239`. Tested implementation: `e4dbe6a`
(`e4dbe6a859da5f1472f2739324b8b4ea53b79754`). MR 17, the sole prerequisite, merged
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

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr19-validation/dist
mkdir -p /private/tmp/mr19-validation/inputs /private/tmp/mr19-validation/installed
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json /private/tmp/mr19-validation/inputs/
cp tests/fixtures/mr19/query_consumer.py /private/tmp/mr19-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr19-validation/install.py
cd /private/tmp/mr19-validation
./installed/venv/bin/python -I inputs/query_consumer.py inputs
```

The temporary installer calls the retained `_InstalledWheelCheck.validate` with the
checkout, `installed/` and built wheel. The hash-locked binary-only runtime install,
dependency compatibility, governance-free imports and exact-codec smoke all passed.
A separate byte comparison verified all **74 packaged files** against source and
the external installation. The consumer ran under `-I` outside the checkout with
only copied inputs and that installed package.

The consumer publishes two synthetic archive partitions, each with 32 original
trades and 32 evidenced corrections. Cutoffs at seconds **0, 5, 9, 10, 43200, 9**
produce known eligible counts **0, 0, 0, 64, 32, 0**. Projection returns 32 rows per
binding in batches of at most 7. History retains unknown originals and predecessors;
none becomes known merely because it was downloaded. Cancellation, generator close,
aggregate-budget rejection, immutable-ID refusal, exact revision codec round trips
and canonical tamper rejection all passed.

Measured with `tracemalloc` around reader loading and cutoff/history consumption:
**423,730 canonical bytes**, **643,491 current / 4,911,471 peak traced bytes**, under
an explicit **4,194,304-byte** canonical budget. Audit-hook counters observed **one
manifest open and four canonical opens** (verification plus materialization for each
partition); iteration, cancellation and close added **zero snapshot-file opens**.
These counters exclude raw-store reads, which the existing verifier also performs.
This one 64-row synthetic workload measures the reference implementation; it is not
a large-data scaling, latency or RSS guarantee and does not establish a need for MR 18.

Snapshot ID: `e0feebb45622e08b25e48411c767636b35f988d0d6fd1b70eca92ecdf5804061`.
Query ID: `0d7a764bc3c6a9f50b9ca56aa5e96bd0e283bb9dc0de231fcad4c1ee5ba5f4bf`.
Wheel SHA-256: `089d3669d19498781e849cf8f2091a0dc1ebf7e8ab8380c843f1d858d7706795`.
Runtime `query.py` SHA-256: `9cb8eb186c43d2bb16c8451012f62c527651869c766ecefa42c32cacfbb3da5d`.
Lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
Synthetic snapshots use temporary storage; the retained consumer recreates their
inputs, including the ZIP creation metadata. Temporary wheel/environments are local
development evidence, not a durable release archive. An earlier successful in-checkout
consumer run measured 4,909,319 peak traced bytes; only the isolated run above is
reported as external installed-consumer acceptance.

### Fresh-kernel NB 19

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
git ls-files -- examples/
git check-ignore examples/runs/example.ipynb examples/.kernel-example/kernel.json examples/.ipynb_checkpoints/example.ipynb
```

Final attempt **`619069d4-23bc-4e5b-83db-d9281c62cc5c`** ran all **36 cells / 19 code
cells** against the clean committed implementation in a fresh CPython 3.14.7 kernel.
The first cells verified all **73 runtime files** against installed `site-packages`.
Runtime content SHA-256:
`b3b18a7a4e107e83798670352216ebe49d9cb37b80a8cbbc9d067832cd5d4fc0`.
Notebook source SHA-256:
`0110d9dfbf98d564b6e91c1a30933743f5d13f113c374773ac2b672adbae9501`.
Tooling remains separate from the unchanged runtime lock: nbclient 0.10.4,
ipykernel 7.2.0 and nbformat 5.10.4. The runner closed the execution kernel.
The earlier uncommitted attempt `3df79ed0-2acf-4038-bbbb-d426911455c7` also passed;
its snapshot remains separately retained under ignored `examples/runs/`.

Section 8 reopens the prior synthetic archive snapshot and returns an empty cutoff
batch with both bindings' degraded evidence. Captured synthetic BTC prices at seconds
1/9/10/43200 are **67540.01000000 / 67540.01000000 / 67541.01000000 / unavailable**;
applicable control counts are **0/1/1/1**, with no ETH control leakage. Batch sizes 1
and 8 have identical query identity and selected content. History retains the original
and corrected prices plus all four membership assertions. Cancellation after one
batch raises `InterruptedError`. Five visible required refusals cover zero batch size,
history without a revision column, naive cutoff, excessive aggregate bytes and a
mutable snapshot alias.

The saved OKX/Bitfinex inputs are the pinned directories above, read without network
access or a new research comparison. Maintained `.ipynb`, `.py` and `.md` examples
remain tracked; generated runs, kernel files and checkpoints remain ignored under
unchanged policy. Notebook source, compact outputs and metadata were reviewed before
each commit. The final evidence-only commit changes prose and executed notebook
metadata/outputs; runtime, fixture, notebook source, lock and wheel bytes remain the
tested implementation, so their behavioral results are reused.

The P1 specification remains byte-for-byte unchanged, SHA-256
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
No full local `make check` or hosted CI result is claimed; required hosted merge
gates remain pending. Work stops at MR 19.

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
