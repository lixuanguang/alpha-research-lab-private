# M0 implementation and local acceptance

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified; commit, push
and merge authorized by the founder on 2026-09-14. Implementation branch:
`codex/mr-01-02-configured-fixture`.
The [roadmap](README.md#m0-minimal-runnable-foundation) remains the sole authority
for MR ownership, dependencies and milestone acceptance. This record uses the
repository PR template and records the bounded MR 01–02 delivery.

## Problem / change

A saved source frame previously required manually selecting instruments and wiring
decoders. Versioned JSON now selects a named data job and universe, checks the
implemented capability and complete catalog interval, then identifies the resolved
manifest and per-instrument minute requests. `alpha-inspect-fixture` loads those
bindings and composes the existing Tardis/Binance decoders to return an exact trade
or an actionable diagnostic. BTCUSDT and ETHUSDT use the same implementation.

The [component command reference](../../src/alpha_research/data/README.md#configured-fixture-command)
owns current usage, identities, supported combinations, input bounds and exit codes.
Definitions do not activate themselves. Rights/revision references remain explicit
synthetic fixture declarations; the command cannot acquire data or authorize trading.

## Affected scope

- MR 01: [configuration](../../src/alpha_research/configuration.py) owns typed
  universe/job definitions, parsing, capability/interval validation and immutable
  resolution; [requests](../../src/alpha_research/data/requests.py) owns bounded
  minute partitioning and semantic identities. Their consumers are the dataset
  fixture pipeline and the completed local notebook checkpoint.
- MR 02: [dataset pipeline](../../src/alpha_research/pipelines/dataset.py) owns
  configuration/catalog I/O, decoder construction, explicit frame/clock inputs,
  result routing and exit codes. Installation adds one entry point in
  [pyproject.toml](../../pyproject.toml). Existing catalog, decoders, provenance and
  exact serialization implementation/wire formats are unchanged.
- Retained regression coverage lives in
  [configuration tests](../../tests/unit/test_configuration.py),
  [request tests](../../tests/unit/data/test_requests.py),
  [pipeline/installed-command tests](../../tests/unit/pipelines/test_dataset.py)
  and the updated [package contract](../../tests/engineering/test_package_definition.py).
  [Saved frames](../../tests/fixtures/market_data/tardis/btcusdt.txt) and
  [job definitions](../../configs/data-jobs/fixture-inspection.json) are synthetic.

Review the implementation in three usable slices: MR 01a configuration with
its working `read`/`resolve` consumer and notebook; MR 01b requests together with
MR 02's first `inspect_fixture` consumer; then MR 02's installed CLI and failure
routing. No declaration-only commit or forwarding layer is needed. The runtime
change against base `679d29fb4184b040b1afe0a737841699a2c2d679` adds
**367 production code-bearing lines, deletes 0, total 367**. The reading slices
cover 171, 123 and 73 lines respectively; these are review groupings, not fabricated
MR/commit history. The 171-line resolver is modestly above the preferred 150 lines:
its immutable records, constructor checks, strict file boundary and first complete
interval resolver belong together. Requests ship with their useful fixture consumer.
Counts exclude comments/docstrings, blank lines, tests and fixtures; include imports,
annotations, validators, codec use and entry functions. Declarative changes are
separate: 3 added TOML lines for installation and 77 added JSON configuration lines;
no dependency or lock changes. The unsupported-product JSON is a negative fixture.
The later versioned example runner adds 127 executable code lines and deletes 0,
bringing runtime plus executable tooling to 494 code-bearing lines. The notebook
is a separate worked example artifact containing foundation and M0 scenarios,
reviewed with its small synthetic outputs; it is not runtime implementation.

Objects retain only immutable configuration/reference values. Decoder instances
live for one frame inspection, and there is no persisted state or global active job.
`DomainCodec` caches strict schemas; all new record constructors enforce their own
invariants, including unsafe nested instrument revalidation before equality checks.
No native, performance, concurrency or source-access claim is added.

## Validation result

Fetched `origin` and verified local `main` matched it before creating the branch.
Environment: macOS arm64, standard CPython 3.14.7, uv 0.12.7, frozen dependencies.
The final focused command ran **105 tests, 0 failures, 0 skips, 0 deselections**,
including the explicitly selected installed-command integration case:

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' \
  tests/unit/test_configuration.py tests/unit/data/test_requests.py \
  tests/unit/pipelines/test_dataset.py tests/engineering/test_package_definition.py \
  tests/unit/test_reference_data.py tests/unit/test_serialization.py \
  tests/unit/data/providers/tardis tests/unit/data/venues/binance \
  tests/unit/data/test_decoders.py
```

The same changed Python paths passed `ruff check`, `ruff format --check` and
configured `mypy --strict` (8 files). Exact static invocation:

```sh
m0_paths=(
  src/alpha_research/configuration.py src/alpha_research/data/requests.py
  src/alpha_research/pipelines tests/unit/test_configuration.py
  tests/unit/data/test_requests.py tests/unit/pipelines/test_dataset.py
  tests/engineering/test_package_definition.py
)
uv run --frozen ruff check "${m0_paths[@]}"
uv run --frozen ruff format --check "${m0_paths[@]}"
uv run --frozen mypy --strict "${m0_paths[@]}"
uv run --frozen alpha-governance-engineering-standards
uv run --frozen bandit -q -c pyproject.toml \
  src/alpha_research/configuration.py src/alpha_research/data/requests.py \
  src/alpha_research/pipelines/dataset.py
uv lock --check
uv run --frozen alpha-governance-architecture
git diff --check
```

Engineering checks cover their configured source scope. Bandit, unchanged-lock
validation and documentation checks pass. The changed component README was also
explicitly passed to `ArchitectureGovernanceService.validate_local_links`, since
the standard command only discovers `docs/**/*.md`. Native adapters/stubs and
financial arithmetic are unchanged; focused codec/catalog/decoder regressions
and the existing wheel smoke cover the affected integration. Full `make check`
and hosted merged-result CI remain pre-merge gates; no full local suite is claimed.

### Installed consumer, outside the checkout

Built the final wheel and reused `_InstalledWheelCheck.validate` from the existing
wheel-smoke tool to install hash-locked runtime dependencies plus the wheel into
`/private/tmp/m0-final-verification/consumer/venv`. Its `-I` import/round-trip smoke and
`uv pip check` passed, and governance tooling was absent. Copied the configuration,
catalog and saved frames into the consumer's `fixtures/` directory; removed
`PYTHONPATH` and set `PYTHONNOUSERSITE=1`. All ten fresh-process cases passed.

Actual build and acceptance commands:

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/m0-final-verification/wheels
uv run --frozen --no-editable python /private/tmp/m0-final-verification/verify_installed.py
cd /private/tmp/m0-final-verification/consumer
venv/bin/alpha-inspect-fixture --config fixtures/jobs.json \
  --catalog fixtures/catalog.json --job btc-fixture --fixture fixtures/btcusdt.txt \
  --received 2026-09-14T00:00:00Z --ingested 2026-09-14T00:00:01Z --sequence 0
```

The last invocation is the shared case shape recorded by the acceptance script;
it supplies paths relative to the outside-checkout working directory. The script,
wheel, copied inputs and complete argv/output reports remain local under
`/private/tmp/m0-final-verification/`; the retained integration test provides the reusable
CLI success/failure coverage. Temporary artifacts are not a release archive.

| Case (changes to the shared command) | Exit | Observed result |
| --- | --- | --- |
| `btc-fixture`, `btcusdt.txt` | 0 | Exact BTCUSDT trade; minute offset 0 |
| `eth-fixture`, `ethusdt.txt` | 0 | Exact ETHUSDT trade through the same code |
| `both-fixture`, `ethusdt.txt` | 0 | Two-member manifest; same ETH request identity |
| `unsupported-product.json` config | 2 | Unsupported `product` rejected before frame access |
| `missing-binding.json` config | 2 | Missing universe binding named in diagnostic |
| `--job unknown` | 2 | Unknown data-job binding |
| `short-catalog.json` catalog | 2 | Complete requested interval not covered |
| BTC job with `ethusdt.txt` | 3 | Unsupported stream symbol ETHUSDT |
| `invalid-timestamp.txt` | 3 | `T must be nonnegative` |
| `absent.txt` | 4 | Local missing-file error |

The extra local negative inputs change only the BTC universe reference to
`missing`, or catalog `valid_to` to `2024-06-01T00:30:00Z`; the retained tests also
exercise these boundaries. Additional focused cases cover unknown fields and
schemas, unsupported modes/providers/pipelines/streams, minute alignment, naive
and non-UTC configuration times, reversed/empty/oversized ranges, unknown catalog
IDs, duplicate definitions/IDs, wrong payload symbols, invalid capture
or invalid/overflowed exchange timestamps, endpoint exclusion, invalid receipt metadata, bounded
file reads, depth rejection and recovery after a failed frame.

### Local notebook checkpoint and candidate identity

Completed `examples/research-foundations.ipynb`, section 10, NB 01–02, with the
installed package. Displayed BTC/ETH/both selections, 60/60/120 exact requests,
first/last bounds and offsets, content identities, prices and source/capture/local
clocks. Unsupported family and incomplete interval were rejected, followed by the
installed CLI success/wrong-instrument/unknown-binding/invalid-time cases.

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
```

Each attempt starts a fresh kernel and shuts it down. Notebook tooling is separately
identified and did not change the project lock. The initial failed attempt
`38ada143-6720-49da-b8e3-417784beae93` is retained: library scenarios passed, then
CLI discovery failed because the separate uv kernel's interpreter directory did
not contain the project command. The notebook now resolves the installed command
through `PATH`; completed attempt `c307139e-5a1f-467b-a340-607769d1336d` demonstrated
the correction. Final nested-record hardening then renewed the affected tests,
notebook and wheel evidence recorded below. Sandbox cache denials were retried
with the required permission; early typing/lint/docstring findings were fixed.

Final notebook attempt `2f6edc78-c67f-4c31-99a9-bd29d998a2ce` completed all
11 code cells with the final installed runtime, verified against 32 checkout runtime
files. Its snapshot is retained under
`examples/runs/research-foundations/2f6edc78-c67f-4c31-99a9-bd29d998a2ce.ipynb`.
Notebook source SHA-256: `7ec6f67dc7d5031d65b5aac4b09d9739e95bd30ae7fb59a6c9510c758375db04`.
The same final wheel passed all ten installed cases and the existing isolated
wheel smoke. Complete command/output and file identities are in the local
`/private/tmp/m0-final-verification/installed-results.json` and
`candidate-files.json`; source and small input bytes remain in this review change.

| Final candidate/input | SHA-256 |
| --- | --- |
| Candidate changed-file manifest (excluding this self-referential record) | `bb2ce66802abec96a6e169fd3d601563b1f89796d6bd814f0d99c198ab89ebcc` |
| Final development wheel | `d6adc8bdf935820cf79825ceb3dacdd2398e432b62af746de258d82efd1ef44e` |
| Installed runtime implementation | `4031e9c9464d557a5b879efe60f44f87cb30dc343192a5ada924fd13d9bb82bc` |
| Job configuration file | `cbbda41513b34530118982194372a1ea09e22d1800a37e7c654a6b3872b0b3ab` |
| BTC saved fixture | `30a770208c525b39a5a9f8e9eb4f21b89bdb4b48bf063d6007a9174ed1b75915` |
| ETH saved fixture | `af186c0065aab0a4a841ef9cf447bb0f7ba2628fb6428b1367a4ebba8d7fbf87` |
| BTC resolved run | `9265edaf5741eae4056d610da0e536cea828fa2be312ebc63bc8e5aa9ee09c0d` |
| ETH resolved run | `6d6bacafc0c7708605635d202ad4967398c8d5f84318fe41af4d63665709ec49` |

### Interactive notebook import repair

The editor's `.venv` contained renamed duplicates instead of all 33 expected
runtime files, causing namespace-package import failures. Reinstalling the verified
wheel with `--no-deps --reinstall --link-mode copy` restored exact file identity;
the cause of renaming was not established. Runtime, wheel, catalog and lock were
unchanged. The failure remains in local ignored `examples/runs/research-foundations/`.
Fresh-kernel attempt `0828cf38-bc7f-48b3-aa1b-6bc0b78d634b` passed all 11 code
cells with `.venv/bin/python` and ipykernel 7.3.0; notebook source SHA-256:
`77957737d7d2818310747f6bedde6b261d6fc84ce970e3d2ef88b9d861b25918`.
Current environment repair instructions live in the
[notebook operations guide](../../examples/notebook-operations.md).

## Risks / reversal

M0 is complete for the declared offline fixture workflow. It accepts one saved
nonblank uncompressed trade frame, not a file stream, disconnect sequence or
validated dataset. The catalog retains its research-assumption evidence and
one-day coverage; no historical eligibility, revision history, permitted source
access, retention right, price/quantity filter admission, book reconstruction or
empirical alpha is established. Installed code identity is content attribution,
not R1 artifact authentication. Existing QuantLib development/release restrictions
remain unchanged. No strategy, deployment, executable account or network consumer
has been introduced.

The frozen [P1 experiment](../research/p1-baseline.md), catalog and lockfile are
byte-for-byte unchanged. Reversal removes the M0 command/configuration/request
consumer and its tests/docs together; no stored data, service or state migration
is involved. Commit, push and merge were subsequently authorized; their actual revision and
hosted-check results are recorded in the pull request.

## Versioned examples and merge preparation

The founder selected tracking maintained `.ipynb`, `.py` and `.md` examples;
generated snapshots, kernel files and checkpoints remain ignored. This superseded
the initial local-only notebook policy without changing runtime or wheel bytes.

Pre-merge local validation completed in a separate environment, preserving the
editor kernel installation:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/m0-merge-check/venv UV_LINK_MODE=copy make check
```

Result: **482 tests passed, 3 performance tests deselected, no skips or failures**;
all configured static, native stub, dependency, vulnerability, secret, local-link
and isolated installed-wheel checks passed. The log remains local at
`/private/tmp/m0-merge-check/check.log`. The example runner passed focused Ruff
lint/format checks, and the example/component README links passed explicit
validation. The versioned notebook's table renderer now has a cohesive class
owner; all 11 code cells passed in fresh-kernel attempt `e8bc380c-7d2a-4f91-ac47-6880485b32f5`
(source SHA-256 `a7446076dbd0ce2bd7d1727eb1d5c82ae33507feaff60a9aa85d1935f5b89779`).
The historical notebook snapshots and validation identities above remain retained;
Git records the final maintained example and policy changes in this delivery.
