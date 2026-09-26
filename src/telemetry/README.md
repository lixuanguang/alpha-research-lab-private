# Monitoring, metrics, dashboards and alerts

Owner: quant development. Status: implemented local monitoring interfaces;
external venue/service qualification remains with
[MR11/MR12](../../docs/roadmap/README.md#mr12-delivery-and-acceptance).
This package is included in both operating wheels and imports no research stack.
It cannot submit orders, release a risk block or change account state.

## Events, queries and retention

`MonitoringEvent` (`monitoring-event-v1`) retains a named semantic version,
exact rational value and units, or an explicit missing reason. Fixed bounded
context fields correlate scope/mode, release, strategy, model, dataset, source,
study, account, instrument, venue, order, fill, state epoch and incident.
Sensitivity and clock quality travel with each fact. Raw requests, credentials
and arbitrary label dictionaries are not telemetry payloads.

Event time, source availability and monitoring receipt are separate UTC clocks,
ordered `at <= available_at <= recorded_at`. Producers supply real receipt at
the boundary; importers must not invent historical receipt. A sample key is
scope/mode/name/version/sample. Corrections retain its context, units and event
time, and advance revision and receipt clocks. A late recovered source fact may
have earlier source availability; its later receipt still prevents leakage into
earlier queries. Changed retries fail; identical retries are idempotent.

`TelemetryStore.append` atomically persists a bounded batch in a separate SQLite
journal. `query(MonitoringQuery(...))` selects one scope/mode in `[start, end)`,
with `end <= as_of`; both availability and receipt must be at or before `as_of`.
Only the latest eligible revision of each sample is returned. Queries default
to 10,000 facts, permit up to 100,000, and fail on overflow. No truncation is
hidden in a metric. An absent journal yields no observations, which metrics
report as missing. A malformed or incompatible journal fails visibly.

The default retained capacity is one million revisions. Capacity exhaustion
rejects the whole append. `store.prune(before_utc)` explicitly removes complete
event-time samples and advances a persistent retention floor; queries and appends
before that floor fail. A caller must retain needed dashboards before pruning.
There is no automatic destructive cleanup. A telemetry writer rejects another
application's database rather than adding tables to it. SQLite write-lock waits
are bounded to 50 ms; filesystem latency itself is not bounded by that setting.

## Metric and chart extension

Register an injected `MonitoringMetric` with `MetricRegistry`. `MetricSpec`
(`metric-spec-v1`) pins the implementation digest, semantic version, named input
versions/units, output units, operating applicability, aggregation, missingness
and optional freshness budget. Configuration selects identities; it does not
import arbitrary code. A selected semantic version never consumes a newer one.

`SeriesMetric` supports last, sum, mean and maximum with exact arithmetic.
Missing inputs propagate; last evaluates the last observation. Staleness uses
the evaluation cutoff and event clock, independently of receipt liveness.
`DelayedLabelError` joins prediction and outcome samples only after the selected
label revision was available **and received**. Pending labels remain chart gaps;
the mean uses observed pairs and their retained points expose coverage. Reopening
an earlier cutoff does not acquire a later correction. This is diagnostic
machinery, not evidence of model quality or empirical alpha.

The [study bridge](../research/studies/README.md#research-monitoring-bridge)
adapts the same definitions to existing MR03 `MetricValue`/`ChartSpec` reports.
Quant development's installed study consumer adds its own metric and chart,
retains study and paper views, and exports actual saved predictions/outcomes.
No collector, shared study runner or dashboard renderer changes for that extension.

`DashboardConfig` selects up to 32 panels (line/bar/table) and 32 alert rules.
`DashboardBuilder.build` evaluates only the registered definitions. Its retained
`DashboardSnapshot` contains config, query, selected input bytes, exact results
and alert outcomes. `write(directory)` writes JSON, self-contained HTML and a
digest manifest; `read(directory)` verifies both data and rendered bytes.
Identical writes are idempotent; conflicting or incomplete outputs fail visibly.
Preserve incomplete output for diagnosis and regenerate into a fresh directory.
Charts break at missing points and retain exact tables alongside approximate SVG
coordinates. No browser script, remote resource or dashboard service is required.

## Operating signals and commands

`ExecutionMonitoring` projects authoritative account/venue state after operations.
Account/venue CLI calls opt in with `--telemetry /absolute/monitor.sqlite3`.
Signals include risk blocking/admission rejection, reconciliation age/failure,
open/uncertain/rejected/cancel-pending physical orders, venue recovery/receipt
counts, alert failures and exact currency cash/instrument inventory. Currency
and instrument series remain distinct; no implicit FX or cross-account sum is
performed. Monitoring failure is returned as `telemetry_error` after the operation;
it cannot undo an already committed stop or reconciliation break.

`ProcessSupervisor` retains periodic and final observations to `monitor.sqlite3`
under its existing output root. `HealthRecorder` uses one bounded worker queue;
its storage I/O never runs on the watchdog's control thread. Overflow, persistence
failure and unfinished shutdown work remain explicit in `health-summary.json`.
Protection runs before the final bounded recorder drain. Process heartbeat,
ingestion/durable progress, market activity, received/durable frame counts,
invalid/duplicate/gap counts, reconnects, queue bytes/age/peak and latest
receipt-to-durable lag are separate signals. Receipt lag is measured with local
monotonic clocks through durable append; it is not exchange latency. Source clock
drift is explicitly `not_measured`; receipt/source differences cannot establish it.

For an existing telemetry journal, create an explicit editable view using the
installed API (substitute the actual scope, mode and UTC observation window):

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from applications.execute import MonitoringConfiguration
from serialization import DomainCodec
from telemetry import MonitoringQuery, TelemetryStore

now = datetime.now(UTC)
query = MonitoringQuery(
    scope="account:shared", mode="paper", start=now - timedelta(minutes=5), end=now, as_of=now
)
events = TelemetryStore(Path("/absolute/monitor.sqlite3")).query(query)
config = MonitoringConfiguration.defaults(query, events)
Path("/absolute/view.json").write_bytes(DomainCodec().encode_json(config))
```

Then render without alert delivery:

```sh
alpha-execute monitor --config /absolute/view.json \
  --journal /absolute/monitor.sqlite3 --output /absolute/retained-view
```

The default views are explicit last-value data/runtime or risk/account selections,
with a 60-second freshness budget and **no alert routes**. Edit the returned
definitions/panels/thresholds to fit the declared operating contract. The CLI pins
the actual installed metric implementation bytes; a code change requires an
explicit new config identity. Custom code is injected through the public Python
registry; the CLI supports the built-in series and delayed-label implementations.

## Alerts and hard-control independence

`AlertRule` declares an exact unit-matched threshold, comparator, local syslog
socket, and separate missing/stale policies (`trigger` or `unavailable`).
Inapplicable/unavailable metrics are never silently healthy. Evaluation alone
sends nothing; passing `--alerts /absolute/alerts.sqlite3` authorizes the CLI's
configured local routes. The existing `OperationalAlerts` journal retains pending,
delivered and failed attempts. Delivery means only local datagram acceptance,
not human or remote acknowledgement. Repeated identical evidence/rule bytes do
not send again; changed evidence creates a distinct attempt. An interrupted
pending attempt is not silently replayed. Alert-store failure is retained as
`alert_persistence_failed` in the dashboard.

Thresholds are diagnostic. Hard risk, stop/cancel, fencing and recovery retain
their independent owners. Reference tests block telemetry storage and saturate
its queue while checking that supervision/protection still completes. The
installed shared-account workload verifies dashboard retries and failed local
routing without changing exact cash, positions, fees or stops.

## Qualification and remaining boundaries

Current software evidence covers installed retained studies, local account
controls and scripted OKX/Bitfinex spot adapters. Neither a fixture venue label
nor a rendered chart establishes external venue conformance. Authorized demo/
paper-account access is still unavailable under MR11. Remote service routing,
acknowledgement, host/source clock qualification and deployed failure drills
remain unproven. Dashboard volumes/latency and retention sizing beyond the stated
bounds belong to MR15, not an inferred capacity result from these small workloads.
MR13 activation, MR14 deployed multiple instances and MR17/G5 remain open.
