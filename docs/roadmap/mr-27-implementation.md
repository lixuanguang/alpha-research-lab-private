# MR 27 — Captured book parity and shared replay

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Status: implemented and locally verified for separate
review on 2026-09-19; not merged or deployed. Branch:
`codex/mr-27-capture-replay-parity`. Base: fetched `origin/main` at
`c4469fa1d543c7727b94013d68fcf9d523fe63a2`. Direct prerequisites are merged in
that history: MR 20 / PR #46 (`f8ef338`), MR 25 / PR #52 (`8b3027b`), and
MR 26 / PR #53 (`c4469fa`). The [roadmap](README.md#m3-reliable-live-capture)
owns scope, dependencies and acceptance.

## Problem / change

Native capture previously compared only final summaries, and published book
histories could not use the shared chronological clock. MR 27 compares the
selected live canonical prefix with independent normalization of the exact saved
raw frames, receipts and session transitions. `BookObservation.capture` is the
same normalization operation for both paths. The bounded prefix is retained in
`book-prefix.json`; a first mismatch writes `first-divergence.json` with original
raw provenance, position and both observations before failing.

`BookReplay.read` verifies the entire published book snapshot and selects one
explicit request. Its whole-message batches retain source order, controls, depth
and quality. Its stepping, equal-time phases, callback failure handling and
completed cursor use the same implementation as MR 20 trade replay. Exact receipt
nanoseconds remain in each event; the shared UTC clock rounds up to microseconds,
so no input becomes visible early. Unknown archive availability remains unscheduled.
The installed consumer compares exact visible spreads and state, serializes the
accepted snapshot/current state/recovery epoch with its cursor, and resumes in a
separate process with a different batch size.

The owning API and usage descriptions are the
[data guide](../../src/market_data/README.md#published-book-queries-and-shared-stepping-mr-27)
and [collector guide](../data/l3-collectors.md#mr-27-published-capture-and-replay-parity).

## Affected scope and review size

Against `c4469fa`: **253 added + 83 deleted = 336 production code-bearing lines**.
This exceeds the MR preference, primarily because extracting the existing clock
and normalization operations counts their deleted and added lines. Three cohesive
review slices keep each working operation with its actual consumer:

| Slice | Operation and first consumer | Production lines |
| --- | --- | --- |
| Shared clock | Existing `Replay` consumes generic ordered stepping; its trade/control regression suite retains behavior | 65 added + 53 deleted = 118 |
| Published book adapter | `BookReplay` consumes admitted whole-message history and validates coordinates; unit and installed consumers query, step and restore it | 113 added + 1 deleted = 114 |
| Captured canonical prefix | Existing `collect` consumes `BookCapture`; the same normalizer serves saved admission, and publication compares retained live input | 75 added + 29 deleted = 104 |

Counts include imports, annotations, validation and pipeline wiring; exclude blank
lines, comments/docstrings, tests/fixtures and notebook acceptance exercises. No
configuration, dependency, lock, public export or executable-tooling changes.
The shared-clock review commit is `fca4399`; the published-book adapter is
`22ed994`. The complete behavior requires shared stepping, an admitted-book consumer and
capture-side evidence; declarations are not split away from those consumers.
Per-slice counts are checked against their actual review boundaries.

`docs/research/p1-baseline.md` is byte-for-byte unchanged, SHA-256
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Maintained examples remain tracked; only existing generated run/kernel/checkpoint
paths are ignored. No ignore rules were changed.

## Validation result

CPython 3.14.7, macOS arm64. **178 focused tests passed in 35.04 seconds**, with
zero skips or deselections, including the explicitly selected installed-consumer
and process-boundary cases:

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' --basetemp=/private/tmp/mr27-focused-final tests/unit/data/test_book_replay.py tests/unit/data/test_book_datasets.py tests/unit/data/test_book_inputs.py tests/unit/data/test_event_stepping.py tests/unit/data/test_query.py tests/unit/data/live tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/venues/okx
```

Tests cover exact nanosecond retention and conservative scheduling, atomic L2
messages, equal-time source phases across batch sizes, serialized cursor resume,
consumer callback failure and isolation, unknown archive availability, raw corruption,
incompatible snapshot/incomplete cursors, duplicate/recovery histories, and the
first divergent intermediate state even when later updates converge. Existing
trade/query, all native reconstruction and MR 26 health tests pass unchanged.

Focused Ruff lint/format, strict mypy on eight Python files, engineering standards
and Bandit passed. Actual command families:

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/book_datasets.py src/alpha_research/data/book_replay.py src/alpha_research/data/replay.py src/alpha_research/pipelines/live.py tests/unit/data/test_book_replay.py tests/unit/data/live/test_capture.py tests/fixtures/mr27 examples/research-foundations.ipynb examples/market-data-capture.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/book_datasets.py src/alpha_research/data/book_replay.py src/alpha_research/data/replay.py src/alpha_research/pipelines/live.py tests/unit/data/test_book_replay.py tests/unit/data/live/test_capture.py tests/fixtures/mr27 examples/research-foundations.ipynb examples/market-data-capture.ipynb src/alpha_research/data/README.md
uv run --frozen --no-sync mypy --strict src/alpha_research/data/book_datasets.py src/alpha_research/data/book_replay.py src/alpha_research/data/replay.py src/alpha_research/pipelines/live.py tests/unit/data/test_book_replay.py tests/unit/data/live/test_capture.py tests/fixtures/mr27
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/book_datasets.py src/alpha_research/data/book_replay.py src/alpha_research/data/replay.py src/alpha_research/pipelines/live.py
```

### Installed candidate and named-source evidence

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr27-validation/dist
uv run --frozen --no-sync python /private/tmp/mr27-validation/install.py
cd /private/tmp/mr27-validation
installed/venv/bin/python -I verify_identity.py
```

The installer calls existing `_InstalledWheelCheck.validate`: hash-locked binary
runtime dependencies, governance-free imports, exact-value smoke and installed
compatibility all passed. All **80 runtime files** match source, wheel and installed
bytes. Wheel SHA-256:
`e1bbd528a606fb5a138e0e327b7f4d3b94d93fb129527fce00b052e45c5f82aa`.
Installed implementation:
`26df28cd5d421486c0f3fbf9a299ea326de5c2730d3c6ae8773059fefa5583eb`.
These identities name the tested candidate independently of the base commit.

The configured 20-second captures ran from the installed candidate in the capture
notebook, after native discovery. Both reported synchronized native state, no gaps,
full native-summary parity and selected-prefix canonical parity:

| Input | Local retained directory under repository data | Messages | Raw SHA-256 | Published 32-position snapshot |
| --- | --- | --- | --- | --- |
| Bitfinex R0 | `bitfinex/108d1814-edb4-418a-8dd2-f79c1cae06cc` | 315 | `f249e9e5566412ff4e8b33190ebd5133928a6b548cae3bcf12bc0148f7522ea3` | `0bd0f3424bd8cf05b10e9b9b99fa8d5178e5accf69d54dae663920da9a608061` |
| OKX live L2 | `okx/live/7c7e83f9-b19e-46a9-8b91-30d883212a35` | 156 | `0de8f9c9e6f8b56789b509e2f0402cb982d8641cd9f2184c8c3630ba0a0063a2` | `ba39e623f28911a0cc5959452f88e0f43b7abc5664f0e2bddb1587e3d77a99b3` |

The independent OKX historical input remains
`data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f`, raw
`fef59b343d1972c32f67583edc538c5d2f7350e6f3a0059e6f87896d7e8bf676`.
Its 32 canonical query messages produce **zero scheduled source events** because
original receipt/availability is unknown. Download time is not substituted.

The retained [parity consumer](../../tests/integration/consumers/capture/parity_consumer.py) was
copied outside the checkout and executed with `-I`, both directly and through the
notebooks. It compares live prefix bytes, canonical history, downstream exact
spreads/state, every completed checkpoint and an additional fresh-process resume.
The [recovery probe](../../tests/integration/consumers/capture/recovery_probe.py) separately injects
a disconnect and one exact repeat per session into original permitted Bitfinex
frames. It records new local receipts explicitly: two sessions, two duplicates,
one retained gap, two updates and canonical parity. This is controlled transport
intervention, not evidence that the real source emitted duplicate deliveries.
The intentionally changed first receipt is refused at raw position zero and both
observations are retained.

```sh
cd /private/tmp/mr27-validation/consumer
../installed/venv/bin/python -I recovery_probe.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' /private/tmp/mr27-validation/recovery-final
../installed/venv/bin/python -I parity_consumer.py /private/tmp/mr27-validation/installed-consumer '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/108d1814-edb4-418a-8dd2-f79c1cae06cc' '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/live/7c7e83f9-b19e-46a9-8b91-30d883212a35' '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' '/private/tmp/mr27-validation/recovery-final/captures/18f3df9b-cd6f-4fcb-84e9-f447ead6a151'
```

Wheel, drivers, installed environment and small external consumer reports remain
under `/private/tmp/mr27-validation`. Native bytes remain in ignored `data/` with
their requests/manifests and book prefixes. These are local development artifacts,
not a backed-up release archive; retain the bytes to reproduce their identities.

### Fresh-kernel notebooks

Notebook tooling was added only to the isolated candidate kernel; the runtime lock
is unchanged. Both maintained notebooks ran every cell from a fresh kernel:

```sh
uv pip install --python /private/tmp/mr27-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb --kernel-python /private/tmp/mr27-validation/installed/venv/bin/python
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr27-validation/installed/venv/bin/python
```

- Capture: **23 cells / 10 code cells passed**, attempt
  `5215cb3a-913f-44e3-a0d7-11a9df3cee71`, completed `2026-09-19T07:14:12Z`.
  Executed source SHA-256:
  `d0d0f8b67fa1ec5eb9d4de77adf8bf49eaaba15ac605a4dbab500c241ae8a46d`.
  A subsequent Ruff-only reorder of independent standard-library imports leaves
  all executed behavior/outputs valid; retained attempt bytes are unchanged.
  Current source SHA-256:
  `abce48366ba0915742d44878c93d5090f50d7813949556b32c891b4169d38ef4`.
- Foundations: **79 cells / 39 code cells passed**, attempt
  `50f2cef2-78af-404d-a138-63810c4d7e1e`, completed `2026-09-19T07:15:24Z`.
  Source SHA-256:
  `f4ed18590a77e64f1a6d5934749cb3219555955f088e77d09d9e38da1992361a`.
  NB 27 is section 18; named-source integration is capture section 10.

The foundations notebook independently selects the same saved Bitfinex capture
and retained OKX archive. Its synthetic recovery/first-divergence files are owned
by its temporary workspace and cleaned after small reviewed outputs are retained.
No notebook silently downloads substitute input or uses an editable import.

### Diagnosed development attempts

An initial 38-test run passed with one integration case intentionally deselected;
the final 178-test run includes integration explicitly. A new four-test run took
53.57 seconds but passed; a bounded archive-only diagnostic also passed in 7.27
seconds. No persistent failure or product timing cause was established.

Strict typing required an explicit `zip_longest` fill value. The first external
recovery probe incorrectly used a symlink for raw bytes; the raw store correctly
refused it. The fixture now copies those original bytes and succeeds without
weakening raw-store validation. Notebook import sorting was corrected after
successful execution as described above. Sandbox-denied uv-cache access was
rerun with host permission. No source contract, required assertion or gate was removed.

### Final source hygiene

Notebook schema, sequential execution counts and retained outputs passed. The
capture notebook differs from its successful attempt only by the verified import
reordering noted above. All eight maintained example sources are tracked; **199**
example/component local links and **60** documentation files passed their checks.
Only pre-existing temporary kernel directories remain; both new kernels closed.
The secret scan passed for **295 governed paths** before final staging. Generated
run/kernel/checkpoint paths remain ignored; configuration, lock, ignore policy
and frozen P1 bytes match the base.

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr27-validation/final_check.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
python3 /private/tmp/mr27-validation/count_lines.py
git diff --check
git check-ignore examples/runs/probe.ipynb examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

## Post-merge review corrections — 2026-09-19

The preceding evidence describes the original MR 27 candidate. This follow-up
corrects three review findings in the working tree based on merged MR 27 commit
`828cfaf076701a804f6826b7778031ced66ab7a6`:

- Coinbase snapshot bridging retains the last applied buffered source time and
  rejects backwards supplied clocks, including nanosecond regressions. Covered
  messages cannot advance that clock. Replay and reconstruction share the timestamp
  conversion, and a late REST receipt cannot freshen an old buffered update.
- Capture finalization runs blocking persistence, replay, verification and publication
  outside the event loop. Heartbeats continue; cancellation waits for the finalizer,
  and persistence failures propagate with the corresponding health flag.
- Shared Binance event validation bounds decimal representations before rational
  arithmetic. Lazy saved-input readers produce a rejected quality report without
  canonical bytes for oversized values. Supported values retain their exact scale.

The owning contracts are updated in [data contracts](../data/contracts.md) and the
[collector guide](../data/l3-collectors.md). All three regression tests reproduced
the original failures against the base source. The corrected installed package
passed **649 tests in 61.05 seconds**, including integration cases, with no skips
or deselections. The final run used CPython 3.14.7 on macOS arm64:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr27-fixes-env uv sync --frozen --no-editable --offline
PYTHONDONTWRITEBYTECODE=1 /private/tmp/mr27-fixes-env/bin/python -I -m pytest -q -p no:cacheprovider -m 'not performance' --basetemp=/private/tmp/m27-fix tests/unit/data tests/unit/pipelines tests/unit/test_serialization.py
```

All 78 installed Python modules matched the working-tree source bytes; installed
implementation identity:
`bfecde8d8087f84ec58404ade35f42c2b94104546b6ecde714a931737ab16c33`.
Whole-scope Ruff lint/format, strict mypy on the 11 changed Python files, Bandit on
the five changed runtime modules, engineering standards, architecture links and
`git diff --check` passed. Development attempts that could not bind local health
test sockets were rerun with host permission and a shorter temporary path.

Raw and canonical wire schemas are unchanged. Existing raw bytes remain retained,
but corrected Coinbase clocks can change derived quality and canonical observations;
regenerate affected derived snapshots from their originals. Out-of-bound Binance
decimals are now rejected. Historical capture/notebook evidence above was not rerun
for this patch. These are local synthetic and saved-input checks, not new live-source
qualification. Revert this correction patch to reverse the code changes while
preserving original raw inputs and diagnostics; no stored data was rewritten.

## Risks / reversal

Canonical parity covers only the explicitly selected prefix; whole-capture native
summary parity remains separately reported. Query/replay owns one native partition
per instance, with bounded in-memory full visible states. It does not supply a
cross-source nanosecond scheduler, complete depth/coverage, archive continuity,
causal eligibility or executable book admission. Coinbase live access remains
unverified. Supervised capture retains MR 26's existing raw-only CLI contract and
refuses publication flags; this MR does not extend that interface or claim full M3.
R1 and existing release restrictions still apply before any deployment.

Revert the three review slices in reverse order, preserving originals, manifests
and diagnostic reports. Raw and canonical schemas are unchanged; pre-existing
trade/native consumers retain their existing meaning. No service or trading
activation is performed. Full local `make check` is not repeated; the complete
hosted lane remains required before merge.

**Next: MR 28 — Compute versioned historical features**, after MR 27 merges.
No MR 28 implementation is included.
