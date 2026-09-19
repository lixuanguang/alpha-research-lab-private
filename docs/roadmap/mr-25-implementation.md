# MR 25 — Continuous quality and bounded book publication

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-18. Branch: `codex/mr-25-continuous-quality`. Base: fetched, unchanged
`origin/main` at `12be1a6`. Direct prerequisites are merged: MR 24 / PR #51 at
`12be1a6`; MRs 10–15 / PRs #34–39 at `d88ba11`, `5b10f78`, `210db65`,
`7ef4892`, `746e002`, and `69a45eb`. Their merge commits are in main's history.
The [roadmap](README.md#m3-reliable-live-capture) remains the scope authority.
[PR #52](https://github.com/lixuanguang/alpha-research-lab-private/pull/52) records
the hosted checks and merge status. Tested implementation: `98f4fad`. The merge
follow-up formats README examples, renames a test module and links this record;
runtime and notebook bytes are unchanged, so their installed evidence is reused.

## Problem / change

Native collectors previously reconstructed books without a continuous consumer
quality gate or shared immutable dataset publication. MR 25 adds receipt/source
watermarks, economic-progress freshness and latched recovery to `CaptureReplay`,
which the live pipeline already consumes after durable append. Heartbeats and
exact repeats cannot freshen economic state. Opening a connection cannot recover
it. Invalid schemas/sequences and late input block use until a fresh session's
native synchronization succeeds; the Coinbase bridge can complete on its first
contiguous update. Closed sessions are unavailable for freshness-dependent use.

The current live binding uses zero permitted lateness and `idle_seconds` as the
freshness budget. A standalone policy also exercises bounded positive lateness.
Reports retain scope, reasons, transition time, last durable receipt, economic
progress and watermarks. Source strings and receipt nanoseconds are preserved.
No source has evidence for a `valid`/complete-coverage claim: synchronized states
are explicitly degraded, and default consumers refuse them. Exploratory fresh
use requires `allow_degraded=True`; this does not enable an execution consumer.

`BookInput` binds saved Bitfinex R0, Coinbase L3, OKX live L2 and OKX historical L2
to their original request, raw digest, raw position and session/schema lineage.
`BookHistory` retains whole message boundaries and exact native orders or
aggregate levels. Unknown archive receipt, availability and sequence stay unknown.
Native duplicate handling is reused; trade revision rules are deliberately not
applied to book lifecycles. The OKX decoder now validates and commits both sides
atomically, including sequence-reset accounting. Zero-size updates delete levels;
invalid prices, sizes and malformed messages cannot produce a partial valid state.

The dataset pipeline reuses `RawStore`, `QualityReport` and `SnapshotStore` to
publish and reproduce admitted prefixes. The explicit `book-dataset-v1` schema
keeps trade manifest bytes/default readers compatible and refuses silent use of
book snapshots as trade queries. Optional paired capture arguments
`--snapshot-directory` and `--snapshot-records` call the same publication path after
raw completion. A failed publication retains the completed raw capture/summary.
The [data guide](../../src/alpha_research/data/README.md#bounded-saved-books-mr-25)
and [collector guide](../data/l3-collectors.md#mr-25-continuous-quality-and-bounded-publication)
own current API usage and limits.

## Affected scope

Against `12be1a6`: **585 added + 22 deleted = 607 production code-bearing lines**.
This exceeds the preferred 150-line target. The substantial MR 25 extension is
separated into four review commits, without another MR's behavior:

| Review slice | Working operation and first consumer | Production count |
| --- | --- | --- |
| Continuous quality | Constant-size binding state consumed by existing live/saved `CaptureReplay`; freshness-dependent refusal tests | 130 added, 0 deleted |
| Atomic L2 | Existing live/archive OKX decoder commits complete messages; native consumer regression | 20 added, 11 deleted |
| Saved admission | Validated native provenance and bounded exact canonical histories, consumed directly by installed-library admission tests | 285 added, 0 deleted |
| Publication | Book manifest verification, shared atomic snapshot reader and dataset/live pipeline callers | 152 added, 13 deleted (including two replaced import lines) |

The admission slice is a deliberate cohesive overage: strict input/record
validation, original-clock handling, four existing native input forms and the
first useful reader are reviewed together under one canonical format. Publication
is separate, as the roadmap suggests. No validation was removed or code compressed
to meet the target. Final-base counts include imports, annotations, constructors,
validation and pipeline wiring; blanks, comments, docstrings, tests/fixtures and
notebook acceptance exercises are excluded. Per-commit totals can additionally
count replaced import lines between slices. There are **no configuration,
dependency, lock, ignore-policy or executable-tooling changes**.

`SnapshotStore` retains its existing constructor and default trade type while
allowing an explicitly selected book reader. Two dated, line-local Ruff D418
annotations resolve the repository checker's requirement for overload docstrings;
no enforcement configuration is weakened. The reference book format stores full
visible state on market boundaries. This favors inspectability and uses explicit
raw/canonical byte and record bounds; it is not a throughput optimization.

## Validation result

CPython 3.14.7, macOS arm64. **173 focused tests passed in 17.41 seconds**, with
zero skips or deselections, including installed consumer and process-interruption
cases. Tests cover native L2/L3 reconstruction, Coinbase buffered bridging and
exact duplicate matches, quality watermarks and stalled progress, malformed atomic
messages, archive unknown clocks, canonical identity/reopen, publication interruption,
raw tampering, all existing capture/recovery cases and trade query compatibility.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' --basetemp=/private/tmp/mr25-reviewed-tests tests/unit/data/test_book_inputs.py tests/unit/data/test_book_datasets.py tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/venues/okx tests/unit/data/test_snapshots.py tests/unit/data/test_datasets.py tests/unit/data/test_query.py
```

Ruff lint/format passed on all seven changed runtime files, seven changed/new test
and fixture files, and the maintained notebook (15 files). Strict mypy passed on
those 14 Python files plus the affected query, replay and EDA callers (17 files).
The actual static command families and repository checks were:

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/book_datasets.py src/alpha_research/data/live/quality.py src/alpha_research/data/live/replay.py src/alpha_research/data/snapshots.py src/alpha_research/data/venues/okx/book.py src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/live.py tests/unit/data/test_book_inputs.py tests/unit/data/test_book_datasets.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_replay.py tests/unit/data/live/test_quality.py tests/unit/data/venues/okx/test_okx_book.py tests/fixtures/mr25/book_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/book_datasets.py src/alpha_research/data/live/quality.py src/alpha_research/data/live/replay.py src/alpha_research/data/snapshots.py src/alpha_research/data/venues/okx/book.py src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/live.py tests/unit/data/test_book_inputs.py tests/unit/data/test_book_datasets.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_replay.py tests/unit/data/live/test_quality.py tests/unit/data/venues/okx/test_okx_book.py tests/fixtures/mr25/book_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/book_datasets.py src/alpha_research/data/live/quality.py src/alpha_research/data/live/replay.py src/alpha_research/data/snapshots.py src/alpha_research/data/venues/okx/book.py src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/live.py src/alpha_research/data/query.py src/alpha_research/data/replay.py src/alpha_research/pipelines/eda.py tests/unit/data/test_book_inputs.py tests/unit/data/test_book_datasets.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_replay.py tests/unit/data/live/test_quality.py tests/unit/data/venues/okx/test_okx_book.py tests/fixtures/mr25/book_consumer.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/book_datasets.py src/alpha_research/data/live/quality.py src/alpha_research/data/live/replay.py src/alpha_research/data/snapshots.py src/alpha_research/data/venues/okx/book.py src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/live.py
```

Initial feedback caught a recovery fixture whose second epoch reused earlier receipt
instants; it now advances time without weakening the watermark. The first wider test
run was interrupted after stalled temporary-file work; a fresh explicit test directory
passed. Bandit identified a redundant assertion; an explicit narrowed archive branch
replaced it and the seven book tests passed before the final 173-test run. Strict typing
and documentation/format findings were corrected. One wheel-install attempt refused
to overwrite its existing environment; the final candidate uses a new directory.

### Installed consumer outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr25-validation/dist
uv run --frozen --no-sync python /private/tmp/mr25-validation/install.py
cd /private/tmp/mr25-validation/consumer
../installed-final/venv/bin/python -I ../verify_identity.py
../installed-final/venv/bin/python -I book_consumer.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' run-final
```

The temporary installer uses the existing `_InstalledWheelCheck.validate` with
hash-locked binary runtime dependencies, governance-free imports, exact-value
smoke and compatibility checks. All **78 runtime files** match source, wheel and
installation byte for byte. The tracked consumer is
`tests/fixtures/mr25/book_consumer.py`; it runs with `-I` outside the checkout,
publishes/reopens 32 saved Bitfinex positions, repeats the identity, refuses an
uninitialized prefix and an interrupted later publication, and records seven
quality transitions plus nine expected refusals. The final fixture also prints three
source-lateness boundaries and distinguishes zero-size deletion from zero-price
refusal without exposing a partial state.

- Wheel SHA-256: `9fa3c25ac71668115abe9b500101de6bcb09081ceb48c229ca13224e2579f9c5`.
- Installed implementation: `d50cfa9da61b54935bfe6cc79354fe577003edbf981f000cc30de79ef7079e2b`.
- Installed Bitfinex snapshot: `ab9655ae718826cf4225cf0e77452406389c73eec00def2d0a0d096c026bc4e3`.

Drivers, wheel, environment and `installed-evidence.json` remain under
`/private/tmp/mr25-validation`; these are local acceptance artifacts, not a release
or durable archive. Source evidence reuses the identified saved observations; no
new venue connection or Coinbase external-access claim is made.

### Fresh-kernel notebook

```sh
uv pip install --python /private/tmp/mr25-validation/installed-final/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' ALPHA_BITFINEX_CAPTURE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr25-validation/installed-final/venv/bin/python
```

All **71 cells / 35 sequential code cells passed**. Final attempt:
`c3ed196e-9020-4b80-a5cf-36b1d634a295`, completed `2026-09-18T15:26:04Z`.
Notebook source SHA-256:
`3322f954aab2a3d68da1c612dd91df42b2ffad980f9609e0e55bd6acd861b59b`.
NB 25 is section 16. Its mixed Bitfinex/OKX snapshot is
`a24030017fe094b6d806531fc00ceec9726b8a91e74537608173c68bafa07e16`, with two
32-position partitions. Original Bitfinex raw digest:
`a57ddabc5b1283c702ee2c7fd104a2b9cd943e2b41661cfc1d66619b35930163`;
OKX archive raw digest:
`fef59b343d1972c32f67583edc538c5d2f7350e6f3a0059e6f87896d7e8bf676`.
The archive retains unknown receipt and source sequence. Temporary notebook datasets
are cleaned up; identities and small outputs remain, with original saved inputs
required to reproduce them.

Failed attempt `00a6773c-c009-4f6c-9b76-ef108b85c0f5` stopped at the MR 18
historical measurement guard: snapshot format dispatch now imports book modules.
The notebook preserves the original measurement/source hashes and checks known
changed paths, but explicitly labels old timings as historical, not current-candidate
benchmarks. Attempt `d907a901-1655-4ee5-9dab-1f0699b48564` then passed; final record
validation changes triggered the rebuilt-wheel execution above. Failed and successful
attempts remain under ignored `examples/runs/`. A final fixture-only addition
made the late-event and deletion failures explicit in notebook output; its installed
integration recheck passed 1 test / 2 intentionally deselected before the final
fresh-kernel run. No runtime bytes changed for that addition, and no new performance
claim is made.

### Final source and artifact hygiene

The architecture checker passed for 58 documents; the focused example-link check
passed 101 links. Notebook schema, equality with the successful retained attempt,
35 sequential execution counts, all eight tracked example sources and kernel
cleanup passed. Generated runs/kernel/checkpoint paths remain ignored. P1,
configuration, lockfile and ignore-policy bytes match `12be1a6`. Whitespace checks
passed. The staged secret scan passed for 287 governed paths before the final review commit.

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr25-validation/final_check.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
python3 /private/tmp/mr25-validation/count_lines.py
git diff --check
git diff --cached --check
git check-ignore examples/runs/probe.ipynb examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

### Merge-time checks

The first [hosted source-validation run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35417569775)
on `98f4fad` failed the README's Python-example formatting. The repository-wide
local check then exposed a duplicate mypy module name between the new live quality
tests and the existing data quality tests. Formatting the examples and renaming
the new file to `tests/unit/data/live/test_continuous_quality.py` fixed both without
changing test assertions or runtime behavior. The historical commands above used
the original test filename.

```sh
uv run --frozen --no-sync ruff format src/alpha_research/data/README.md
make lint format-check typecheck
uv run --frozen --no-editable pytest -q tests/unit/data/live/test_continuous_quality.py tests/unit/data/test_quality.py
uv run --frozen --no-sync alpha-governance-architecture
```

Repository-wide lint and formatting passed (180 formatted files), strict mypy
passed for 179 source files, and stubtest passed for 1,548 modules. All 15 tests in
the two quality modules passed in 1.06 seconds; the architecture link check passed
for 58 documents. The final hosted results and merge status are retained in PR #52.

## Risks / reversal

Only bounded exploratory publication is admitted. Full visible state per message
can reach the byte limit quickly. Complete raw integrity is checked, but unselected
native tails are not admitted; no prefix implies whole-recording/archive coverage.
Missing source/eligibility evidence remains visible. Coinbase external acceptance,
causal availability, full depth and execution-sensitive consumers remain blocked.
`valid` is not emitted without evidence; the implementation does not invent a
completeness switch. Book query/chronological stepping and installed canonical
capture/replay parity remain MR 27. Supervision, alert delivery and clock-driven
health observation remain MR 26. R1 and existing release restrictions still apply.

At the initial implementation handoff, full local `make check` and hosted CI had
not run. PR #52 retains the subsequent hosted results; its complete hosted lane
is required before merge. No M3 completion, strategy result or deployment is claimed.
Revert the four commits in reverse order before dependent work, preserving raw
recordings. New book snapshots require this format reader; old trade snapshots
and raw captures need no migration. Frozen P1 remains byte-for-byte unchanged,
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
**Next: MR 26 — Supervise live health and responses**, after MR 25 merges. Stop here.
