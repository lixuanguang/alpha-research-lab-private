# Paper activation and recovery

Status: complete for the bounded signed local scope below. Owner: quant development. Scope: MR13 and
its MR10 evidence, from main `b4a1193`, branch
`codex/paper-activation-recovery`. No push or merge is authorized.

## Bounded implementation plan

An operator installs an admitted independent execution release, inspects a
versioned disabled paper deployment, explicitly authorizes a bounded reference
workload, and consumes OKX or Bitfinex public books through the existing paper
OMS. Block, cancel and attributable reduction remain distinct. Restart and
compatible code rollback retain committed orders, fills, fees, costs,
reservations and checkpoints. Monitoring reports outcomes without authorizing
work or retrying economics. Engineering workloads establish software behavior,
not profitability or private venue fidelity.

Repository rules are owned by the [engineering guide](../coding_standards/README.md),
including its documentation section (the former separate documentation page is
absent). No applicable `AGENTS.md` was found. Existing risk, accounting,
portfolio attribution, matching, journals, workspace recovery, installation and
monitoring remain functional owners.

1. Correct monitoring's account-order selection; prove two populated account
   ledgers remain unchanged during successful projection.
2. Add immutable deployment and separate authorization records. Bind release,
   account/instances, candidate/policy, model/features/input, configuration,
   execution scenario and compatible state. Installation records a disabled
   selection; authority bounds instruments, simulated size/count and UTC duration.
   Reject production authority. The account journal owns durable grants,
   revocations, owner generations and checks inside serialized transactions.
3. Fence admission, matching and restart. Recheck current time and generation
   at economic boundaries; revoked/expired authority prevents new exposure.
   Retain safe controls and processing of already committed obligations. Reuse
   risk and reservation checks. Reduction belongs to account operations and
   routes bounded attributable sell orders through the same OMS/matcher.
4. Connect the signed account launcher and public-paper API with a supported
   installed interface. Extend existing installed consumers and dependency
   admission; do not install the research wheel to evade release restrictions.
5. Reconcile before claiming a new worker generation. Preserve the latest
   journal on compatible code rollback. Version managed state so incompatible
   old readers reject it. Workspace snapshots stay stopped and quarantined;
   supported local recovery uses retained current state. A snapshot alone cannot
   prove the absence of newer economics, so it cannot activate managed execution.
6. Renew focused and installed evidence, then update owning guides/runbook and
   roadmap. MR10 remains open for MR14 deployed-service requirements; MR14,
   MR15, live execution and real capital are outside this slice.

## Acceptance and evidence method

Use independent exact economic expectations for invalid/expired/revoked or
mismatched authority, stale owners, partial fills, absent liquidity, stop vs
cancel vs reduce, strategy ownership, and restart/rollback preservation. Unit
checks establish account transaction behavior; installed artifact consumers
establish package isolation, signed launch, compatibility and rollback. Bounded
public/local drills qualify both venues and shared ownership where affected.
Monitoring failure must leave controls effective and never repeat execution.

Retain actual commands, first failures, corrections, source/artifact identities,
results and limitations here and in `logs/paper-activation/`. Diagnose failures
at their smallest boundary before repeating an expensive drill. Reuse unaffected
MR08/MR11 matching/accounting and MR12 diagnostic evidence with a specific impact
explanation; renew changed entry points and artifacts. Run applicable repository
checks without weakening typing, dependency, numerical or hosted merge gates.

## Implementation and validation record

The managed operating boundary is the signed execution `paper` runner using
`account-runtime-v1` configuration and `account-journal-v3` state. Its admitted
execution/contracts closure owns economics. `InstalledPaperAccount` connects
the existing public-paper Python workflow to that runner using retained typed
requests and responses, without installing the research wheel into the target.
The client collects inputs/evaluates engineering policies; the installed owner
independently checks grants, generations, risk and reservations. Legacy raw v2
simulation APIs remain development interfaces and cannot substitute for this
managed installation contract.

`PaperDeployment` is immutable and disabled. It binds compatible signed release
digests, exact account configuration, instance/policy/candidate/model/feature
identities, public input selection, execution scenario and state ABI. The separate
`PaperAuthorization` grants a half-open UTC interval, cumulative admitted buy
quantities and order count, plus per-order notional. Selling, cancellation and
renewal do not replenish the deployment's budget. Both records reject production
authority. Model/venue/authority context is checked again at portfolio admission;
the public entry checks exact policy/model/feature/input identities before capture.

Durable serialized transactions fence ownership and recheck current time at
economic boundaries. Expiry/revocation prohibits new exposure and claims, while
the current owner may drain committed obligations with fresh data. Operator
stop, cancel and bounded attributable reduction remain independent actions.
Grant replacement requires a stopped account and settled physical outcomes;
otherwise it preserves the existing owner so cancellation can finish. Accepted
standing orders remain reserved through replacement. Rejected or timed-out
installed commands are retained and never automatically retried.

Reduction reserves a normal IOC sell at an explicit minimum price and maximum
fee. It requires fresh observed quotes, recent eligible matching input, independent
reconciliation, known outcomes and owned inventory after outstanding sells.
The ordinary paper matcher alone supplies fills and terminal cancellations.
Manual managed fill/post/lifecycle injection is rejected. Partial fills, zero
liquidity, cancellation requests and rejected reductions do not imply liquidation.

Latest-journal restart and compatible code rollback preserve all economic facts,
checkpoints, reservations and protection. Restored snapshots are quarantined
before publication; none can silently resume managed execution. This conservative
boundary replaces a proposed snapshot-age comparison: a local snapshot cannot
prove that no newer economics exist elsewhere. Loss/replacement of the latest
journal, hostile same-user tampering, host-volume disaster recovery and schema
migration remain unsupported by this bounded local claim.

MR12 now filters trace orders by selected account. The regression populates two
accounts and verifies successful projection with both ledgers unchanged. Existing
monitoring failure/receipt-reopen checks remain applicable; diagnostic errors
never authorize work or retry execution. New signals expose disabled deployment,
grant presence/validity/expiry/revocation, owner generation, restore quarantine
and accepted/rejected/unresolved reduction outcomes.

### Focused economic and failure evidence

- Authority/operations/reduction/recovery tests use independent exact economic
  expectations. A two-unit buy at `10.01` with a 1% fee consumes `20.2202` cash:
  from `1000` to `979.7798`, holding `2`, fees `0.2002`. The partial state is
  `989.8899` cash, `1` unit, fee `0.1001`; restart/rollback and duplicate market
  input retain the same identities/economics. Protective sales cannot consume
  another strategy's inventory or already reserved sells.
- Expired/revoked owners retain safe reduction and cancellation processing.
  A replaced owner cannot admit, match or reduce. Unaccepted sends and pending
  cancellation prevent grant replacement until the matcher settles them.
- Model/feature mismatches reject before public capture; mismatched model, venue
  or production portfolio context rejects before orders/checkpoints/ledgers change.
- Historical snapshot publication is tested with a failed quarantine during
  staging; no destination is published. Successful copies are already quarantined. Fresh
  reconciliation cannot remove that quarantine. Current journal recovery remains
  available with a new generation and listed compatible release.

Final focused check:

```sh
PYTHONPATH=src:tools/governance/src .venv/bin/pytest -q \
  tests/unit/execution/test_paper_activation.py \
  tests/unit/execution/test_account_reduction.py \
  tests/unit/runtime/test_paper_recovery.py \
  tests/unit/runtime/test_public_paper.py \
  tests/unit/execution/test_paper_monitoring.py
```

Result: **36 passed** (`logs/paper-activation/focused-final.log`). The final
complete repository gate used an isolated environment:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/paper-activation-check-env \
PYTEST_ADDOPTS=--basetemp=/private/tmp/paper-activation-complete-suite-final \
TMPDIR=/private/tmp make check
```

Result: **1,748 passed, 2 skipped, 3 performance cases deselected**, plus installed
research-wheel smoke; lock checks, Ruff, strict mypy/native stubs, engineering
standards, architecture links, dependency admission/audit, Bandit and secret scan
passed (`logs/paper-activation/make-check-final.log`). The existing development-only
QuantLib source-binding exception remains visible; the signed execution closure
does not include QuantLib or the research wheel and does not use that exception.
The two skips are existing real-Feast worker integrations: this shell has no
`ALPHA_FEAST_WORKER_PYTHON` selection (`skip-reasons.log`). They are unrelated to
the paper authority/OMS boundary; this change does not requalify Feast services.

### Signed operator qualification

Both native-message reference consumers passed using the existing signed launcher
and independent execution target. Each starts with `100000` quote cash, creates
two attributable fills (one unit per strategy), and independently reconciles
modeled execution at `100.50` against a `99` mark. The venue currency grids give:

| Path | Final cash | Fees | Position | Net P&L | Evidence directory under `logs/paper-activation/` |
| --- | ---: | ---: | ---: | ---: | --- |
| OKX / USDT | 99798.799 | 0.201 | 2 | -3.201 | `okx-qualified-public-v2/` |
| Bitfinex / USD | 99798.80 | 0.20 | 2 | -3.20 | `bitfinex-qualified-public/` |

`cancellation-verification.json` retains requested and matcher-confirmed terminal
cancellation. `reduction-verification.json` retains the per-instance reservation
and zero-fill IOC outcome: one displayed bid lot at 50% modeled participation
cannot supply a whole admitted lot. No liquidation is claimed. Unit evidence
separately covers available/partial liquidity and other-strategy reservations.
`recovery-verification.json` proves exact retained economic projections across
release selection, independent reconciliation, generation 1-to-2 reclaim and
idempotent market retry. The summary's legacy `restart_replay_equal` field is false
because that direct-journal replay is not invoked; the signed proof is reported
by `code_rollback_equal`, `reclaimed_after_rollback` and `market_retry_equal`.

Both `postrun-verification.json` records compare final installed per-instance
checkpoint queries with the last successfully committed coordinate requests,
read back all three committed batches, and retain equal before/after economic
digests. `postrun-monitor.sqlite3` exposes owner generation `2`, accepted reduction
`1`, unresolved reduction `0`, and `risk.blocked=1` after the final signed stop.
Both qualified targets are left stopped. These final diagnostics use read-only
installed state queries and do not repeat execution. The signed launcher's argument
allowlist rejects `--telemetry`; telemetry-path failure injection is therefore
covered by the existing owner-application unit test and MR12 diagnostic recovery
tests, rather than bypassing that release boundary for a drill.

| Venue | Initial / rollback release SHA-256 | Upgrade release SHA-256 |
| --- | --- | --- |
| OKX | `b8e62d1ade0156cfbe33f0f40926a55638644a4eb3b5b05864b849f72c8d2e45` | `8146fadef4ef3a2936989afcb3071008ee63be3175ec906cca5f5f4d8e2bdef6` |
| Bitfinex | `5f055254f3bb0d4dfca142e6770934efad9a94574a0190d304b7fbb3a467eff5` | `ee23b1359d69a7e33f46dc3778aafd1a9610a710bdcc2a1955544951c1d747df` |

Bundles live in `logs/paper-activation/registry/<release>/`; fresh dependency
audits are in `qualified-build-<venue>-<phase>/`. All four use source manifest
`3005f32d61d836ed3af9ebf208c5e65ec9f85fcf95b3b52b546db9c1a96e248d`,
contracts wheel `590713d9e12e63d55fc17dc34fe22903483454331186bced32a65b40df049c37`
and execution wheel `051dd64e2ab87187c999378985a5efd18fd8d4438d86f08c7178874bf12a1f5f`.
Their 326 captured source Python files match the final implementation. These are
distinct signed release identities with identical code/wheel bytes: the proof is
compatible signed code selection and preservation, not an old v3 implementation
or schema migration. The nine-package target contains no research distribution.

The qualified reference consumer SHA-256 is
`d8379cc466118aad84a957e83adc6e25f7c87c073e697108ab5e41604a766b67`.
The account configuration hashes are
`d52c2d9e8725ca25889ed9749b1ebac3b9c51de547254d2d532d8a5fd0fdd4a1` (OKX) and
`73b97c191cfad388221ff191523a29235d5183d61e7c4abd5bc9a7b5a851ddb1` (Bitfinex).
The explicit reference profile uses 30-second freshness, a 60-second capture
deadline and the existing finite four/five native-message caps. Final consumer
changes affected fixture clocks, paths and wire requests; runtime package bytes
stayed fixed. Ruff, strict mypy and engineering standards passed after those edits.
The final eight existing public-consumer integration cases also passed after the
fixture corrections (28.37 seconds). Their first restricted-shell attempt failed
to bind the local Unix alert socket; the host-permitted rerun passed all eight.

### Operator commands

The [runbook](../governance/operations.md#managed-public-paper-activation-and-recovery)
owns request authoring, independent observations, safe controls and recovery.
From the repository root, this inspects the qualified stopped OKX target:

```sh
paper_repo="$PWD"
paper_evidence="$paper_repo/logs/paper-activation"
uv run --frozen alpha-governance-artifacts run \
  --target "$paper_evidence/targets/okx-qualified-public-v2" \
  --policy "$paper_evidence/release-policy.json" -- account
```

To repeat the bounded fixture journey in a new absent target while its retained
grant and signing policy remain valid:

```sh
paper_repo="$PWD"
paper_evidence="$paper_repo/logs/paper-activation"
paper_initial=b8e62d1ade0156cfbe33f0f40926a55638644a4eb3b5b05864b849f72c8d2e45
paper_upgrade=8146fadef4ef3a2936989afcb3071008ee63be3175ec906cca5f5f4d8e2bdef6
uv run --frozen --no-editable python \
  tests/integration/consumers/runtime/public_paper.py \
  --config configs/live/okx-btc-usdt.json --freshness-us 30000000 \
  --output "$paper_evidence/new-okx-run" \
  --launcher "$paper_repo/.venv/bin/alpha-governance-artifacts" \
  --target "$paper_evidence/targets/new-okx" \
  --policy "$paper_evidence/release-policy.json" \
  --account-config "$paper_evidence/registry/$paper_initial/configuration/config.json" \
  --release "$paper_evidence/registry/$paper_initial" \
  --upgrade-release "$paper_evidence/registry/$paper_upgrade" \
  --rollback-release "$paper_evidence/registry/$paper_initial" \
  --deployment "$paper_evidence/okx-qualified-activation-v2/deployment.json" \
  --authorization "$paper_evidence/okx-qualified-activation-v2/authorization.json"
```

For Bitfinex use `configs/live/bitfinex-btc-usd.json`, its tabled release IDs,
`bitfinex-qualified-activation-v2/`, and new Bitfinex target/output names. Requests,
responses, capture, reports and dashboards remain in the chosen output. A new
owner is running after the recovery assertion; submit a separate `control/stop`
when finishing a manual repeat. Expired grants require a newly authored bounded
authorization and fresh explicit claim. Changes to consumer, input selection or
configuration require regenerated bindings, not reuse of an old authorization.
The exact build, preparation, drill and final-stop transcript is
`logs/paper-activation/commands.md`; inputs and outputs remain alongside it.
Protected signing keys are not copied into evidence.

### Retained diagnosis and corrections

Ignored `logs/paper-activation/` retains the first failures as well as successful
runs. Initial cache-access failures were permission/environment issues; checks
then used an isolated environment. Initial formatting/typing errors included
protocol propagation and a boolean literal unsupported by the wire decoder;
the deployment keeps an explicit `enabled is False` invariant. The engineering
checker rejected peer application imports, so command/response and recovery
receipt wire records moved to the execution owner with compatible public exports.
It also identified missing test-helper docstrings, fixed before acceptance.
The bounded subprocess adapter has the repository-required annotated Bandit
exceptions for its explicit signed-launcher argv; the security gate passes.

The first full gate stopped on those docstrings (`make-check-first.log`). A
subsequent full gate passed 1,745 tests and installed wheel smoke
(`make-check-before-binding-guards.log`). Final review then added explicit
model/feature/context rejection and its three regressions, so the full gate and
affected artifacts were renewed. Preliminary signed bundles are retained as
superseded evidence and were not used to claim final qualification.

The first final OKX signed consumer attempt installed successfully but rejected
its relative request path before deploying or executing. This was a harness path
normalization error; the supported adapter requires absolute operating paths.
The failed target/output remain retained, and the corrected attempt uses a new
absent target with regenerated exact workload/deployment identities.

The next OKX attempt reached synchronized native capture but its fixture source
timestamps were already about 5.2 seconds old after signed preflight. The existing
5-second freshness guard correctly produced no inputs, decisions or fills; the
consumer's expected nonempty trace assertion then failed. Fixture messages are
now authored at connection opening, preserving the same native messages and
freshness limits. Failed runs and their empty economic journals remain retained.

The following signed attempt committed a fresh market but rejected coordination
after command round trips exceeded the 5-second account quote budget. The
retained quote-to-error-receipt interval was about 8.08 seconds (an upper bound
including response persistence). There was no admitted economic commitment.
The signed reference drill therefore selects `--freshness-us 30000000` explicitly
and binds that 30-second assumption consistently in account configuration, input
requirements and feature expiry. The original 5-second failure remains evidence.
Actual fixture source time is authored at each receipt; runtime guards and their
stale-input regressions remain unchanged. This is a bounded software workload,
not latency/capacity acceptance or a production freshness recommendation.

The first 30-second OKX profile completed two attributed fills, independent
monitoring/reconciliation and terminal cancellation. It then hit a consumer
request validation error: `stop_instance` is an ownerless protective wire action.
The corrected consumer omits the inappropriate owner field; the installed
execution packages did not change. The completed partial proof remains in
`okx-qualified-public/`: cash `99798.799`, fees `0.201`, position `2`, net P&L
`-3.201`, from starting cash `100000`, two units bought at `100.50` and marked
at `99`. Each of the two strategies owns one unit and its own fee attribution.

### Evidence reuse and limitations

MR08/MR11 [paper integration](paper-integration.md) still owns native reconstruction,
matching algorithms, fee rounding, public source connectivity, and no-trade/losing
and sensitivity examples. Their arithmetic and source adapters did not change;
new authority and signed request boundaries are requalified here. MR12
[monitoring evidence](paper-monitoring.md) still owns actual local alert receiver
delivery, receipt replay and dashboard query semantics. The changed account
selection and new operational signals receive focused regressions; both signed
venue journeys renew projection through the managed entry point.

The fixtures establish software behavior on OKX/Bitfinex native public messages,
not exchange fills, queue priority, empirical profitability or calibrated latency.
There is no production authority, private credential requirement or real capital.
MR10 incorporates these local results but remains open for MR14 multiple-instance
deployment and deployed service failure/restoration. MR15 capacity, continuous
monitoring and remote routing remain separate.
