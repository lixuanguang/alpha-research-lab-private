# MR 20 — Replay with shared event stepping

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-17. Branch: `codex/mr-20-event-stepping`.
[PR #46](https://github.com/lixuanguang/alpha-research-lab-private/pull/46)
records hosted checks and the merge status. Base: fetched `main` at
`f37c07d`; MR 19, the sole prerequisite, merged at `0898d0a` through PR #44 and
is an ancestor of the base. Tested runtime:
`67ff51d9106d3e1425ebf43f5047953273c20014`. The NB 20 source digest below
identifies the corrected notebook exercise. Scope follows the
[MR 20 roadmap row](README.md#m2-research-data-access-and-replay).

## Problem / change

The reference history query retains revisions in partition/head order. `Replay`
expands that history at effective availability and reuses the admitted economic
ordering rule. Its shared `step` operation advances to the next source, consumer
wakeup or inclusive terminal, delivering every equal-time source before expiry,
fill, decision and mark callbacks. Read-ahead does not advance the clock.
Unknown original archive availability is never inferred. Membership and quality
remain explicit evidence for the consumer's cutoff-aware selection.

A frozen, codec-serializable `ReplayCursor` binds the query, consumer configuration
and ordering/phase version to a completed clock and logical source position.
Resume works across query batch sizes and rejects mismatched or incomplete source
positions. Callback errors propagate and prevent further use or checkpointing of
the partial instance; restore the last completed cursor with matching consumer
state. Callback payloads and exposed cursors/evidence are isolated from mutation.

## Affected scope

Runtime changes are confined to `data/replay.py`: ordered reference construction,
clock, phase delivery and completed-step cursor. Its first consumers are focused
regressions, the [installed fixture](../../tests/integration/consumers/replay/replay_consumer.py)
and [NB 20 section 10](../../examples/research-foundations.ipynb). The existing
query, selector, configuration, canonical/revision serialization, publication and
live/book implementations are reused unchanged. The
[API guide](../../src/alpha_research/data/README.md#chronological-event-stepping-mr-20)
documents arguments, memory, progress, failure and recovery contracts.

Against `f37c07d`, production code-bearing changes are **147 additions + 0 deletions
= 147 lines**, including imports, annotations, validators and codec use. Blank
lines, docstrings/comments, tests/fixtures and notebook exercises are excluded
under the roadmap rule. No declarative configuration, dependency, lock, public
export or executable-tooling changes. The cursor and phase declarations ship
with the operation that consumes them; no later runner or schema is scaffolded.

## Validation result

CPython 3.14.7, macOS arm64. The final focused command ran **89 tests**, with
**no skips or deselections**:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_event_stepping.py tests/unit/data/test_query.py tests/unit/data/test_asof.py tests/unit/data/test_revisions.py tests/unit/data/test_eligibility_selection.py tests/unit/data/live/test_replay.py --tb=short
```

The 13 new replay cases cover original/gap/correction availability, explicit
intermediate wakeups, fixed phase order, equal-time sources split across batches,
terminal once, future-only duplicate/row/hash perturbations, unknown archive
availability, every source-step resume across batch sizes, strict cursor JSON,
changed inputs/configuration, incomplete source positions, invalid clocks,
callback failure, reentrancy, unsafe mutation and cancellation. Existing query,
selector, revision and eligibility regressions passed with them. Unchanged raw
publication/process-interruption and live integrations retain their prior evidence;
no network, source acquisition or economic result was needed for this scope.

These relevant static and documentation checks passed:

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/replay.py tests/unit/data/test_event_stepping.py tests/fixtures/mr20/replay_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/replay.py tests/unit/data/test_event_stepping.py tests/fixtures/mr20/replay_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src tests tools/governance/src tools/typing/stubs
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/replay.py
uv run --frozen --no-sync alpha-governance-architecture
python3 /private/tmp/mr20-validation/verify.py
uv run --frozen --no-sync --with 'nbformat==5.10.4' python -c 'import nbformat; nbformat.validate(nbformat.read("examples/research-foundations.ipynb", as_version=4)); print("Notebook schema valid")'
git diff --check
```

Final mypy covered all 163 configured source files; Ruff covered the new source, test, installed
consumer and maintained notebook. The engineering checker retained its complete
configured scope; architecture checked 53 documents. The temporary verifier
checks code-bearing line count, unchanged P1, additional component/example and
notebook Markdown links, sequential execution counts, cell errors and notebook
source identity. A separate byte check matched source, wheel and external install
for all 75 packaged files. These are local checks; hosted complete CI remains a
pre-merge gate, and no full local `make check` is claimed.

### Installed candidate outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr20-validation/dist
mkdir -p /private/tmp/mr20-validation/inputs /private/tmp/mr20-validation/installed
cp tests/fixtures/mr20/canonical.json tests/fixtures/mr20/replay_consumer.py configs/data-jobs/fixture-inspection.json configs/reference/binance-spot.json /private/tmp/mr20-validation/inputs
uv run --frozen --no-sync python /private/tmp/mr20-validation/install.py
cd /private/tmp/mr20-validation
./installed/venv/bin/python -I inputs/replay_consumer.py inputs
```

The temporary installer invokes existing `_InstalledWheelCheck.validate` with the
checkout, `installed/` and built wheel. Frozen, hash-locked, binary-only runtime
installation, dependency compatibility, governance-free imports and exact-codec
smoke all passed. The retained standalone consumer ran under `-I` outside the
checkout, with copied configuration and one 17,221-byte synthetic canonical fixture.
The fixture is reproduced through canonical admission; it is not external market
evidence. It needs neither the checkout nor test/governance imports at runtime.

The source trace was `(1, 100.00)`, `(3, disconnect)`, `(10, 101.00)`, followed
by terminal at second 12. An explicit second-2 wakeup is processed before the gap.
Batch sizes 1/8 and cursor resume produced the same 27 callback rows and final
cursor. A changed configuration was refused. Tracemalloc observed **126,593 peak
bytes** for the tiny replay exercise after reader construction; this excludes
reader admission, is not process RSS, and is not a large-input performance claim.
The inherited aggregate byte cap and explicit whole-reference memory contract
remain the admission bound.

| Retained identity | SHA-256 |
| --- | --- |
| Built wheel | `02507f37725b6d12337352c4aad7f0c41abbe1e08677c0812fa712e1729b1034` |
| `data/replay.py` | `38c939678cea1419bea3b8498b051d0231553e71b26d1e0b8d1f89930e906923` |
| Synthetic canonical fixture | `12e18d2364f5d5f7a6c0a2545b7715b510e835fb4fe64077b8c67570eea0ce5f` |
| `uv.lock` | `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4` |
| Preserved P1 specification | `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d` |

The development wheel/installation and temporary verification scripts are local
under `/private/tmp/mr20-validation`, not a durable release archive. Source,
synthetic fixture and consumer are retained in Git. Existing release restrictions
are unchanged.

### Fresh-kernel NB 20

From the checkout, using the existing saved book inputs and separate pinned
notebook tooling:

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

All **45 cells / 23 code cells** passed in a fresh kernel after verifying all
**75 installed runtime files** against the committed candidate. Successful attempt:
`6d5a0249-bc46-4642-b5d8-f409f68387f5`; notebook source SHA-256:
`72baafa69723a41a8e167c90a8c9b1f72be64a346a3cff35392536680ba6ce1c`.
Maintained outputs equal the ignored attempt snapshot; no cell errors remain.
The runner shut down the kernel and removed temporary kernel files.

Section 10 reuses the captured synthetic price, BTC-scoped gap and late correction.
It shows first availability at **0.004103 s**, gap at **2 s**, correction at **10 s**,
an intermediate **1.5 s** wakeup, all phase callbacks, batch-size parity, serialized
cursor and restored consumer-prefix/suffix parity. It prints changed-configuration,
changed-query-terminal, repeated-clock and naive-clock refusals. Sections 1–9 also
ran: the real saved-book paths were read only, temporary synthetic datasets were
cleaned up, and MR 18's historical runtime/lock/driver fingerprints were verified.
Those measurements remain historical query evidence; the added replay module is
explicitly outside their measured scope.

The first notebook attempt, `3d72e34c-ed98-47c5-8da5-cb63c06811f4`, failed only the
new expected-time assertion: the earlier query's one-second cutoff had been
mistaken for arrival time. The saved capture `00:00:00.0041023Z` conservatively
rounds to `00:00:00.004103Z`, which the replay correctly returned. The notebook
expectation and explanation were fixed; the next all-cell fresh-kernel run passed.
Runtime/wheel bytes were unchanged, so their tests and installation proof remain
applicable. Initial test assertions/type/lint findings were likewise corrected
before acceptance; failed attempts are not counted as passes.

Maintained `.ipynb`, `.py` and `.md` examples remain tracked. The unchanged ignore
policy excludes generated `examples/runs/`, `.kernel-*` and notebook checkpoints;
`git ls-files -- examples/` and `git check-ignore` verified the boundary. Reviewed
outputs contain small synthetic traces and saved-input identities, not raw book
exports, credentials or bulk data. P1 is byte-identical to the MR base.

### Hosted integration correction

The first hosted full-scope mypy run at `285bed6` failed before tests because the
new `tests/unit/data/test_replay.py` collided with the existing live test module
of that name. [The failed job](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35238057626/job/105258990635)
retains the diagnostic. The new test was renamed to `test_event_stepping.py`;
no exclusion, typing waiver or runtime behavior changed. The final focused test
and static commands above use that unique filename. Full configured mypy scope passed for 163 files; the 89-test focused run
passed with both replay test paths included, without skips or deselections.
Installed runtime, fixture and notebook source bytes are unchanged, so their
identified acceptance remains applicable.

## Risks / reversal

This is a bounded in-memory reference over trade/control canonical history.
The canonical-byte cap bounds retained input, not process RSS or one-batch memory;
selected revisions and their sorted index remain resident. Existing MR 18 query
measurements are historical, verified against the unchanged measured runtime
files, and make no claim about new replay performance. No replay benchmark or
large-scale latency claim is made.

Consumers own observations, outstanding schedules, pending intents, applied fills
and ledger state; the source cursor cannot certify unsupplied economic state.
The scheduler fixes phase order, while E1/MR 44 will prove the earlier-fill/later-gap,
exact-expiry and resumed-economics contracts using their actual libraries.
L2/L3 shared publication/adapters, atomic book application and accepted-snapshot /
recovery-epoch checkpoints remain with their later consumers. The current canonical
trade boundary does not accept those book records. No research outcome, deployment
or release acceptance is claimed; existing release restrictions remain.

Revert this MR before dependent consumers merge; existing datasets and cursor-free
query APIs require no migration. Preserve the frozen P1 specification. Hosted full
CI remains required before merge. **Next: MR 21**, after this MR merges; it is not
implemented here.
