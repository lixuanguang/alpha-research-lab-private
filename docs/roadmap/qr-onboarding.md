# QR onboarding acceptance

Owner: quant development. Status: **open.** The journey passes in fault-injection
development runs; the preflight after the remaining work passed every J1–J7 criterion on
`b05cfca` (rehearsal-136 and rehearsal-137, below). The counted attempt waits for the frozen candidate and its
day rehearsal, and J8 for the day run's retention
([remaining work](overview.md#remaining-work-before-qr-onboarding)).

The [roadmap](overview.md#qr-onboarding-acceptance) owns the six acceptance items and
gate G5. This record declares the integrated fresh-entry journey that proves them. Live
trading stays out of scope; nothing here grants live authority.

G5 is the full research and paper-platform handoff. It does not block
[bounded offline research](overview.md#bounded-offline-research) whose selected data
and workflow have passed G2. QR forward paper/shadow operation still requires G5
and its separate activation decision. The counted journey and capacity criteria
remain required in full.

## Journey

**Principle.** One frozen commit, one set of installed artifacts, the published guides
only. The operator acts as a fresh QR. A step that needs knowledge outside the guides,
an edit to shared code, a deep import or a built-in fallback fails, and the guide gap is
recorded. Nothing is worked around inside an attempt.

**Environment.**
- A clean git worktree at the frozen commit, used only to build.
- Fresh environments built with `uv sync --frozen --no-editable`: one for building and
  one for research; the Feast worker from its own lock; signed execution targets
  installed by `alpha-governance-artifacts`.
- Local lakeFS and ClearML from `make local-services-up`, with existing private keys
  ([local services](../local-services/lakefs.md)).
- Evidence under `~/AlphaResearchEvidence.noindex/mr17/<attempt>/`, outside any synced
  folder.

**QR workspace.** A separate repository, authored from the guides alone, never under
`tests/` or `src/`. Its extension package, `mr17-extensions`, contains:
- a book feature (depth imbalance) and a non-book feature (signed public-trade flow) in
  one multi-feature schema;
- a fitted transform (train-only standardization) and a forward mid-return label;
- a non-built-in estimator (exact least squares), a rule policy emitting order/quote
  intents, and a learned policy emitting targets;
- a custom metric (net return per unit turnover) and a custom chart.

**Driver.** [`onboarding_journey.py`](../../tests/integration/consumers/journey/onboarding_journey.py)
runs one declared attempt. It retains every command in `commands.jsonl` before the next
starts, rewrites `summary.json` after each step, stops at the first failed criterion, and
never edits the QR workspace. It holds the host awake for the attempt.

| Step | What runs | Pass criteria |
| --- | --- | --- |
| J1 Provision | Build and verify the research wheel and signed `contracts`, `collector` and `execution` releases; install outside the checkout; local services; Feast worker; import audit and guide coverage of the QR workspace | Installs from the guides alone; installed identities recorded; an execution target holds no research, notebook, training or reporting modules |
| J2 Data | `alpha-collect capture-run` of a fixed window of public OKX BTC-USDT/ETH-USDT and Bitfinex BTC/USD/ETH/USD books and trades; replay; publication; discovery; quality and coverage; lakeFS publish and reopen | Every capture completes, gaps explicit; replay passes with original clocks; reopened bytes equal; specification versions and limits visible |
| J3 Research | Rule-only and learned walk-forward studies, costed, both decision kinds; a small grid; holdout; ClearML publication; fresh-process reopen; architectural extension | No built-in substitution; holdout consumed once; reports with the custom metric and chart; refusals before work |
| J4 Features | Offline retrieval, materialization and online serving of the QR feature; late revision, TTL expiry, missing entity, materialization retry and version rollback | Matched-cutoff parity exact; no future leakage; each fault explicit and recovered |
| J5 Candidates | Package rule and learned candidates; replay through the candidate loader | Replay decisions equal the study's at matched inputs |
| J6 Paper | Signed installation and activation per account; supervised deployment of both candidates on shared and isolated accounts in both venues, paper and shadow; shared-budget race, injected order uncertainty, selective stop and restart, adverse cost | Exact independent reconciliation; cost and P&L with gas inapplicable; no duplicate effect; custom metric on dashboards; alert received; shadow makes zero fills |
| J7 Operations | Quiesced backup; restore into fresh roots; resume from retained journals; signed upgrade and rollback | Restored identities equal; restored accounts quarantined; resumption without manual repair; rollback keeps current facts; decision delays within the studies' modelled delay; refusals only for paper-only rules |
| J8 Capacity | No new measurement in the journey | Links the measured full [research](research-capacity.md) profile and accepted [runtime](runtime-capacity.md) day run, 4× replay and 72-hour retention evidence |

**Pass and fail.** The journey passes only if every step passes in one counted attempt
on one frozen commit. A failed step is fixed in code or guides, and the journey is rerun
from J1. A counted attempt is never patched mid-run.

## Journey declaration

Abbreviations: `A` is `~/AlphaResearchEvidence.noindex/mr17/<attempt>` and `C` is
`$A/checkout`. `T` holds the environments and sockets (each socket path under 100
bytes). `GA` is `$T/build/bin/alpha-governance-artifacts` and `PY` is
`$T/research/bin/python -I`.

**J1 — Provision.**

```sh
git -C <repository> worktree add --detach $C <frozen commit>
cd $C
uv python install
UV_PROJECT_ENVIRONMENT=$T/build uv sync --frozen --no-editable
UV_PROJECT_ENVIRONMENT=$T/research uv sync --frozen --no-editable
uv pip install --python $T/research/bin/python --no-deps $A/qr/mr17-extensions
UV_CACHE_DIR=/private/tmp/uv-cache-research-worker \
  uv sync --frozen --project configs/development/research-worker
make local-services-up
make local-services-status
$T/build/bin/alpha-governance-engineering-standards import-audit $A/qr
$GA fetch --repository $C --request $A/j1/collector-request.json \
  --policy $A/j1/policy.json --dependencies $A/j1/wheels
$GA build ... --registry $A/j1/registry      # collector, as the runbook lists
$GA verify --release <collector release> --policy $A/j1/policy.json
$GA install --release <collector release> --policy $A/j1/policy.json \
  --target $A/j1/target-collector
```

Pass criteria:
- every command exits 0;
- the installed identities of research, extension, collector and worker are recorded;
- the import audit and guide coverage are clean: every platform name the QR workspace
  imports appears in the [quickstart](../research/quickstart.md), the
  [research guide](../research/guide.md) or a guide they link;
- an inventory of an execution target (built in J6) shows no `research`, notebook,
  training, tracking or reporting modules.

**J2 — Data.** One fixed window for all eight feeds: books and trades for OKX `BTC-USDT`
and `ETH-USDT`, and Bitfinex `tBTCUSD` and `tETHUSD`. The counted attempt's window is six
hours.

```sh
$T/research/bin/alpha-collect capture-run --config $A/j2/config/<feed>.json \
  --window $A/j2/window.json --run-directory $A/j2/runs/<feed>   # x8, concurrent
$T/research/bin/alpha-collect capture-run-replay --run-directory $A/j2/runs/<feed> \
  --max-seconds 7200                                                   # x8
PY $A/qr/studies/j2_publish.py --runs $A/j2/runs --store $A/j2/raw \
  --snapshots $A/j2/snapshots --lakefs-repository <repository>
$T/research/bin/alpha-dataset discover --snapshots $A/j2/snapshots \
  --max-entries 100 --max-bytes 64000000
PY $A/qr/studies/j2_reopen.py --snapshots $A/j2/snapshots --lakefs-repository <repository>
```

Pass criteria:
- each capture completed: it reached its stop deadline without exhausting its
  reconnects, named every gap, and exited 0 with no gap or 2 with gaps (the collector
  exits 2 whenever a window holds a declared gap);
- every run's replay passes, with original receipt and venue clocks;
- reopened lakeFS bytes equal the published snapshot;
- the catalog lists every partition with its specification version and limits;
- in J6, an `authorize_paper` request whose instruments come from the research
  selection, not the account's trading universe, is refused and leaves the account
  unchanged.

**J3 — Research.** The first five hours are walk-forward development (one-hour train,
30-minute test, 30-minute step). The last hour is holdout, consumed once by the selected
learned study.

```sh
PY $A/qr/studies/j3_study.py rule --snapshots $A/j2/snapshots --attempts $A/j3/attempts
PY $A/qr/studies/j3_study.py learned --snapshots $A/j2/snapshots --attempts $A/j3/attempts
PY $A/qr/studies/j3_study.py grid --attempts $A/j3/attempts \
  --thresholds 0.2,0.4 --horizons 30,60
PY $A/qr/studies/j3_study.py holdout --attempts $A/j3/attempts
PY $A/qr/studies/j3_publish.py --attempts $A/j3/attempts   # publish_experiments to ClearML
PY $A/qr/studies/j3_reopen.py --attempts $A/j3/attempts    # a fresh process
PY $A/qr/studies/j3_extension.py --snapshots $A/j2/snapshots --attempts $A/j3/attempts
```

`j3_extension.py` covers the architectural extension: ETH studies selected by
configuration only; the trade-flow input carried from study to candidate; and a study
with calendar `XNYS` and an instrument of product `perpetual`, each refused before any
source access or fold.

Pass criteria:
- both decision kinds are studied with costs;
- every component identity is the extension's fingerprint, with no built-in
  substitution;
- holdout consumption is recorded once, and a second access is refused;
- reports include the custom metric and chart;
- ClearML lists the published experiments;
- reopened results equal the originals;
- both refusals are recorded, with no attempt data written.

**J4 — Features.**

```sh
PY $A/qr/studies/j4_features.py define  --store $A/j4/store --feast $A/j4/feast
PY $A/qr/studies/j4_features.py offline --snapshots $A/j2/snapshots --store $A/j4/store
PY $A/qr/studies/j4_features.py stream  --version v1 --snapshots $A/j2/snapshots
PY $A/qr/studies/j4_features.py faults  --store $A/j4/store --feast $A/j4/feast
```

The faults step injects, in order: a late revision, TTL expiry, a missing entity, a
materialization retry after a stopped Feast worker, and a rollback from `v2` to `v1`.

Pass criteria: offline and online values are equal at matched cutoffs; no value is
served before its availability; each fault returns its declared pause reason, and
serving recovers exactly.

**J5 — Candidates.**

```sh
PY $A/qr/studies/j5_package.py --attempts $A/j3/attempts --store $A/j4/store \
  --candidates $A/j5/candidates
PY $A/qr/studies/j5_replay.py --candidates $A/j5/candidates \
  --snapshots $A/j2/snapshots --attempts $A/j3/attempts
```

Pass criteria: the packager refuses a changed parameter; replayed features, predictions
and decisions equal the study's at every matched instant.

**J6 — Paper.** Four accounts, eight source processes (book and trades for each
instrument), eight active instances and one provisioned inactive instance, inside the
qualified sustained envelope (at most 50-minute services under one-hour grants).

| Account | Instances |
| --- | --- |
| `okx-shared` | rule and learned @ OKX BTC (the shared-budget race pair); an inactive rule instance with a second grid origin, activated in J7 |
| `okx-isolated` | rule and learned @ OKX ETH |
| `bitfinex-shared` | rule and learned @ Bitfinex BTC |
| `bitfinex-isolated` | rule and learned @ Bitfinex ETH |

Commands follow the runbook's
[packaged-candidate path](../governance/operations.md#take-a-packaged-candidate-to-signed-paper):

```sh
$T/build/bin/alpha-governance-engineering-standards import-audit $A/j6/extensions/mr17-extensions
$GA fetch --repository $C --request $A/j6/services-request.json \
  --policy $A/j6/policy.json --dependencies $A/j6/wheels
$GA build --repository $C --request $A/j6/services-request.json --policy $A/j6/policy.json \
  --configuration $A/j6/services.json --dependencies $A/j6/wheels --audit $A/j6/audit \
  --key <key> --registry $A/j6/registry \
  --candidates $A/j6/candidates --extensions $A/j6/extensions
$GA verify --release <services v1> --policy $A/j6/policy.json
$GA install --release <services v1> --policy $A/j6/policy.json --target $A/j6/services
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment-check
# for each account: build, verify, install an execution target from those identities, then
$GA run --target $A/j6/target-<account> --policy $A/j6/policy.json -- account \
  --request $A/j6/requests/<account>-<install|authorize|observe|claim|serve>.json
$GA run --target $A/j6/services --policy $A/j6/policy.json -- feature-publisher ...
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment \
  --owners $A/j6/owners.json --root $A/j6/service-root --socket $T/s/supervisor.sock
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment-control \
  --socket $T/s/supervisor.sock --request $A/j6/controls/<identity>.json
```

| Phase | Supervisor life | Shape |
| --- | --- | --- |
| P-A | 30 min | Paper; reconciliation every 60 s. Selective `stop_instance` and `restart_instance` (with an observation) of the learned instance on OKX BTC at 10 min. Ends with an injected death of the `okx-isolated` owner while a request is in flight |
| P-B | 10 min | Recovery as the runbook: stop, inspect, reconcile, resolve the uncertain order, fresh claims, relaunch |
| S | 10 min | Shadow, on two fresh shadow targets with the same candidates on BTC, under their own grants |

Scenarios:
- **Shared-budget race.** On `okx-shared`, the rule candidate's quote size plus the
  learned candidate's target exceeds the per-instrument limit, so the first decisions
  contend for it.
- **Adverse cost.** Every scenario declares a nonzero adverse cost.
- **Alert.** A threshold on the QR's net-per-turnover metric is set so that it fires
  within the step; a local receiver retains it.
- Each account's orders are projected per hour against the 80-order grant before the
  run.

Pass criteria:
- exact independent reconciliation at every round;
- cost and P&L per strategy, with gas inapplicable;
- no duplicate economic effect, and the uncertain order is never retried;
- the race is admitted once and refused once, with the account inside its limit;
- served-feature lineage is retained and verified on replay, and trades deliveries are
  retained;
- exact replay of every delivery log, with only the killed owner's tail unattributed;
- the custom metric is on each account's dashboard, and an alert reached the receiver
  during the step;
- shadow made zero fills.

**J7 — Operations.** `$B` is the backup set `<evidence root>/<attempt>.j7-backup`,
outside `$A` because a backup cannot sit inside its source.

```sh
JP="PY $A/consumers/journey_paper.py"; P=$A/j6/paper
SIGNED="--launcher $GA --targets $P/targets --policy $A/j6/policy.json"
$JP quiesce --plan $P $SIGNED                     # no fence held; stop running accounts
PY $A/qr/studies/j7_backup.py --workspace $A --backup $B/research \
  --record $A/j7/research-backup.json --worker <feast worker>
$JP backup --plan $P $SIGNED --backup $B --record $A/j7/paper-backup.json
PY $A/qr/studies/j7_restore.py --backup $B/research --root $A/j7/restored/research \
  --record $A/j7/research-backup.json --worker <feast worker>
$JP restore --plan $P $SIGNED --backup $B --restored $A/j7/restored \
  --record $A/j7/paper-backup.json
$JP reclaim ... ; $JP owners --plan $P            # R: from the retained journals
$GA build ... --configuration $P/services-upgraded.json ...   # revision 2 activates the late instance
$GA install --release <services v2> --policy $A/j6/policy.json --target $P/services
$JP reclaim ... ; $JP late ...                    # U
$JP facts ... --output $A/j7/facts-before.json
$GA rollback --release <services v1> --policy $A/j6/policy.json --target $P/services
$JP reclaim ... ; $JP facts ... ; $JP rollback-check ...   # B
$JP delays --plan $P --attempts $A/j3/attempts --roots <every paper service root> ...
$JP refusals --plan $P $SIGNED --output $A/j7/refusals.json
```

Phases R, U and B run the supervisor and publisher for 5 minutes each, each ended by a
`shutdown` control. U stops the late instance 30 s before its end.

Pass criteria:
- every restored manifest equals its backup's, and studies reopen with equal reports;
- the restored QR store and the restored paper store serve equal values, the paper store
  by replaying every J6 delivery log exactly;
- each restored account receipt equals its backup receipt, its facts equal the retained
  journal's, and it is quarantined while the retained journal is not;
- resumption from the retained journals needs no manual repair: every command is a
  runbook step that exits 0, with J6's per-phase checks in R, U and B;
- the upgrade receipt names v1 as previous, and the late instance decides;
- after the rollback, the receipt selects v1 with v2 as previous and the deployment
  check equals v1's; facts are extended unchanged, terminal orders are unchanged, the
  late instance places nothing, and U's delivery logs still replay exactly;
- every paper decision delay is at most its study's modelled entry delay;
- every paper refusal carries a declared paper-only reason (`self_trade_conflict`,
  `holding_limit`, `instance_limit`, `account_limit`, `firm_limit`, `insufficient_cash`,
  `insufficient_owned_inventory`, `order_notional_limit`).

**J8 — Capacity.** No new measurement in this step. It is `pending` until both full
capacity records are accepted: the measured 72-hour research corpus and workflow,
and the counted runtime day, 4× replay and retention check at least 72 hours later.
Extrapolated research acceptance or a bounded G2 scope cannot satisfy J8. A failure
in either required profile, including retention, prevents G5 acceptance. The
record owner verifies these evidence requirements before supplying the two records;
the journey driver checks the referenced files exist, not their measurement content.

**Evidence layout.**

```text
~/AlphaResearchEvidence.noindex/mr17/<attempt>/
  declaration.json  summary.json  commands.jsonl
  checkout/         frozen worktree, used only to build
  consumers/        driver copy
  qr/               QR workspace copy
  logs/             every command's output
  j1/ ... j8/       each step's inputs and outputs
```

Builder keys are created per attempt under `$T/keys` (mode 0700). Sockets live under
`$T/s`.

## Counted attempt

- It runs the declared six-hour J2 window and full phases through J7 on the frozen
  candidate, the one the counted day run also qualifies. The freeze comes before both
  counted runs ([acceptance policy](overview.md#remaining-work-before-qr-onboarding)).
- No full uncounted journey on the frozen candidate is required. One fault-injection
  development preflight after the last code change, before the freeze, covers the code.
- It needs separate owner approval, and the owner chooses its host. It runs before the
  counted day run, and no fault injection overlaps the measured day.
- Changes after the freeze follow the roadmap's
  [candidate changes and reruns](overview.md#remaining-work-before-qr-onboarding). A
  guide- or record-only change does not by itself require a rerun. A code fix makes a
  new candidate, which needs a renewed counted journey and its own day evidence.
  Workload, configuration or grading changes repeat the runs whose evidence they affect.
- A failed attempt keeps its original outcome; diagnostics never regrade it, and a rerun
  replaces no earlier attempt.
- J8 is evaluated after the day run's retention and measured full research capacity pass.

## Development runs

Development runs are uncounted and are not evidence. The development harness runs the
real driver's steps on the working tree, records every criterion without stopping, and
can reuse earlier J2 or J3–J5 outputs. Its fault-injection mode runs a 30-minute J2 with
300 s segments and freezes one collector for 40 s.

| Run | Code | Result |
| --- | --- | --- |
| rehearsal-126 (2026-10-07) | `c998a28`, QR `7a7f28e` | J1–J7: 292 of 293. OKX dropped the frozen collector's connection; the collector recorded the gap and exited 2, which failed the old exit-zero criterion. J2 now grades each capture's printed result; all eight captures pass that criterion |
| rehearsal-127 (2026-10-07) | `8c25636`, QR `7a7f28e` | J1–J5 passed every criterion; all eight captures completed with no gap. At 07:44 UTC, during J6, the source checkout was switched to `main` outside the run, so the J6 shadow and J7 upgrade builds used different code from the packaged candidates and were refused (`installed environment differs`). Not a code defect: the development harness now snapshots the working tree instead of linking it |
| rehearsal-128 (2026-10-07) | `2ec69a1`, QR `7a7f28e` | J1–J7: all 293 criteria passed, on the renamed driver with the working tree snapshotted; the frozen collector completed with no gap |
| rehearsal-135 (2026-10-10) | `c4a5f78` | J1–J7: every criterion passed, including the six `candidate_metric_on_dashboards` checks. It predates the later telemetry, source shutdown, supervisor delivery and paper decision-lifecycle changes, so one more preflight is required after the remaining work lands |
| rehearsal-136 (2026-10-13) | `5723ac3` (storage #124, D2 #125), QR `7a7f28e` | Fault injection: 30-minute J2 with 300 s segments, the OKX BTC-USDT book collector frozen for 40 s. J1–J7: 292 of 293. J2 27/27, J3 47/47, J4 16/16, J5 15/15, J7 85/85. J6 failed only `P-A:race_admitted_once_and_refused_once`: the check read refusals from decision-time batch results, but under D2 a contender is refused at its modelled arrival (the okx-shared journal held 111 arrival-time `holding_limit` refusals). Harness defect, fixed in #126 |
| rehearsal-137 (2026-10-14) | `b05cfca` (#126; shipped code identical to `5723ac3`), QR `7a7f28e` | J2 and J3–J5 reused from rehearsal-136; J1 19/19, J2 reopen 5/5, J6 84/84 (the race passed: `reference-okx-btc` refused at arrival while `rule-okx-btc` held a reservation), J7 85/85. With rehearsal-136 this covers every J1–J7 criterion on the delivered code; J8 not run |
