# MR 22 — Bind and verify one live source

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-18 (Asia/Singapore). Branch: `codex/mr-22-live-source`. Base: fetched `main`
at `d11dd2c`, identical to `origin/main` before branching. Prerequisites MR 01
(`80b5bc6`, PR #23), MR 03 (`bf3fb99`, PR #24) and MR 04 (`b136b36`, PR #25) were
verified merged ancestors. MR 21 is also merged through PR #47. The
[roadmap](README.md#m3-reliable-live-capture) remains the scope authority.
[PR #48](https://github.com/lixuanguang/alpha-research-lab-private/pull/48)
retains the hosted checks and merge status. Tested implementation: `e649f9d`.

## Problem / change

The early collector already supplies the configured direct Bitfinex spot R0 path.
MR 22 completes its bounded source verification: outbound subscription sends now
use the remaining capture deadline, and advertised Bitfinex protocol versions other
than integer 2 are refused. A blocked send closes the socket and retains an
unavailable session; unsupported negotiation never admits a usable book.

`collect` owns the send lifetime and failure handling. `BitfinexBook` owns protocol
validation. Existing `CaptureConfig`, `CaptureRequest`, `VenueTransport`, exact
`Wire` decoding, `CaptureJournal`, raw storage and `CaptureReplay` remain the working
consumers and contracts. No new schema, wrapper, transport, stream or dependency is
introduced. The [source contract](../data/l3-collectors.md#mr-22-verified-source-contract)
defines source/session identity, acknowledgements, coverage, clocks, access,
heartbeat/lifetime and checked rate-limit assumptions.

## Affected scope

Against `d11dd2c`: **6 added + 1 deleted = 7 production code-bearing physical lines**,
all in the two runtime modules. No overage. Tests, notebook acceptance exercises,
comments/docstrings and prose are excluded under the roadmap definition. No
maintained executable tooling, declarative configuration, dependency, lockfile,
public export or ignore-policy change. Existing serialized captures remain readable;
a source that advertises an unsupported version is intentionally rejected.

The source acceptance selects one existing `tBTCUSD` spot R0/F0 job at depth 25.
It uses the maintained 20-second budget to include a documented 15-second heartbeat,
one channel and one actual connection. No rate-limit stress probe is needed. The
research notebook adds NB 22 in section 12, inspecting the saved negotiation and
six controlled refusals without network access. Both the researcher and operations
guides describe the new checkpoint. No MR 23 implementation is included.

## Validation result

CPython 3.14.7, macOS arm64. **57 focused tests passed in 5.86 seconds; zero skips
or deselections.** These include Bitfinex and shared capture regressions plus
Coinbase/OKX callers of the changed send path. New cases cover blocked subscription,
rejected source sessions, malformed/unsupported advertised versions, pre-acknowledgement
heartbeats/market frames and unsupported venue/product/stream selections.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/venues/okx/test_okx_capture.py
uv run --frozen --no-sync ruff check src/alpha_research/pipelines/live.py src/alpha_research/data/venues/bitfinex/book.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_config.py tests/unit/data/venues/bitfinex/test_bitfinex_book.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/pipelines/live.py src/alpha_research/data/venues/bitfinex/book.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_config.py tests/unit/data/venues/bitfinex/test_bitfinex_book.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/pipelines/live.py src/alpha_research/data/venues/bitfinex/book.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_config.py tests/unit/data/venues/bitfinex/test_bitfinex_book.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/pipelines/live.py src/alpha_research/data/venues/bitfinex/book.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
uv run --frozen --no-sync --with 'nbformat==5.10.4' python -c 'import nbformat; nbformat.validate(nbformat.read("examples/research-foundations.ipynb", as_version=4)); print("Notebook schema valid")'
uv run --frozen --no-sync python /private/tmp/mr22-validation/final_check.py
git diff --check
```

Focused static checks, repository engineering standards, notebook schema and local
links passed (55 governed documents plus 72 example/notebook links). Strict mypy
checked five changed Python files; secret scanning passed 273 governed paths.
The local final verifier also checked sequential
cell execution, snapshot equality, tracked examples, preserved bytes and review size. At the initial implementation handoff, complete local `make check` and hosted CI
were not run. PR #48 retains the subsequent hosted results; the complete hosted
lane remains required before merge. Existing unrelated acquisition, publication and performance evidence
is retained; no new empirical research result is claimed.

### Installed consumer and actual source

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr22-validation/dist
mkdir -p /private/tmp/mr22-validation/installed /private/tmp/mr22-validation/inputs
cp configs/live/bitfinex-btc-usd.json /private/tmp/mr22-validation/inputs/bitfinex.json
uv run --frozen --no-sync python /private/tmp/mr22-validation/install.py
cd /private/tmp/mr22-validation
./installed/venv/bin/alpha-collect probe --config inputs/bitfinex.json
./installed/venv/bin/alpha-collect capture --config inputs/bitfinex.json --output captures > capture-result.json
./installed/venv/bin/python -I verify_installed.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private'
```

The local installer calls existing `_InstalledWheelCheck.validate` with the checkout,
`installed/` and the candidate wheel. Frozen hash-locked binary-only dependencies,
governance-free imports, exact codec smoke and dependency compatibility passed.
The local verification script compared all **76 runtime files** across source,
wheel and installed inventory, bound the capture implementation/configuration,
checked actual negotiation and CLI/replay parity, and verified unsupported config
exits **2 before creating output**. It runs under `-I` outside the checkout and saves
`installed-evidence.json`. These temporary scripts and artifacts are local evidence,
not new maintained tooling or a durable release archive.

Discovery returned `available=true`, SHA-256
`ad5c2c16d99b75060bdfcb43aa70faa233931623d8b9539ab1bac659eb2130dc`.
The real recording is `captures/ffb21fbf-9357-4b68-b593-3f1e7be45d9a` under that
external work directory: **498 messages, one snapshot, 493 updates, one heartbeat,
50 visible orders, one epoch, zero detected gaps**. Negotiation acknowledged
version 2, flags 65536, channel 461284, `tBTCUSD`, R0/F0 and length 25. Server
sequences ran from 1 to 495; source timestamp is absent. Exact first/last receipt
integers are `1789663921432175000` and `1789663940692253000` (2026-09-17
16:52:01.432175–16:52:20.692253 UTC). Nanosecond storage is not clock-accuracy proof.

The 69,260-byte saved input has SHA-256
`c9d04ce6caa1bf378c5aa3c391dd65242d2787de8f08a01b93d60c07ec106457`.
Captured/offline trace identity is
`c7c559e2f6d2e58f92f14860269f8345dfdbfaeaa26b2ea83986b911e972f4cc`.
The first sandboxed probe failed before source verification; the permitted network
retry passed. Cache/kernel commands also needed sandbox permission. These access
failures are not venue or product failures, and no failed capture was discarded.

### Fresh-kernel NB 22

From the checkout after installing the wheel:

```sh
uv pip install --python /private/tmp/mr22-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=/private/tmp/mr22-validation/captures/ffb21fbf-9357-4b68-b593-3f1e7be45d9a uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr22-validation/installed/venv/bin/python
```

All **55 cells / 28 code cells passed**, including complete installed-import byte
verification, saved book reconstruction, prior dataset/query/EDA checkpoints and
NB 22 negotiation/refusals. Successful attempt:
`3d8a4a8a-86f9-4292-89a1-c72a10483e74`, completed `2026-09-17T19:38:19Z`.
Notebook source SHA-256:
`d059f822e4f73ded632530321172afe30f693597ff076a9c8d92bf2481aec00f`.

Initial attempt `2a1a484b-715a-420b-9447-d08a73eb2360` stopped in NB 18's historical
whole-package comparison when it encountered the changed Bitfinex module. Inspection
confirmed both changed modules are outside the retained query workload. The notebook
still verifies the complete historical digest and every other measured file, and
uses an isolated import check to confirm neither changed live module belongs to the
query import path. It lists these two exceptions explicitly and makes no current
live/replay performance claim. Historical measurements and hashes were not altered;
no unrelated workload rerun was needed. The second fresh-kernel run passed.

Maintained examples remain tracked; only generated runs/kernel files/checkpoints
remain ignored. P1, config, lock and ignore-policy bytes match the base. The wheel
SHA-256 is `c76db82ef3ee10181fbba577f90b3a580daae14aacb4ae066812f1aad1fd5089`;
the capture's installed implementation identity is
`fae68134d32c668203fe3c9139c5310a223e59239b8e7e6e922d1c6259895b98`.
The frozen P1 SHA-256 remains
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.

## Risks / reversal

This verifies one bounded public source from the observed location. It does not
admit Coinbase authentication, another instrument/stream, full matching-engine
history, execution, service deployment or complete M3. Local receipt cannot become
an absent source clock. The 15-second idle ceiling can end a quiet session under
jitter; failure remains visible. Repeated invocations share an external IP budget;
no cross-process rate coordinator is claimed. Bulk input and temporary evidence
remain local-only. Canonical book integration/shared replay are MR 25/27; existing
native release restrictions and R1 still apply before deployment.

Revert this MR before dependent changes; existing saved input needs no migration.
Retain original recordings and failed notebook attempts. **Next: MR 23 — Capture
durably before downstream use**, after MR 22 merges. Stop here.
