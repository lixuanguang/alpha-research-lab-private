# Crypto L3 collector implementation record

This record retains the original L3 implementation and eight-cell checkpoint
evidence. The subsequent [OKX extension](okx-market-data.md) integrates L2 live
and historical examples into the same maintained notebook and existing pipelines;
its record owns the newer combined checkpoint evidence.

Owner: repository founder. Date: 2026-09-16 (Singapore).
Base: updated `main` at `a6cb23f1267a8f4c477a666a9dacf426215796b6`.
Branch: `codex/crypto-l3-collectors`.
Status: bounded foreground collectors and visible-order replay implemented;
Bitfinex externally verified; Coinbase authenticated source acceptance blocked
by unfilled Exchange credentials. No M3 or complete MR 22–27 closure is claimed.

## Problem and change

Bring irrecoverable native order-level observations forward without rewriting the
Binance historical baseline. Configured Bitfinex R0 and Coinbase Exchange Level 3
now compose installed transports, exact decoding, fsynced append-only recording,
existing content-addressed raw storage and offline replay. Acknowledgements,
compact schemas, receipt nanoseconds and recovery epochs remain in saved input.
A capture with a known gap exits nonzero even if a later epoch resynchronizes.

The [collector guide](../data/l3-collectors.md) owns supported behavior, commands,
source references, limits and credential setup. The notebook checkpoint is
[market-data-capture.ipynb](../../examples/market-data-capture.ipynb). The source
amendment is scoped to this new workflow. Binance configuration, transport,
maintained historical notebooks and `docs/research/p1-baseline.md` are unchanged.

## Ownership and review boundaries

| Existing owner | Delivered slice | Acceptance retained outside this slice |
| --- | --- | --- |
| MR 22 | Explicit native BTC/USD config; public listing probes; Bitfinex public R0; Exchange HMAC Level 3 and schema negotiation | Coinbase authenticated live/eligibility verification; additional products/regions need actual source evidence |
| MR 23 | Receipt envelopes, bounded queue, durable-before-apply journal, raw-store publication, descriptor identity and interrupted-prefix inspection | Canonical dataset publication remains with MRs 10–15; no remote storage service |
| MR 24 | Finite retries, fresh epochs and snapshots, preserved gaps, overload and storage stop reasons | No historical backfill, economic exactly-once claim or automatic gap repair |
| MR 25 | Exact R0 visible-order reconstruction; Coinbase full L3 snapshot bridge and lifecycle; invalid-until-resnapshot consumer | Canonical revision, lateness/watermark and quality-publication prerequisites remain; no general admission of all venue products |
| MR 26 | Foreground bounded receive/persistence progress in saved input; heartbeat/idle, queue pressure and failure handling | External supervisor/process-loss alerts and alert-delivery acceptance remain planned; no unattended service |
| MR 27 | Installed consumer and offline replay of exact received bytes, clocks and session transitions; rolling message-boundary state parity | General MR 20 scheduler, normalized dataset consumers, broader recovery/restart acceptance and Coinbase real-source parity remain open |

Review changes in dependency order: (1) capture selection and shared raw request
binding; (2) exact visible-order primitives and Bitfinex; (3) Coinbase schema,
authentication and lifecycle; (4) journal and replay; (5) real transport and CLI;
(6) explanatory notebook, commands and evidence. Stable library objects own
validation and I/O capabilities; `pipelines/live.py` composes their lifetimes.
The existing historical acquisition manifest remains historical. It is not
stretched into a live checkpoint with invented source clocks.

The source/storage prerequisite is MRs 01/03–04, already implemented. This narrow
amendment retains MRs 10–15, MR 20 and R1 for their consuming acceptance. General
replay scheduling, supervision, simulation, execution and deployment are excluded.

### Actual review sizes

Code-bearing physical lines against each commit's parent, excluding comments,
blank lines, docstrings and tests (additions plus deletions, not net growth):

| Commit | Cohesive operation | Added | Deleted | Total |
| --- | --- | ---: | ---: | ---: |
| `b4512d8` | Bind bounded native L3 capture requests to existing raw storage | 107 | 8 | 115 |
| `ce2342e` | Decode exact sequenced Bitfinex R0 visible orders | 180 | 0 | 180 |
| `7d85234` | Load local Coinbase Exchange secrets and sign read subscriptions | 54 | 0 | 54 |
| `018919e` | Synchronize compact Coinbase Level 3 snapshots and lifecycle | 143 | 0 | 143 |
| `6bece3d` | Persist bounded capture journals and replay scoped order state | 201 | 0 | 201 |
| `6b1acc1` | Add bounded read-only native WebSocket and snapshot transport | 78 | 0 | 78 |
| `03eb8a6` | Compose bounded collection recovery and installed capture commands | 293 | 0 | 293 |

Declarative changes are separate: two JSON capture configs, one empty credential
example, one runtime dependency and installed command in `pyproject.toml`, its
29-line lock addition, and matching license/native/digest admission. Generated
captures are excluded. Documentation and the notebook form the final review slice.

The 180-line exact parsing/Bitfinex slice keeps its first concrete order-book
consumer with the primitive invariants it exercises. The 201-line journal/replay
slice keeps the receipt envelope, publication and invalid-state consumer together.
The workflow composition exceeds the 150-line preference: it owns connection,
receiver/snapshot task cancellation, durable-before-apply, finite retry and CLI
failure propagation as one tested resource lifetime. Splitting those transitions
into forwarding layers would obscure which task owns shutdown and pending data.
The independent transport and credential contracts are already separate commits.

## Validation

Final focused behavioral command:

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/test_raw_objects.py tests/unit/data/test_raw_store.py
```

Result: **88 passed in 8.40 s; no skips or deselections**. The selected integration
cases include existing raw-store process-interruption tests. Additional collector
cases cover malformed JSON, source clocks, invalid subscription/schema, exact
large IDs/decimal tokens, missing auth, concurrent Coinbase snapshot bridging,
non-resting changes/completions, match overfill/price errors, duplicate/gap
recovery, retry exhaustion, queue overload, byte ceilings, disk failure, truncated
journals, native identity mismatch and raw-object tampering.

Changed-path Ruff, configured strict mypy, engineering-standards, Bandit and
dependency admission are required for the delivered candidate. The only added
runtime dependency is pinned `websockets==16.0`; uv lock and BSD-3-Clause/native
admission were updated together. QuantLib's existing development-only release
restriction remains unchanged. Full hosted CI remains a merge gate; this work
does not claim that an unrun complete local/hosted lane passed.

### Actual source observations

Both public probes returned `available=true` for the configured native symbols.
Bitfinex discovery SHA-256:
`ad5c2c16d99b75060bdfcb43aa70faa233931623d8b9539ab1bac659eb2130dc`.
Coinbase discovery SHA-256:
`d2bfd4363396ca895bed3a49a2e3f265c7c043efbb50b04ccf87fd5df6197137`.
Discovery snapshots can change; their digests identify these observations only.

First source attempt: `data/bitfinex/e485d30a-1fc0-4b52-b2d5-2ac9a8b0b282`,
raw identity `d009b08f567e0b9ee5eeb8e1f866d99899973c20e492777f64ccdd759121b6b8`.
It retained 695 messages, a rejected pre-ack heartbeat and actual reconnect to a
second epoch, then recovered 50 visible orders. It exited 2, correctly retaining
its invalid first interval. The received prefix showed that a heartbeat can race
the subscription acknowledgement. The decoder was corrected to retain liveness
while requiring a matching acknowledgement before snapshot admission. The first
attempt and its original implementation identity/summary remain local and intact.
Its original parity result belongs to that earlier implementation.

Clean CLI attempt after this correction:
`data/bitfinex/1d32f063-6497-46bf-a392-92cccf5fb8e5`,
raw identity `fe910bc4392b83b1c1c6ead3e40a02ef6ce7c80806da96cb25f7187c07d0822d`.
It recorded 799 messages, 1 snapshot, 794 updates, 1 heartbeat and 50 visible
orders with zero detected gaps. The 109,090-byte input replayed with identical
message-boundary state. Receipt interval was 2026-09-15 17:11:00.914820–
17:11:21.112471 UTC; there is no fabricated Bitfinex source timestamp.

### Notebook and installed consumer

The maintained notebook uses the installed package with fresh-kernel execution:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
```

The first fresh-kernel run completed all 8 code cells, including a real 724-message
Bitfinex recording, exact offline parity and synthetic Coinbase lifecycle checks.
It retained attempt `504f7e52-cd27-4909-86ee-71dae63e1913` under ignored
`examples/runs/market-data-capture/`. The runner normalized missing cell IDs;
the maintained notebook now has IDs. The final-candidate run is recorded below.

Wheel build command:

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir dist
```

Runtime dependencies are exported from the frozen lock with `uv export --frozen
--no-dev --no-emit-project --format requirements-txt`, installed with
`uv pip install --require-hashes`, and the candidate wheel installed with
`--no-deps` into `/private/tmp/crypto-l3-verification/consumer`. Consumer commands
run from `/private/tmp/crypto-l3-verification`, outside the checkout.

### Final candidate evidence

Runtime source SHA-256:
`46c8b0a613049c9bc8f79302500742c2675d2c7944398f729c9ee4630bed7e42`.
Built wheel SHA-256:
`e6893aa102663f2d36258181317cc9dcb932fb64ace9480f230b8414dad97bac`.
The wheel is a development artifact under the existing QuantLib restriction.

Final fresh-kernel attempt `f1fc55a1-528a-4549-a13b-512dc253832e` completed all
**8 code cells**. Notebook source SHA-256:
`fb29a6303d83a7e7072a2eba41b844902d087d7f36ae9e76ce992467de5eab1b`.
It recorded 363 messages, 358 updates, one snapshot, one heartbeat and 50 visible
orders, with zero gaps. Input directory:
`data/bitfinex/3e061476-ccca-41a1-b09f-8b3010a75013`;
50,714-byte input SHA-256:
`a57a31aef5ca719a3cbaebf951b4ece0644b1f8ae067b3120456430bd6d57041`.
The final notebook records the precise UTC interval and replay trace.

From `/private/tmp/crypto-l3-verification`, the isolated consumer command was:

```sh
consumer/bin/python installed_consumer.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private'
```

The locally retained script and `installed-consumer-result.json` record installed
CLI help, a four-second real R0 capture, replay trace equality, and missing
Coinbase authentication exiting 2. Import location was the isolated consumer's
`lib/python3.14/site-packages/alpha_research`, not the checkout.
Its real capture retained 24 messages, 20 updates and 50 orders without gaps:
`data/bitfinex/50a3733d-2856-44e3-92a0-68b5de91f3a7`, input identity
`0b9567507e57a40604b2565c702888d2da34fc21a6dd6b8a1d91b66179a15865`.

Static results: **strict mypy passed 20 files**, changed-path Ruff lint and
format checks passed, repository engineering-standards passed, focused Bandit
passed, architecture links passed and dependency admission passed 73 locked
packages. `uv run --frozen --no-editable alpha-governance-dependencies audit`
reported no unresolved vulnerabilities or coverage gaps. An initial direct
executable audit could not find `pip-audit` on PATH; the supported uv invocation
resolved that harness issue. The replay test was then moved to its own review file; its 10
focused Bitfinex/replay tests and the final 20-file mypy check passed.

Final `uv run --frozen --no-editable alpha-governance-ci scan-secrets --all`
passed **187 governed paths**. `uv run --frozen --no-editable uv lock --check`
resolved the consistent 75-package lock; dependency admission separately counts
73 external packages. An earlier direct secret-scanner invocation lacked its
`detect-private-key` executable on PATH; the supported uv invocation above passed.
No scanner rule or scope was weakened.

`git diff --exit-code main` verified unchanged P1, Binance config/transport and
both historical notebooks. Git ignore checks cover filled secrets, both venue
data roots, generated notebook runs and kernel directories. The notebook uses
only small metadata/count outputs and synthetic lifecycle values; no credentials
or raw bulk feed output are tracked. All capture identities reference retained
local-only bytes, not a published dataset.

### Coinbase verification blocker

`secrets/coinbase.secrets` was created with mode 0600 and blank
`COINBASE_API_KEY`, `COINBASE_API_SECRET`, `COINBASE_API_PASSPHRASE` fields.
The tracked empty example is `configs/live/coinbase.secrets.example`.
The user's CDP JSON was not accessed and is not used. The local Exchange fields
are unfilled, so authenticated subscription, eligible account access and real
Coinbase capture/reconstruction parity are unverified. Public BTC-USD discovery
and all independent Coinbase decoder/signing/concurrent-capture fixtures pass.
No Coinbase live recording or historical backfill is claimed.

## Risks and reversal

Source schema, regional access and native feed limits can change. Coinbase may
need larger explicitly bounded snapshot/order/bridge budgets for a permitted
live workload; exceeding them fails closed. Missing authenticated-only messages
cannot universally be detected through product sequence. Bitfinex R0 depth and
server sequence do not prove queue rank or matching-engine completeness.

Stop the foreground process to end collection. Retain ignored recordings and
manifests for replay; remove/revert the new command/config/library changes to
reverse the feature. Existing Binance inputs, source code, notebooks and P1
specification need no migration. No orders, service activation, push or merge
are part of this delivery.
