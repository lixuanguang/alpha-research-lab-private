# MR 17 — Read point events as of a cutoff

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified
for review on 2026-09-17. [PR #42](https://github.com/lixuanguang/alpha-research-lab-private/pull/42)
retains the hosted checks and merge result.
Branch: `codex/mr-17-asof-point-events`. Base: freshly fetched `main` at `1b02d5c`.
Required merges MR 10 (`d88ba11`), MR 12 (`210db65`) and MR 15 (`69a45eb`) are
ancestors of that base. Committed implementation and retained fixture: `972b111`
(`972b111b6f0280559e3283e2588a83fb391d1cd3`). Scope and acceptance follow the [roadmap](README.md#m2-research-data-access-and-replay).

## Problem / change

`AsOfSelector` now loads an explicitly identified, verified snapshot or existing
admitted canonical partition bytes, and selects eligible point events at independent
business and decision bounds. Availability is filtered before revision selection;
a known but out-of-window or ineligible correction never revives its predecessor.
Exact values, capture/event/acquisition clocks, revision availability and lineage
remain unchanged. Unknown archive knowledge selects no original version; later
evidence can establish a corrected version's availability.

Explicit source/stream/subscription precedence, logical partition start and raw
position resolve equal-time events without hashes. Applicable instrument-less
controls survive instrument filtering, the left query boundary and terminal control
instants. Complete canonical history and quality annotations stay separate from
cutoff results, so earlier versions remain reconstructible after a terminal query.

The [API guide](../../src/market_data/README.md#select-point-events-at-a-cutoff-mr-17)
and [NB 17](../../examples/research-foundations.ipynb) describe inputs and interpretation.

## Affected scope

Only `data/asof.py` adds runtime behavior. `AsOfSelector` owns bounded snapshot
reading and pure cutoff projection; `_Partition` is its immediately consumed strict
view of the existing canonical schema, reproducing admission through `QualityPolicy`.
`SnapshotStore`, `DomainCodec`, `TradeRevision`, `EligibilityAssertions`, `Occurrence`
and configuration remain unchanged. There is no new canonical format, runtime
dependency, configuration schema, query backend or pipeline wrapper.

Against `1b02d5c`, production code-bearing changes are **220 additions + 0 deletions
= 220 lines**, all in `data/asof.py`. Imports, annotations, validation and codecs
are included; blank/comment/docstring lines and tests/notebook fixtures are excluded.
The cohesive 70-line overage above the 150-line preference includes strict canonical
admission, cross-partition overlap/head checks, verified snapshot entry, explicit
ordering and scoped boundary controls. Splitting off declarations or omitting these
checks would leave this first reader incomplete. Reading/admitting untrusted canonical
bytes, preserving history and producing the first usable cutoff result are one
reviewable capability; no validation was removed or behavior compressed to meet the target.
Declarative configuration, dependencies/lock and executable tooling: zero changes.
Tests, the retained installed consumer and maintained notebook are acceptance inputs.

## Validation result

CPython 3.14.7, macOS arm64. Focused behavioral command:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_asof.py tests/unit/data/test_revisions.py tests/unit/data/test_eligibility_selection.py tests/unit/data/test_quality.py tests/unit/data/test_datasets.py tests/unit/data/test_snapshots.py --tb=short
```

**107 passed, 3 deselected, no skips.** The three unchanged MR 15 process-interruption
integration cases are not selected by default; their earlier evidence is reused
because publication code and its subprocess boundaries did not change.
New selector cases include late publication versus availability, prior reconstruction,
correction-window retirement, equal captures, future duplicates and changed digests,
boundary and unrelated controls, two instrument bindings, future membership withdrawal,
unknown membership, half-open validity, canonical tampering, ambiguous order,
unsupported/duplicate instrument selections, invalid clocks, and verified snapshot
reading with unknown originals, evidenced corrections, mutable IDs and damaged bytes.

Initial testing found a local misuse of `DomainCodec` for generic JSON comparison;
its supported domain decoder contract was preserved, and comparison uses a cached
strict msgspec value decoder after schema validation. All initial 16 cases failed
at that common boundary, then passed after correction. Static checks caught fixture
narrowing/import issues and Bandit's internal-assert finding. Inspection also replaced
a digest-ordered duplicate's business instant with the earliest retained point
instant, with a narrow-window future-duplicate regression. No failed attempt is
claimed as acceptance. The final focused command above was rerun after committing
the runtime and retained fixture, again passing 107 tests with three deselections.
Final static, installed-wheel and notebook results follow.


### Static checks and documentation

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/asof.py tests/unit/data/test_asof.py tests/fixtures/mr17 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/asof.py tests/unit/data/test_asof.py tests/fixtures/mr17 examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/asof.py tests/unit/data/test_asof.py tests/fixtures/mr17
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/asof.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr17-validation/verify.py
git diff --check
```

All passed. Architecture validation covered 50 documents under `docs/`. The
local verification script separately checked the changed component/researcher
READMEs and all notebook Markdown links, the notebook schema/source digest,
sequential execution counts and absence of cell errors. It compared all 68 packaged
files between source, wheel and the external installation and verified unchanged
P1 bytes. Runtime `asof.py` SHA-256:
`15752acc876a4b79f6904f32c173a82804f9b524ced952bc1f870644d1ea73eb`.
The temporary script is a verification aid, not new maintained tooling.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr17-validation/dist
mkdir -p /private/tmp/mr17-validation/inputs /private/tmp/mr17-validation/installed
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr17/asof_consumer.py /private/tmp/mr17-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr17-validation/install.py
cd /private/tmp/mr17-validation
./installed/venv/bin/python -I inputs/asof_consumer.py inputs
```

The temporary installer calls the existing `_InstalledWheelCheck.validate` with
this checkout, `installed/` and the built wheel. Its hash-locked, binary-only runtime
installation, dependency compatibility, governance-free public imports and exact
codec smoke passed. The retained
[consumer](../../tests/integration/consumers/query/asof_consumer.py) uses only the copied inputs
and external installed package. It publishes BTC and ETH together through the same
configuration path, reopens the explicit snapshot, and selects known eligible
versions at seconds `0, 5, 9, 10, 43200, 9`: counts **0, 0, 0, 2, 1, 0**.
Original archive knowledge stays null; the correction becomes usable at second 10,
and the later membership correction removes BTC's earlier interval. Exact revision
round trips, retained predecessors, mutable-ID refusal and canonical tamper rejection
all passed. Unknown coverage is never promoted to validity.

Synthetic snapshot ID:
`0cc522deb2458b7091e574314307bf8fbb12f57dd97cbf0c7a2acf607be45044`.
Wheel SHA-256:
`07d1dd335572d811a7a5adff05d1c3f1c92c9b73e6c16e39ff5bae6e40ed703d`.
Lock SHA-256:
`e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
The wheel includes the accompanying component guide; all executable runtime/fixture
bytes are the committed implementation. Temporary artifacts/environments are local
development evidence, not a durable release archive or external-source acceptance.

### Fresh-kernel NB 17

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
git ls-files -- examples/
git check-ignore examples/runs/example.ipynb examples/.kernel-example/kernel.json examples/.ipynb_checkpoints/example.ipynb
```

Final attempt **`cac00e61-e5ca-4e0e-8690-037b9462fbbf`** completed all **69 cells / 29
code cells** in a fresh CPython 3.14.7 kernel. The first cells verified all **67 runtime
files** against installed `site-packages`; runtime content SHA-256 is
`3f23e418e2e1377a0e20facf18db36bb0de84d2176ee04cd950365b15757b396`.
Notebook source SHA-256:
`0c0d728275ee4ecf5ba1be269d9a0f6e5344703acdd0936ac3e3b530ec53426c`.
The runner closed its execution kernel. Notebook tools remain separate from the
unchanged runtime lock: nbclient 0.10.4, ipykernel 7.2.0, nbformat 5.10.4.

The earlier successful attempt `5087932c-e21b-4c3a-a329-f5749f58bf13` covered all
computations but its inherited environment table reported the last duplicate
ipykernel distribution's metadata (7.3.0). An explicit import check resolved 7.2.0;
the table now uses normal metadata version resolution. The two environment cells
were corrected and every cell rerun. The prior **24 computational cells** retain
their source; no previous checkpoint, runner or saved sample was changed.

NB 17 displays unavailable → original `67540.01000000` → still original at publication
→ corrected `67541.01000000` at availability → unavailable after membership withdrawal.
Requerying the earlier cutoff retains the original version. Equal captures retain
trade IDs `[99, 1]` in raw order; one BTC disconnect survives the left query boundary
and zero unrelated ETH controls are returned. The snapshot example retains unknown
original archive availability and selects zero known rows. Five required failures
show mutable-ID, empty-window, naive-cutoff, missing-precedence and altered-quality
rejections, followed by a successful repeated query.

Saved OKX/Bitfinex inputs use the pinned directories above; their acquisition and
raw digests remain the [earlier retained observations](../../examples/notebook-operations.md#okx-and-bitfinex-migration-verification).
This run reads them without network access or a new research comparison. Maintained
notebooks, runner and Markdown guides remain tracked. The three generated-path
checks above confirm that only run snapshots, kernel files and checkpoints are
ignored; no ignore policy changed. Code, compact synthetic outputs and metadata were
reviewed before commits. Generated runs remain local-only under `examples/runs/`.

### Hosted formatting follow-up before merge

The first final-head CI attempt at `04afdf4` failed the source-validation format
step in [run 35201491710](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35201491710).
Ruff's configured directory scope also formats Python snippets in Markdown; the
new `src/alpha_research/data/README.md` example had been omitted from the earlier
explicit-path format command. Only that snippet's whitespace changed. Full
configured formatting now passes for **152 files**:

```sh
uv run --frozen --no-sync ruff format src/alpha_research/data/README.md
uv run --frozen --no-sync ruff format --check src tests tools/governance/src tools/typing/stubs
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr17-merge/dist
uv run --frozen --no-sync python /private/tmp/mr17-merge/verify_formatted_wheel.py
```

All passed. The temporary verifier compared ZIP entries against the earlier wheel:
only the component README and wheel `RECORD` changed. It repeated the existing
hash-locked wheel smoke in `/private/tmp/mr17-merge/installed/`, compared all **68
package files** with source, and ran the retained external consumer with `-I`.
The six cutoff counts remain **0, 0, 0, 2, 1, 0**; exact round trips, preserved
history, mutable-ID refusal and tamper rejection passed. This new fixture attempt's
snapshot is `dc15340075c65aafd0d034683f32e49596bd7a812dc3a9ba6e7b51ff7521fb97`.
Final formatted wheel SHA-256:
`15dea57e9a0fb9d6149af5833dc4e5a0cd6f6d621167b0b3da586bb0ca892f42`.
Runtime, tests, notebook cells/outputs, lock and P1 bytes are unchanged; their
existing behavioral/notebook evidence remains applicable. PR #42 retains the
subsequent required hosted results; this failure is not reported as a passed gate.

## Risks / reversal

Bounded in-memory reference behavior only. Selection reconstructs validated private
views for each call, keeping unsafe mutation of returned records from affecting
later queries. There is no throughput/memory benchmark, column projection, batch
iteration, cancellation, cursor, event stepping, observation invalidation, fills or
strategy result. The full hosted merge lane remains required before merge; no full local
`make check` or hosted result is claimed by the earlier focused checks above.
The linked PR owns subsequent hosted validation and the actual merge result.

Published snapshots remain archive-only. Captured-trade/control evidence uses
admitted synthetic partitions, not expanded Tardis or collector publication support.
The API does not implement `event-time-assumption-v1`; missing historical knowledge
and membership remain unavailable, and quality stays `exploratory_degraded`.
No empirical P1, M1/M2 completion, deployment or release acceptance is claimed.
The existing QuantLib release-use restriction remains unchanged.

Revert this MR's commits before dependent consumers merge; no stored-data migration
or deletion is needed. Preserve existing raw objects, snapshot IDs and history.
The frozen P1 bytes retain SHA-256
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
After MR 17 merges, **MR 19** is next by dependency order. MR 18 remains conditional
on measured need and depends on MR 19. No subsequent MR was started.
