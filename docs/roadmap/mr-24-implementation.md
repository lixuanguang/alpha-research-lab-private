# MR 24 — Recover sessions without hiding gaps

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-18 (Asia/Singapore); not merged. Branch: `codex/mr-24-session-recovery`.
Base: fetched, unchanged `origin/main` at `b30f89e`. Direct prerequisite MR 23 merged
through PR #49 at `4308a5a`; `git merge-base --is-ancestor 4308a5a HEAD` passed before
implementation. The [roadmap](README.md#m3-reliable-live-capture) owns acceptance.

## Problem / change

After an invalid frame, the collector previously stopped consuming its queue and
cancelled the snapshot coroutine. Accepted queued frames disappeared from a
completed recording, and cancelling `to_thread` did not stop its REST worker before
a reconnect. The pipeline now stops the affected receiver, drains accepted input
and completes its single outstanding snapshot before starting another epoch.
Persistence still precedes consumer use. Invalid state blocks later queued frames
and delayed snapshots from mutating the book. A failed medium or storage ceiling
retains the existing explicit incomplete/unknown-tail failure rather than claiming
that in-memory input was saved.

One epoch coalesces all snapshot triggers into one request. Existing bounded
connection attempts, resubscriptions and exponential backoff are retained; a
summary now exposes retry exhaustion. HTTP protocol failures, including a truncated
response, become a queued gap. Coinbase reserves one of the existing message slots
for its REST response before receiving stream frames, preserving the total message
ceiling without discarding accepted frames. An unused reservation stays unused.

`CaptureReplay` keeps exact adjacent Bitfinex/Coinbase sequenced duplicates in raw
lineage and suppresses the second mutation. A one-frame cache is scoped to the
epoch; ambiguous, conflicting or older repeats retain native sequence refusal.
OKX retains its source-specific sequence/reset rules. Prior-epoch or closed-epoch
snapshots are counted and ignored by the current state. They keep their original
response receipt timestamp; recovery cannot backdate knowledge or repair the
preceding unknown interval. Current native snapshots are recovery inputs, not
historical backfill. No new source or canonical reconstruction/publication is added.

## Affected scope

Against `b30f89e`: **77 added + 13 deleted = 90 production code-bearing physical
lines**. `data/live/replay.py`: 48 + 1; `pipelines/live.py`: 29 + 12. No overage.
Counts exclude blanks, comments, docstrings, tests/fixtures and notebook acceptance
exercises. There are no executable tooling, configuration, dependency, lockfile,
public-export or ignore-policy changes. Existing capture envelope and manifest
serialization is unchanged; derived summaries add frames, duplicates, stale
snapshots and retry-exhaustion observations. Historical traces containing an exact
repeat may now classify it as a duplicate rather than invalid; original raw bytes
and historical evidence remain unchanged.

The [collector guide](../data/l3-collectors.md#mr-24-session-recovery) owns current
recovery behavior and limits. NB 24 is section 15 of the maintained
[research-foundations notebook](../../examples/research-foundations.ipynb), reusing
one retained installed consumer fixture for the notebook and integration test.
The researcher and operations guides describe its outputs and next question.

## Validation result

CPython 3.14.7, macOS arm64. **91 focused tests passed in 6.82 seconds**, including
the installed recovery integration case; zero skips or deselections. The source
boundary remains synthetic for failure injection. Existing Bitfinex source evidence
from MR 22 is reused; no additional venue connection was needed for this lifecycle
change. The cases cover disconnect/resubscription, exact/conflicting duplicates,
queue overflow, accepted-frame drainage, pending-snapshot disconnect, a sequence
gap during snapshot acquisition, HTTP 429 simulation, HTTP truncation, stale
responses, retry exhaustion, storage failure and native replay parity.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/venues/okx/test_okx_capture.py
uv run --frozen --no-sync ruff check src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_recovery.py tests/fixtures/mr24/recovery_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_recovery.py tests/fixtures/mr24/recovery_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_recovery.py tests/fixtures/mr24/recovery_consumer.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py
```

Lint, format, strict typing of five Python files, repository engineering standards
and focused Bandit passed. The initial run passed 85 tests and failed two assertions
that expected discarded queued input; these were replaced with exact retained-byte
assertions. The final test fixture delivers that burst without scheduling races.
Initial missing private-fixture docstrings and a test-only mock tuple inference
were corrected. No enforcement or runtime
invariant was weakened. The final fixture-only refinement reuses wheel/notebook
runtime evidence. The final deterministic-burst recheck passed **2 tests / 18
intentionally deselected** with the command below; lint/format, strict typing,
engineering standards and documentation links were checked again afterward.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/live/test_capture.py -k rejected_source_session
```

### Installed consumer outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr24-validation/dist
uv run --frozen --no-sync python /private/tmp/mr24-validation/install.py
cd /private/tmp/mr24-validation/consumer
../installed/venv/bin/python -I recovery_consumer.py . run
../installed/venv/bin/python -I ../verify_identity.py
```

The local installer reuses `_InstalledWheelCheck.validate`: hash-locked, binary-only
runtime dependencies, governance-free imports, exact-value smoke and dependency
compatibility passed. The consumer copies the maintained MR 24 fixture, Coinbase
config, schema and snapshot outside the checkout and runs under `-I`.
All **76 runtime files** match source, wheel and installation byte for byte.
Four installed `alpha-collect replay` invocations preserve gaps and invalid state;
one also exposes the retained duplicate and two stale responses.

A repeated `0.1` match mutates once, retaining exactly `0.200000000000000001` on
the maker. Both raw copies retain receipt clocks 5 and 6 in that constructed case.
A conflicting repeat is rejected before another subtraction. Each of late response,
missing bridge sequence and simulated HTTP 429 uses three connections, three REST
requests and backoff requests of 1 then 2 seconds. Injected waits avoid wall-clock
sleep but record their requested durations. Repeated acknowledgements never create
extra REST requests; the next epoch cannot open while its predecessor's worker
remains active. Late snapshots remain persisted after their gap with later receipt
nanoseconds, and all three cases end invalid with exhausted retries.

Wheel SHA-256: `ebd61884439ce13f0be058e13f0f26d54ce9e188b0a30875967e29dcad5f0b50`.
Installed implementation: `d3b5fc87d315df66450a32308c1fe2cfc6781f1458a0755413e919d0288125c8`.
Local drivers, installed wheel, recordings and `consumer/installed-evidence.json`
remain under `/private/tmp/mr24-validation`; these are local acceptance artifacts,
not a release or durable archive. The reusable consumer source is tracked under
`tests/fixtures/mr24/`. Sandbox access was required for the uv cache and kernel.

### Fresh-kernel notebook

```sh
uv pip install --python /private/tmp/mr24-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' ALPHA_BITFINEX_CAPTURE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr24-validation/installed/venv/bin/python
```

All **67 cells / 33 sequential code cells passed**, with candidate imports and all
runtime bytes verified. Attempt: `036bb3a6-bd16-40a9-bafa-a3d2c96019d2`, completed
`2026-09-18T11:14:45Z`. Notebook source SHA-256:
`43c7d437a53fca99d70ce16fdcfd4b3676a1d7d2c51331ca43318880074bf8ef`.
Tables expose duplicate clocks, exact remaining size, conflicting/stale refusals,
endpoint counts, backoff, invalid state, replay parity and later snapshot receipt.
The kernel shut down; the successful attempt is preserved under ignored
`examples/runs/`. All eight maintained example sources remain tracked. The earlier
query measurements retain their historical identity; no new performance claim is
made for session recovery.

### Final source and evidence hygiene

The architecture check passed for **57 documents**; the focused example-link check
passed **99 links**. Notebook schema, successful-snapshot equality, sequential
execution counts, all eight tracked example sources, generated-artifact ignore
rules and unchanged P1/configuration/lock/ignore bytes passed. The initial cleanup
assertion found four pre-existing kernel directories dated September 13–16;
they were preserved, and the check was scoped to this execution's start time.
No kernel directory from this run remains. The final CI secret scan passed for
**280 governed paths**, and staged whitespace checks passed.

```sh
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
git diff --cached --check
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr24-validation/final_check.py
python3 /private/tmp/mr24-validation/count_lines.py
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/probe.ipynb examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

## Risks / reversal

This is bounded foreground development capture. Retry and endpoint budgets apply
per invocation, not across clients sharing an IP. Existing connection, frame,
queue, message, order and storage ceilings remain; a snapshot response can extend
wall time through the existing HTTP operation timeout and filesystem work.
Cancelling or killing the whole collector still requires interrupted-prefix
inspection; it does not promise to kill an already running OS thread immediately.
The current streams have no historical backfill adapter, so gaps remain unknown.
Coinbase external access acceptance, MR 25 reconstruction/quality/publication,
MR 26 supervision, MR 27 shared canonical parity and R1 deployment remain open.
No M3 completion, strategy result or global exactly-once claim is made. Full local
`make check` and hosted CI were not run; the complete hosted lane remains required
before merge. Existing release restrictions remain in force.

Revert this MR before dependent changes. Existing raw capture envelopes and
manifests require no migration; preserve original and interrupted recordings.
P1/configuration/lock/ignore bytes match `b30f89e`. Frozen P1 SHA-256:
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
**Next: MR 25 — Apply continuous quality and recovery states**, after MR 24 merges.
Stop here.
