# MR 26 — Independent live health supervision

Owner: repository founder. Status: implemented and locally verified for separate
review on 2026-09-19; not merged or deployed. Branch: `codex/mr-26-live-health`.
[Draft PR #53](https://github.com/lixuanguang/alpha-research-lab-private/pull/53)
records hosted checks and review status. Runtime review head: `bbff348`.
Base: fetched `origin/main` at `8b3027b5848cad8534364c93e028a6768e7e6077`.
Direct prerequisites MR 24 / PR #51 (`12be1a6`) and MR 25 / PR #52 (`8b3027b`)
are in that main history. The [roadmap](README.md#m3-reliable-live-capture) owns
scope and acceptance; [collector usage](../data/l3-collectors.md#mr-26-independent-health-supervision)
owns commands and response semantics.

## Problem / change

A connected collector could keep receiving heartbeats while economic progress
stalled, and an in-process observer could not detect loss of the collector itself.
MR 26 adds explicit health configuration and an independent parent process around
the existing finite capture. It observes process heartbeat, accepted ingestion,
successful persistence, MR 25 economic freshness, queue peak, reconnects and
retained invalid/gap counts. It also bounds startup, observation-lock acquisition
and finalization. Raw bytes, native validation and CaptureConfig serialization
remain unchanged.

An unhealthy run stops locally before attempting an alert. The bounded adapter
uses Python's existing `SysLogHandler` with nonblocking Unix datagrams and reports
missing/full-socket delivery failure. It retains policy/runtime identities, last
observations, exit status, stop result and delivery status beside the child capture.
Interrupted replay still verifies MR 23's committed prefix and exposes unknown
tail loss. No source connection was required for this MR's acceptance.

## Affected scope and review size

Against `8b3027b`: **275 added + 7 deleted = 282 production code-bearing lines**.
Counts include imports, annotations, validation and executable pipeline wiring;
blank lines, comments/docstrings, tests/fixtures and notebook acceptance cells are
excluded. One 12-line JSON health configuration is reported separately. There
are no dependency, lockfile, ignore-policy, runtime schema or governance changes.
`docs/research/p1-baseline.md` is byte-for-byte unchanged.

Two review slices keep each declaration with its first useful consumer:

| Slice | Operation, caller and lifetime | Production count |
| --- | --- | --- |
| `5cd07b8`: bounded collector observations | `collect`/`receive_frames` update `HealthMetrics`; the direct collector regression reads its snapshot. Nine shared integers live for one invocation. | 62 added, 0 deleted |
| Independent supervision and response | `supervise` consumes validated `HealthPolicy`, owns the child and composes stop plus `HealthAlert`; the installed capture flag and failure consumer exercise it. | 214 added, 8 deleted |

Per-slice totals count two replaced import lines across the slice boundary. The
second slice is a deliberate cohesive overage above the preferred 150 lines:
independent process ownership, startup/progress policy, bounded shutdown and alert
failure handling need to be reviewable together as one working response. Splitting
these further would leave the configured watchdog or its declared response absent.
No validation was removed or code compressed to meet the target.

## Validation result

CPython 3.14.7 on macOS arm64. **73 focused tests passed in 67.87 seconds**, with
zero skips or deselections. They include existing capture, raw-prefix recovery,
quality, configuration and OKX capture cases plus the new health policy, actual
process failures, failed local alert delivery and full socket pressure.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' --basetemp=/private/tmp/mr26-final-tests tests/unit/data/live tests/unit/data/venues/okx/test_okx_capture.py
uv run --frozen --no-editable pytest -q --basetemp=/private/tmp/mr26-final-consumer tests/unit/data/live/test_health.py
uv run --frozen --no-editable pytest -q --basetemp=/private/tmp/mr26-portable-consumer tests/unit/data/live/test_health.py
```

The final health-only rerun passed **13 tests in 11.38 seconds**, with no skips or
deselections, and verifies the shortened temporary socket path used by the notebook; the earlier 73-test run used the same runtime and a longer fixture
socket location. The final portability follow-up changes only the fixture socket
root to `/tmp` (the same macOS directory, also present on Linux): **13 tests passed
in 11.67 seconds**. Runtime and notebook bytes are unchanged, so their installed
and fresh-kernel evidence is reused. Ruff lint/format passed for both runtime files, three Python
test/fixture files and the notebook. Strict mypy passed on the five Python files;
engineering standards and focused Bandit passed:

```sh
uv run --frozen --no-sync ruff check src/alpha_research/data/live/health.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_health.py tests/unit/data/live/test_capture.py tests/fixtures/mr26/health_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/live/health.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_health.py tests/unit/data/live/test_capture.py tests/fixtures/mr26/health_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/live/health.py src/alpha_research/pipelines/live.py tests/unit/data/live/test_health.py tests/unit/data/live/test_capture.py tests/fixtures/mr26/health_consumer.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/live/health.py src/alpha_research/pipelines/live.py
uv run --frozen --no-sync alpha-governance-architecture
```

The full hosted lane remains required before merge. No release or merge was
performed. Hand review confirms configuration/telemetry operations remain in the
library, response/process composition remains in the pipeline, all spawned work
has an owner, and no raw payload or credential enters the alert.

### Installed consumer and notebook

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr26-validation/dist
uv run --frozen --no-sync python /private/tmp/mr26-validation/install.py
cd /private/tmp/mr26-validation/consumer
/private/tmp/mr26-validation/installed/venv/bin/python -I ../verify_identity.py
/private/tmp/mr26-validation/installed/venv/bin/python -I health_consumer.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/configs/live/bitfinex-btc-usd.json' /private/tmp/mr26-installed-consumer-2
```

The temporary installer calls the existing `_InstalledWheelCheck.validate`:
hash-locked binary dependencies, governance-free imports, exact-value smoke and
installed compatibility all pass. Source, wheel and installation match across
**79 runtime files**. The tracked consumer is
[health_consumer.py](../../tests/fixtures/mr26/health_consumer.py); it ran with `-I`
outside the checkout. Its final socket-path/startup changes were also exercised
by the fresh notebook's isolated subprocess and final focused rerun.

- Wheel SHA-256: `d2c82de7362ea78b5979722fe67b4e95bc91e119d3ea8935ae88f65e6e8f9108`.
- Installed implementation: `4b3dd90a626ee377259f698d14dad8556e28858eadd9a885e4a6a57a690f927e`.
- Wheel/environment/identity drivers remain under `/private/tmp/mr26-validation`;
  these are local development artifacts, not a durable release archive.

From the checkout, notebook tooling was installed only in the separate candidate
kernel; runtime dependencies and `uv.lock` did not change:

```sh
uv pip install --python /private/tmp/mr26-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr26-validation/installed/venv/bin/python
```

All **75 cells / 37 sequential code cells passed** against the installed candidate.
Attempt `3f13ebac-720b-45bf-9d4f-0f74652cda90` completed at
`2026-09-19T05:52:51Z`; source SHA-256:
`a8ba2f81411cc8fe0245c7df45d689c111063331e23b2fd924c6c09bddaf9be7`.
NB 26 is section 17. It displays policy, three configuration refusals, ten process
outcomes and distinct heartbeat/economic clocks, queue peaks and invalid counts:

| Scenario | Expected observed result |
| --- | --- |
| Healthy bounded snapshot | Completed; three committed frames; no alert |
| Heartbeat-only market input | `market_stalled`; receipt and persistence continue |
| Input starvation | `persistence_stalled` takes precedence over stalled ingestion |
| Blocked event loop / killed child | `heartbeat_stalled` / `collector_lost` |
| Read-only journal | `persistence_failed`; earlier committed frames remain readable |
| Invalid price / reconnect / queue pressure | `invalid_limit` / `reconnects_limit` / `queue_limit` |
| Missing alert socket | `market_stalled`; child stopped, delivery false |

The installed consumer uses real spawned processes, SIGKILL for the loss case,
actual journal permissions for disk refusal and actual local socket delivery.
Source transport alone is synthetic. Numerical clock deltas and committed tail
lengths can vary with scheduling; reasons, protection and prefix invariants are
asserted. The notebook retains small outputs; temporary test inputs are removed.
Maintained examples remain tracked; only already-permitted run artifacts are ignored.

### Diagnosed attempts

Initial startup budgets exposed interpreter initialization before the heartbeat;
startup now has an explicit separately validated allowance. The reconnect fixture
initially hit its stricter invalid-count threshold first, so it now permits those
retained gaps while testing its reconnect limit. A combined run returned 70 passes
and one failure when the queue scenario reached `startup_stalled`; the fixture now
uses a 60-second startup allowance and isolates one-second fault budgets. Ordinary
configured policy defaults remain the maintained example's shorter budgets.

A report-parser test initially requested unsupported `object` decoding from the
domain codec; it now uses the existing `Wire` JSON boundary. Failed notebook attempt
`65650700-25e6-4eb5-89ce-652ae1634e88` reached NB 26 but rejected its long temporary
Unix socket path. The fixture now creates a short owned socket directory under
`/tmp` (the macOS `/private/tmp` alias); the runtime path validation remains intact. Sandbox-denied cache
and local-socket operations were rerun with the required host permission. No
source/quality invariant or failure expectation was weakened.

## Risks / reversal

This accepts local POSIX process supervision and syslog socket delivery only.
Remote routing, operator receipt, loss of the watchdog/host and deployed service
recovery remain unproven; R1 is still required before deployment. Stop can leave
uncommitted accepted input, which is reported as an invalid unknown tail rather
than continuity. A failed medium may also prevent its final summary from being
saved, but stop and alert precede that write. There is no automatic restart,
no new source admission, no execution enablement and no canonical parity claim.

Revert the MR 26 change to remove the optional supervised path; prior native
capture configs and raw input retain their existing meaning. Preserve saved
failure reports when investigating a stopped recording. The next roadmap package
is **MR 27 — Prove capture/replay parity**, after MR 26 merges. It was not started.
