# MR 11 — Historical eligibility assertion reading

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified on 2026-09-16.
Scope is only
[MR 11](README.md#canonical-datasets-and-publication).

## Problem / change

A catalog authored in 2026 cannot prove that membership was known during a 2024
sample. `EligibilityAssertions.read` now reads strict immutable file-backed
assertions with independent validity, knowledge, state, reason and identified
evidence. It rejects backdating, conflicting overlaps and changed catalog/units,
while retaining every exclusion, including hypothetical delistings.

Started from fetched, clean `main` at `d88ba11` (PR #34). Required MR 00
(`8b53d75`, PR #14) and MR 01 (`80b5bc64`, PR #23/M0) were confirmed ancestors
of main before creating `codex/mr-11-eligibility-assertions`. Runtime, tests and
retained fixtures are committed in `e8e77e0`; subsequent documentation/notebook
evidence leaves those runtime bytes unchanged.

## Affected scope

| Operation / actual consumer | Inputs, output and state lifetime |
| --- | --- |
| `EligibilityAssertions.read`, used by NB 11 and the retained installed consumer | Explicit JSON path and selected `CatalogSnapshot` → complete immutable assertion history. One-MiB read bound; local validation state is discarded on success or failure. |
| `EligibilityAssertion` and `EligibilityEvidence` | Canonical instrument, half-open UTC valid interval, knowledge, included/excluded state, reason and document/revision identity with basis/availability/recording → validated immutable records. Constructors, unsafe nested inputs and cached `DomainCodec` decoding preserve the same invariants. |

The complete embedded catalog must match the selected catalog identity, including
currency definitions, ticks and authored metadata. Linkage does not transform that
metadata into historical fact. Exclusions may extend beyond catalog validity;
no final-date filtering drops delisted members. Conflicting included/excluded
overlaps fail even with different knowledge dates. Adjacent intervals and repeated
agreement are retained. Empty history asserts no membership. There is no selector
or implicit current projection.

Evidence identities refer to caller-retained documents/revisions; the reader checks
the supplied metadata, not authenticity or source contents. Missing/empty identities
fail, and one identity cannot hide inconsistent clocks or basis. Authored assumptions
cannot claim availability before their recording; knowledge cannot precede evidence
availability. A later recording of actual source evidence may preserve its earlier
evidenced availability. Synthetic evidence remains explicitly labeled.

The [data contract](../data/contracts.md#historical-eligibility-assertions-mr-11)
owns detailed semantics; the [component guide](../../src/market_data/README.md#read-historical-eligibility-assertions)
provides the runnable API example. The module reuses existing UTC/text validators,
catalog/financial-unit invariants and the cached exact codec. No dataset pipeline,
configuration resolver, public export, dependency or ignore policy changed.

Against actual base `d88ba11`, production code-bearing size is **101 additions +
0 deletions = 101 lines**, excluding blanks, comments, docstrings, tests/fixtures
and notebook checkpoint evidence. Imports, annotations and validation are included.
There are **zero declarative runtime configuration/dependency changes and zero
executable-tooling changes**. The synthetic JSON fixture contains the unchanged
catalog plus four explicit assertions; it is not a live configuration. The notebook
adds two evidence cells. No overage or review split is needed.

## Validation result

CPython 3.14.7; commands from the repository root unless specified otherwise.
The initial focused selection passed **64 tests**; the final affected selection
below passed **82 tests**, with **no skips or deselections**.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_eligibility.py tests/unit/test_reference_data.py tests/unit/test_configuration.py tests/unit/test_serialization.py
uv run --frozen --no-sync ruff check src/alpha_research/data/eligibility.py tests/unit/data/test_eligibility.py tests/fixtures/mr11/read_eligibility.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/eligibility.py tests/unit/data/test_eligibility.py tests/fixtures/mr11/read_eligibility.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/eligibility.py tests/unit/data/test_eligibility.py tests/fixtures/mr11/read_eligibility.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/eligibility.py
```

All static checks passed. Tests cover constructor/strict-decoder parity, exact
round trips, immutability, missing evidence/reasons, unknown fields/versions,
naive/non-UTC/reversed clocks, invented knowledge, unsafe nested instances,
contradictory nested/reordered overlaps, adjacent intervals, shared evidence
identity conflicts, unknown instruments, changed currency grids/ticks/authorship,
empty history, delisting retention, missing/oversized/malformed files and recovery.
The changed file reader has no network or process integration marker to select;
its installed boundary is exercised below.

Initial lint reported two wrapping findings, corrected by Ruff formatting before
the runtime commit. Test and notebook executions had no behavioral failures.
Sandbox uv-cache denials were retried through the required escalation path. The
documentation skill references an absent `docs/coding_standards/documentation.md`;
the actual engineering guide's Documentation section was followed.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr11-validation/final/dist
mkdir -p /private/tmp/mr11-validation/final/inputs
cp configs/reference/binance-archive-spot.json tests/fixtures/mr11/eligibility.json tests/fixtures/mr11/read_eligibility.py /private/tmp/mr11-validation/final/inputs/
uv run --frozen --no-sync python /private/tmp/mr11-validation/final/install.py
cd /private/tmp/mr11-validation/final
./venv/bin/python -I inputs/read_eligibility.py inputs
```

The temporary `install.py` invokes the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout root, external directory and built wheel. It installs hash-locked runtime
requirements with `--require-hashes --only-binary=:all:`, installs the wheel with
`--no-deps`, and runs dependency/import/codec smoke checks. All passed.

The [retained consumer](../../tests/integration/consumers/eligibility/read_eligibility.py) runs with
`-I` from the external directory, loads copied inputs and confirms external
`site-packages`. It preserved all four assertions, exact round-trip state and the
excluded member beyond catalog validity; rejected missing identity, backdated
knowledge, contradictory overlap and changed catalog units; then recovered on
the original file. Governance tooling is absent from the installed runtime.

The final wheel includes the updated component README; its installed proof was
renewed after that documentation change. Runtime bytes match those already tested
by the notebook. Final wheel SHA-256:
`dd338d2f33221b6f3c89e92c2f3944a64aa5d3092022df8f85cc637ebc79feda`.
Frozen lock SHA-256:
`e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
Synthetic eligibility fixture SHA-256:
`904fbe0c8946176387e86f1714ef8a89bf195e8f31c5a3a2c82fce521c88b127`.
These local artifacts are development evidence, not a durable release archive.

### Fresh-kernel NB 11

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

All **39 cells / 17 code cells** passed. Before interpretation the notebook checked
all **63 installed runtime files** against runtime commit `e8e77e0`, with no runtime
input diff. The existing 15 code cells are unchanged and were executed against the
same pinned, saved OKX/Bitfinex inputs; no network or new observation was required.
The runner closed the fresh execution kernel. Actual tooling was nbclient 0.10.4,
nbformat 5.10.4 and ipykernel 7.3.0 (despite the requested 7.2.0 overlay).

Completed attempt: `9ed9adad-a53c-4232-ad7e-cb999c6fb374`, retained under ignored
`examples/runs/research-foundations/`. Notebook source SHA-256:
`85c83632583a1da7e1ade38133a931e74dcc507f7f8c8e982054b57d1e09ce42`.
Runtime SHA-256:
`f77137739c4c871e478e1078e3fa3ec4f310b7aa4f2568178a9585b325d6bc43`.

Section 11 displays the same 2024 valid interval with knowledge at
`2026-09-16T00:00:00Z` for the authored assumption and at
`2024-06-01T00:00:00Z` for the synthetic evidence scenario. It retains the ETH
hypothetical delisting, reason and evidence identity. Five visible rejections cover
missing evidence, knowledge before evidence, backdated authored availability,
contradictory overlap and changed catalog units. A successful re-read follows.
This exercises the in-sample evidence contract using explicitly synthetic evidence;
it does not claim an actual historical Binance eligibility document.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr11-validation/validate.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/9ed9adad-a53c-4232-ad7e-cb999c6fb374.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review script checks notebook schema/syntax, completed execution,
source digest, unchanged previous code cells, selected Markdown/notebook links,
wheel/source/installed runtime parity and unchanged P1 bytes. All passed: six
changed documentation/notebook link inputs, 64 packaged files against the final
wheel and external installation, all notebook runtime bytes, and the runnable
component-guide example. The repository architecture check passed for 44 documents.
Maintained `.ipynb`,
`.py` and `.md` examples remain tracked; only existing generated run, kernel and
checkpoint paths are ignored. Small displayed outputs and metadata were reviewed.
No new repository validation tool or dependency was introduced.
A housekeeping assertion initially assumed no old kernel directories existed;
inspection identified three pre-existing September 13–14 directories. This run
removed its own temporary kernel directory; the older artifacts were left untouched.

At the initial local handoff, the full local suite and hosted CI had not been run;
hosted merged-result checks remain required before merge. Unchanged acquisition,
storage and decoder evidence is reused.

### Hosted merge follow-up

The founder requested merging on 2026-09-16. [PR #35](https://github.com/lixuanguang/alpha-research-lab-private/pull/35)
was opened for the required hosted checks. The
[first run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35099419897)
failed because the full formatter also checks Python snippets in Markdown: the
component README's `EligibilityAssertions.read` call needed one-line wrapping.
Ruff applied that documentation-only correction. Runtime and notebook source
bytes are unchanged; the local wheel identity above records the pre-formatting
README. The renewed hosted wheel checks cover the updated packaged README.

```sh
uv run --frozen --no-sync ruff format src/alpha_research/data/README.md
uv run --frozen --no-sync ruff format --check src tests tools/governance/src tools/typing/stubs
```

The complete formatting scope passed after correction. Runtime tests and NB 11
evidence remain applicable; current hosted results are retained on PR #35.

## Risks / reversal

Reading is bounded and in memory; this does not qualify large-history performance.
Evidence authentication and actual historical P1 membership remain unresolved.
MR 12 owns as-of selection, unknown/unsupported outcomes and append-only corrections;
MRs 13–16 own quality acceptance and publication. None is implemented or claimed here.
The existing QuantLib release restriction remains unchanged.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to main:
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR's commits before dependent consumers merge. No existing files,
datasets or source evidence need migration or deletion. After later adoption,
revert/select compatible dependent code and assertion files together.
