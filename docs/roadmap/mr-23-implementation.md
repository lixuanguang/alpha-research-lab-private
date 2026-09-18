# MR 23 — Capture durably before downstream use

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-18 (Asia/Singapore). Branch: `codex/mr-23-durable-capture`. Base: fetched
`origin/main` at `ff2b28e`, which merged MR 22 through PR #48. The direct prerequisite
was verified with `git merge-base --is-ancestor de58c99 ff2b28e` (exit 0). Work uses
`/private/tmp/alpha-mr23`; the original checkout's unrelated commit and modified
notebook were preserved. The [roadmap](README.md#m3-reliable-live-capture) owns scope.

## Problem / change

The existing bounded collector fsynced each append, but interrupted inspection
could admit a complete line whose fsync had failed. `CaptureJournal` now publishes
a durable cursor after each synced append. It binds the recording request, byte
offset, record count and incremental SHA-256. Interrupted readers verify the
bounded prefix before yielding records, exclude uncommitted suffixes and report
unknown loss. Corruption or truncation inside the committed prefix fails closed.

The frozen cursor and its first writer/reader consumer live together in
`data/live/journal.py`, using the existing cached `DomainCodec`. Direct/unsafe
record construction is validated before persistence. A writer that encounters an
I/O failure refuses further appends and publication. Initial provisioning also
syncs newly created output-directory ancestors. A new invocation creates its own
exclusive UUID directory, preserving prior same-day input.

`pipelines/live.collect` continues to persist before passing each complete message
to the existing native replay/schema/unit consumer. Replay now executes outside
the receipt event loop; the existing bounded queue stops an overflowing source
with explicit unknown loss. Invalid frames retain their original bytes and replay
as invalid. `CaptureReplay.read` reports interruption even before the first session
or after an unpublished end record. Empty-prefix inspection has no observed receipt;
its diagnostic retains the existing epoch-zero/nanosecond-one sentinel, not an
observed source clock.

One existing finite journal is one bounded recording segment. No new continuous
rotation service, Kafka dependency, reconnect policy, consumer-state checkpoint,
canonical dataset adapter or shared book replay is introduced. The
[source/storage guide](../data/l3-collectors.md#input-persistence-and-failure-meaning)
owns the operational contract.

## Affected scope

Against `ff2b28e`: **92 added + 7 deleted = 99 production code-bearing physical
lines**. `journal.py` contributes 87 + 6, native `replay.py` 4 + 0, and
`pipelines/live.py` 1 + 1. No overage. Counts exclude blank lines, comments,
docstrings, tests and notebook acceptance exercises. No maintained executable tooling,
configuration, dependency, lockfile, public export or ignore-policy changes.

The cursor file is additive; existing completed capture serialization/manifests
remain readable. Legacy interrupted captures without a cursor retain bounded
newline-prefix inspection and an explicit unknown-loss marker, without a cursor
acknowledgement guarantee. Updated cursors checkpoint input persistence, not
consumer state or venue acknowledgement. A crash during cursor publication may
leave the previous or new synced prefix; neither can include an unsynced journal
write. Failed writes are never reported as successfully delivered to the consumer.

NB 23 is section 13 of the maintained `research-foundations.ipynb`. It displays
message grouping, exact bytes, receipt nanoseconds, committed counts/offsets and
hashes. It exercises failed fsync with a complete uncommitted line, a torn suffix,
committed-prefix truncation, failed-writer reuse/publication, same-directory refusal,
separate restart identity and invalid native zero-size orders. Researcher and
operations guides are updated with the checkpoint and its limits.

## Validation result

CPython 3.14.7, macOS arm64. **87 focused tests passed in 6.19 seconds, with zero
skips or deselections.** These cover shared capture and Bitfinex, Coinbase and OKX
callers. New decisive cases inject journal/cursor/directory fsync and rename
failures, kill a child with SIGKILL after a committed session and partial tail,
corrupt/truncate committed input, reject malformed records/cursors and excessive
metadata, refuse failed writers, retain invalid units/schema, preserve same-day
segments and block a consumer until a one-slot queue visibly overflows. The slow
consumer verifies its exact record is already in the durable prefix before use;
writer failure delivers zero source messages downstream.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/venues/okx/test_okx_capture.py
uv run --frozen --no-sync ruff check src/alpha_research/data/live/journal.py src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_journal.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/live/journal.py src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_journal.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/live/journal.py src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_capture.py tests/unit/data/live/test_journal.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/live/journal.py src/alpha_research/data/live/replay.py src/alpha_research/pipelines/live.py
```

Lint/format, strict typing of five Python files, repository engineering standards
and focused Bandit passed. Initial lint findings and a test-only optional-list
typing error were corrected before these final checks. No runtime suppression or
global enforcement was weakened. Historical query measurements remain unchanged:
NB 18 preserves their historical digest and verifies all measured files, with four
explicitly named changed live modules checked in an isolated process to be outside
the query import path. This adds no current capture performance claim.

Final documentation and source-retention checks also passed: 56 governed documents,
74 example/notebook links, valid notebook schema, exact successful-snapshot equality,
31 sequential executed code cells, all eight maintained example sources tracked,
and only permitted generated paths ignored. The staged secret scan covered **275
paths**. P1/configuration/lock/ignore bytes and the 99-line production count were
checked against the actual base.

```sh
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr23-validation/final_check.py
.venv/bin/python /private/tmp/mr23-validation/count_lines.py
git diff --cached --check
git ls-files -- examples/
git check-ignore examples/runs/probe.ipynb examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

### Installed consumer outside the checkout

```sh
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr23-validation/dist
uv run --frozen --no-sync python /private/tmp/mr23-validation/install.py
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr23-validation/final-dist
uv pip install --python /private/tmp/mr23-validation/installed/venv/bin/python --no-deps --reinstall /private/tmp/mr23-validation/final-dist/alpha_research_lab-0.1.0-py3-none-any.whl
uv pip check --python /private/tmp/mr23-validation/installed/venv/bin/python
cd /private/tmp/mr23-validation/final-consumer
../installed/venv/bin/python -I ../verify_final.py
```

The local installer uses existing `_InstalledWheelCheck.validate`: hash-locked,
binary-only runtime dependencies, governance-free imports, exact-value smoke and
dependency compatibility passed. The initial wheel was refreshed after the final
metadata/parent-directory checks; unchanged dependency evidence was reused.
The final isolated driver compared all **76 runtime files** across source, wheel
and installation, then exercised the public collector with a synthetic transport
and the installed `alpha-collect replay` command. Two same-day recordings have
distinct requests, each preserving three exact source messages and six total
records in 772 bytes. Frozen synthetic receipt clocks produce the same raw digest:
`d4c5f748e59bafbc17c256808443c63eb1d3c3d339fc629deca5a3164303f97c`.

A failed fsync leaves one complete uncommitted source frame; interrupted CLI replay
exposes zero source messages and visible unknown loss. Truncating committed bytes
makes the installed CLI exit **2**. Final wheel SHA-256:
`bcfb76a0c3e374e06252be2efeee4266a0c741f1522acf6415bdda2eed3713f7`.
Installed implementation identity:
`64f22d4d0ab7054a72a4bd599e5db2a0bebdffa3b60ce8a48905429ac156e6d8`.

The driver and `final-consumer/installed-evidence.json` are local acceptance
artifacts under `/private/tmp/mr23-validation`, not a release or durable archive.
Initial driver setup used a wrong relative config path, then a nonexistent working
directory; both were corrected before final execution. Neither failure reached
product acceptance. Cache/kernel access required sandbox permission. MR 22's actual
source-access evidence is reused; no new network capture is required to prove this
storage boundary.

### Fresh-kernel NB 23

The final candidate was installed before executing every cell:

```sh
uv pip install --python /private/tmp/mr23-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' ALPHA_BITFINEX_CAPTURE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr23-validation/installed/venv/bin/python
```

All **61 cells / 31 sequential code cells passed**, including complete installed
import/byte verification, saved OKX/Bitfinex reconstruction, prior query/replay/EDA
checkpoints and NB 23. Final attempt: `4d63af45-75da-4f85-a3f4-9b4465cdc777`, completed
`2026-09-18T09:19:36Z`. Notebook source SHA-256:
`d480b803e323a3e1c34d83bc7a72c317da975afaf65fdb2c05d86da60917292e`.
The earlier successful attempt `a4fff4e5-086c-41b2-b3bb-667d5c23d413` belongs to the
pre-final wheel; it remains a separate ignored snapshot. Both kernels shut down.
Generated runs/kernel/checkpoint artifacts remain ignored. Maintained example
`.ipynb`, `.py` and `.md` sources remain tracked.

## Risks / reversal

Evidence exercises the supported local filesystem using injected I/O failures and
actual process death; it is not a physical power-cut test or qualification of
network/object storage. Per-message cursor fsync adds I/O cost; no throughput or
latency qualification is claimed. Queue/frame/book/storage budgets remain explicit;
overload ends the affected capture with unknown loss rather than repairing it.
No exact dropped-message count or global exactly-once claim is made. Legacy
interrupted captures have the weaker explicitly documented prefix evidence.

MR 24 owns session recovery and gap reconciliation; MR 25/27 own canonical book
admission and shared replay. MR 26 supervision and R1 deployment acceptance remain
open. Existing release restrictions remain. Complete local `make check` and hosted
CI were not run for this local review branch; the complete hosted lane is required
before merge. No empirical strategy result or M3 completion is claimed.

Revert this MR before dependent changes; capture envelopes and existing completed
manifests require no migration. Preserve original and interrupted recordings. P1,
configuration, lockfile and ignore-policy bytes match `ff2b28e`. Frozen P1 SHA-256:
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
**Next: MR 24 — Recover sessions without hiding gaps**, after MR 23 merges. Stop here.
