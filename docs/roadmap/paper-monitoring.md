# Public-paper monitoring integration

Owner: quant development. Status: complete for the bounded local scope, 2026-09-27.
Scope: MR12 integration and affected MR10 evidence, from main `7b27816` on
`codex/mr12-public-paper-monitoring`; the starting worktree was clean.

## Bounded plan and acceptance

Deliver retained, reopenable monitoring for the existing installed, finite local
OKX/Bitfinex public-paper workflow, with dedicated and shared accounts. Follow the
[engineering guide](../coding_standards/README.md) and preserve the completed
[paper integration](paper-integration.md). Accounting, execution and independent
risk remain the authorities. Monitoring observes committed facts and never
retries execution, releases reservations or changes a protective block.

1. Add an execution-owned paper projection consuming existing account views,
   committed matching traces and exact accounting reports. Preserve account and
   strategy scopes, currency/quantity units, explicit gas applicability and the
   last-eligible-bid valuation policy. Cumulative balances/costs/P&L use last-value
   metrics; lifecycle events remain individually attributable.
2. Compose the existing collector health measurements, bounded telemetry writer,
   query/metric/chart APIs and retained dashboards into the public-paper
   application. Retain source/configuration/report and actual monitoring receipt
   identities. Reopening reuses received event bytes; retrospective reconstruction
   stamps its actual import receipt and cannot leak into earlier cutoffs.
3. Supply default paper views and explicit diagnostic local alert configuration.
   Keep custom registries/charts available. Make telemetry loss/storage/routing
   failures visible after committed actions without feeding them into execution
   failure handling. Recover monitoring from retained facts independently.
4. Extend the installed public-paper and operational consumers. Independently
   check dashboard economics for both venues and both account modes; qualify
   duplicate/restart, causal correction, storage/queue and local receiver recovery.
   Use fresh actual public inputs and a real local Unix datagram receiver for
   boundaries that fixtures cannot establish.
5. Run focused owner checks, installed acceptance and required `make check`.
   Update owning guides, roadmap and this record with commands, identities,
   outcomes, evidence reuse and precise limits. Inspect retained HTML as an
   operator artifact. Do not push or merge.

The new projection serves the public-paper application and operational consumer;
the application composition owns default view selection and retained artifacts.
Existing telemetry events/store, metric registry, dashboard renderer, bounded
health writer and local alert journal remain the implementations. No replacement
accounting engine, dashboard service or deployment machinery is introduced.

Reuse unchanged MR08/MR11 matching, allocation, accounting and source evidence,
and MR12 research extension/query evidence with an impact explanation. Renew
affected installed bytes and monitoring/alert boundaries. Diagnose failures at
their narrowest boundary before repeating expensive runs; retain failed attempts.

Reversal: revert the integration and its consumers together while preserving
account/capture/report/telemetry artifacts. No economic schema migration or
execution-model change is planned. Remote services, source-clock qualification,
human acknowledgement, authenticated/live trading, MR13 activation/recovery,
MR14 broader deployment and MR15 capacity are outside this slice. Final MR10
acceptance remains open.

## Implemented outcome

All five steps are complete. `run_live_shared_paper` now returns a separate
`PaperMonitoringResult` after economic commitment and retains a receipt envelope,
telemetry SQLite journal, default configuration, account/strategy dashboard pages
and `monitoring/index.html`. `execution.PaperMonitoring` reads the existing journal
and report; `telemetry.MonitoringConfiguration.paper` selects the existing exact
metric and chart APIs. The execution command's former configuration import stays
compatible through a re-export. Research/custom metric and chart registration is
unchanged.

The views include physical order state, attributed fills, rejects, pending and
uncertain exposure, independent blocks, reconciliation failures, currency cash,
inventory, fees/rebates, slippage, gross/net P&L and valuation age/budget. Each
currency and strategy has its own series. Gross P&L is net P&L plus fees minus
rebates plus modeled slippage; neither fees nor cumulative snapshots are debited
again. The cost report retains last-eligible-bid valuation and the reason gas is
inapplicable to this off-chain spot model. No FX or gas accounting was added.

Original native source text/nanosecond receipts and availability are retained.
Modeled lifecycle event times, report cutoffs and actual monitoring receipts stay
distinct. The measured monotonic callback duration covers match/decision work,
excluding feed transport/persistence; it is not the authored entry/cancel delay.
Source clock drift and receipt-to-durable delay remain `not_measured`. Retrospective
projection uses the actual import receipt; replay uses saved event bytes. A fresh
capture projects only new lifecycle traces and does not relabel old facts.

Default metrics select last cumulative values. Saved receipt cutoffs exclude late
corrections; changed retries are rejected by the existing store. Default diagnostic
routes, when explicitly supplied a socket, cover blocks, uncertainty,
reconciliation/source/runtime failure and currency net losses, including missing
or stale evidence. Configuration and result identities remain retained and editable
through the existing APIs. No route is enabled without an address.

Telemetry runs after account commitment. Its bounded queue, storage, incomplete
drain and alert failures produce diagnostic status, not account retries or control
changes. Incomplete ingestion refuses partial dashboards. Recovery reads the saved
receipt envelope without reopening the account or source. If projection failed
before any envelope could be retained, that missing artifact must be recovered by
a new projection with a new actual receipt; historical receipts cannot be invented.

## Runnable operator journey

From the repository root, install the frozen research package, then copy the
maintained consumer and public profiles outside the checkout:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr12-operator \
  uv run --frozen --no-editable python -c 'import applications.paper'
mkdir -p /private/tmp/mr12-consumer
cp tests/integration/consumers/runtime/public_paper.py /private/tmp/mr12-consumer/
cp configs/live/okx-btc-usdt.json configs/live/bitfinex-btc-usd.json /private/tmp/mr12-consumer/
/private/tmp/mr12-operator/bin/python -I /private/tmp/mr12-consumer/public_paper.py \
  --config /private/tmp/mr12-consumer/okx-btc-usdt.json \
  --output /private/tmp/mr12-okx-shared --live --adverse 0.01
/private/tmp/mr12-operator/bin/python -I /private/tmp/mr12-consumer/public_paper.py \
  --config /private/tmp/mr12-consumer/bitfinex-btc-usd.json \
  --output /private/tmp/mr12-bitfinex-shared --live --adverse 0.01
```

Each output must be absent. Each invocation is bounded to 20 frames or ten
seconds and opens only public subscriptions. Repeat each command with
`--dedicated` and a distinct `-dedicated` output for one strategy per account.
Omit `--live` for deterministic native-frame fixtures; `--no-trade` and
`--adverse 1.00` exercise the economic controls. The consumer binds a real local
datagram receiver and verifies the diagnostic messages it receives.

Open each output's `run/monitoring/index.html`, inspect both account pages and
each strategy page, then check `monitoring-reconciliation.json`,
`alert-delivery.json` and `run/monitoring/monitoring-status.json`. These are finite
retained observations; a protective block in a view remains a real block.
Repeat the original command with `--replay` and identical flags/output to verify
the original account bytes and rebuild identical monitoring with zero inserts.
The receiver path is retained for alert identity; identical delivered evidence
does not send again. A new delivery attempt requires new evidence/configuration.

For monitoring-only storage recovery, use
[`render_paper_monitoring`](../../src/applications/paper/README.md#automatic-public-input-accounts)
with the saved `run/monitoring-input.json`, the retained telemetry journal and a
new output directory. Preserve the route/journal configuration for the original
alert identities. The index links resolve back to the original input/report even
when the new output directory is elsewhere. The installed
[`alpha-execute monitor`](../../src/applications/execute/README.md#retained-monitoring)
also accepts the retained per-page configuration for custom views.

## Verification and retained evidence

The selected environment was local macOS 27 arm64, CPython 3.14.7, installed
research package, finite public-input process and local AF_UNIX receiver.
No private credentials, remote monitoring service or venue orders were used.
Installed implementation identity:
`5100c41df5613f88290996e58ac9fc9b77c59efa344e921f4264055fa2a0f9b9`.
All 335 runtime inputs matched the checkout byte-for-byte. Artifact/source
manifests, source archive, frozen lock, wheel and runtime requirements are retained
under ignored `logs/paper-monitoring/artifact/`; `evidence-index.json` identifies
the final per-venue reports, receipt envelopes, receiver and replay evidence.
The retained wheel SHA256 is
`59bb135de63fd93df082a418bc1b91d8df4cf2b82166551f030f82aa08769b5a`;
all 335 runtime inputs also match that wheel.

The final observed runs under `logs/paper-monitoring/observed-final/` independently
reconcile every dashboard economic result to rational arithmetic over committed
physical fill events and the retained final mark. Strategy totals reconcile to
the account without summing separate currencies. The final observations were:

| Run | Currency | Fees | Slippage | Net P&L | Socket accepted / receiver observed |
| --- | --- | --- | --- | --- | --- |
| OKX shared | USDT | 0.016896280000000000 | 0.000002000000000000 | -0.016918280000000000 | 4 / 4 |
| OKX dedicated | USDT | 0.008448140000000000 | 0.000001000000000000 | -0.008459140000000000 | 2 / 2 |
| Bitfinex shared | USD | 0.010000000000000000 | 0.000002000000000000 | -0.013202000000000000 | 3 / 3 |
| Bitfinex dedicated | USD | 0.010000000000000000 | 0.000001000000000000 | -0.011601000000000000 | 2 / 2 |

All four second-process replays retained identical account/order/trace hashes and
equal dashboards with zero new telemetry inserts. These authored paper losses
establish machinery, not strategy economics or calibrated execution. The OKX
shared run also retained a protective block and its diagnostic; successful
monitoring does not imply healthy admission. Commands and stderr/stdout remain
in `observe-final.py`, `observed-*-complete.log` and `replay-*-complete.log`.

`logs/paper-monitoring/operational-final/{okx,bitfinex}/` contains renewed MR10
installed-consumer evidence copied from the final gate's isolated workspaces.
Both retain sender statuses `delivered, failed, delivered` and separate receiver
observations `true, false, true`. A failed attempt is not silently resent after
receiver restoration; new evidence succeeds. Exact cash 49799.98, position 2,
fees 0.02, pending cancel quantity 2 and account protection remain unchanged.
Human acknowledgement and remote service status are explicitly `not_tested`.

Focused checks covered exact attribution, multiple currencies, no-trade/missing
valuation, report/trace clocks, reconciliation breaks and pending exposure,
storage failure/recovery, duplicate snapshots, late corrections, changed evidence,
bounded queue saturation, source-gap counts and recovery index links. Installed
public-paper cases also cover shared/dedicated, no-trade and adverse costs for
both venues, plus a new capture on the same account that preserves prior receipts.
The final focused projection/diagnostic run passed 9 tests; the earlier combined
owner/installed run passed 41 before the added source-gap regression.

Required final gate:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/paper-monitoring-env \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/paper-monitoring-complete-suite \
  TMPDIR=/private/tmp make check
```

`logs/paper-monitoring/make-check-complete.log` retains **1719 passed, 2 skipped,
3 deselected** and successful installed-wheel smoke, locks, Ruff, strict mypy,
native stub checks, engineering/dependency/architecture governance, Bandit,
dependency audit and secret scan. Performance-marked tests were outside this
required gate; MR15 budgets are not claimed. The development-only native
source-to-wheel exception of the time, since removed, still blocked artifact
release under its own policy; this work did not change it. Changed owning-guide links and whitespace
were checked separately. Retained OKX/Bitfinex HTML pages were visually inspected
using the existing renderer; recovery links also have a targeted regression.

Earlier failed attempts remain in the same log root: tuple decoding in the
acceptance consumer, conflicting unit-test basenames, one lint finding, and an
OKX consumer that unnecessarily recomputed a now-stale report. The consumer now
uses the already committed report/cutoff; freshness was not relaxed. An attempted
observation using an environment concurrently switched to editable installation
failed preflight; final observations used a separate immutable installed
environment. These attempts establish no source-availability success claim.

## Bounded dashboard contract revision (2026-10-01)

MR15 found that a dashboard over a populated hour (10,000 events per account) could
not meet its query budget while every view embedded, revalidated and rendered every
selected event. With owner approval the view contract changed; queries, cutoffs,
metric definitions, alert policy and hard-control independence did not.

- A `DashboardSnapshot` (`dashboard-view`) holds each metric's exact outcome,
  input count and digest, and its last 120 points, plus the count and digest of the
  whole selection, instead of the selected events.
- Retained views add `provenance.jsonl` with every selected payload. Reopening
  verifies it is a complete ordered selection inside the query matching the digest.
  Live readers page the same payloads from the store.
- Installed series metrics decode only what they show; their results equal full
  evaluation, which tests check for every aggregation. Custom and delayed-label
  metrics still evaluate every input.

Earlier retained dashboards use the previous schema and are not readable by this
code. The full test gate, including the installed paper, operational and research
consumers, passes on the new contract. The signed, installed and public-feed runs
recorded above predate it, so MR12's installed evidence needs re-running before
it covers this contract. That re-run needs its own declaration.

## Evidence reuse and remaining limits

MR08/MR11 matching, fee rounding/allocation, independent reconciliation, authored
execution scenarios, accounting schemas and risk enforcement are unchanged.
Their retained acceptance in [paper-integration](paper-integration.md) remains
applicable; renewed installed consumers exercise the new composition without
reopening matching mechanics. MR12's metric registry, custom research chart,
delayed-label revision, retention and alert-journal implementations are unchanged;
their tests pass again in the full gate. Only default view selection, projections,
application composition and affected local receiver boundaries needed new evidence.
MR10's signed install/rollback and MR04 service recovery evidence remain bounded
to their original environments; this record does not relabel them as new service
qualification.

MR12 is complete for this selected finite local paper environment. Continuous or
remote service operation, human acknowledgement, host/source clock accuracy,
long-outage failover and dashboard capacity are unqualified. MR13 owns paper
activation/recovery machinery, MR14 broader deployed multiple instances and
MR15 capacity. Final MR10 acceptance and MR17/G5 remain open. Private venue/live
qualification is KIV and is not mandatory for this paper acceptance. No production
submission authority, dependency-policy change, push or merge is part of this work.
