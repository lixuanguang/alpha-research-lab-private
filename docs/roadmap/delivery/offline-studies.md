# MR03 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared bounded offline study/backtest/report scope**.
MR03 does not accept G2 or QR onboarding.

`applications.explore.evaluate_study` and `compare_studies` compose the existing
MR02 named-input feature, fitted-transform, estimator and policy interfaces with
exact accounting/risk, configurable execution/cost models and retained reports.
Typed values and strict serialized configurations select the same implementations;
external extension bytes join the installed distribution in run identity and
retained artifacts. The [study guide](../../../src/research/studies/README.md#generalized-decision-studies)
owns the API, report readers, publication modes and reversal. The
[simulation guide](../../../src/simulation/README.md#offline-decision-intent-studies)
owns execution assumptions and lifecycle support.

Walk-forward folds retain actual source/features/outcomes, resolved temporal
splits, fitting exclusions, fitted state, predictions, decisions and reconciled
ledgers. Source reads and label cutoffs protect a contiguous final holdout;
consumption survives failed access and changed-run retries are refused. Reports
carry exact versioned custom metrics/charts, predictive missingness, safe HTML/SVG
and typed manifest-verified readers. The existing Optuna journal retains failed,
rejected and pruned trials within the original budget. Local/deferred publication
separates computation from the existing recoverable ClearML outbox.

Dependency ownership remains explicit: MR07 owns the delivered **offline**
order-lifecycle prerequisite (entry/cancel/replace, expiry, partial IOC and declared
passive queue sensitivity); deployed OMS/reconciliation remains open. MR05's
capability admission and historical reference-resolution slices support offline
studies, while candidate/runtime binding remains open. MR12 owns the versioned
report metric/chart interface slice; runtime dashboards, telemetry and alerts
remain open. MR04's existing ClearML and Optuna integrations are reused without
claiming service provisioning, feature serving, jobs or recovery complete.
MR15 capacity budgets and MR17/G5 integrated handoff remain unaccepted.

Evidence is retained under ignored `logs/mr03/`; original retained MR02 capture
and publication bytes are reused without changing their provenance or universes.
`validation-context.json` binds the checkout, exact installed implementation,
wheel and consumer bytes. No new source availability observations are claimed.

| Boundary | Evidence and limit |
| --- | --- |
| Exact and causal contracts | `focused-final.log`: 25 focused tests passed. Independent expected losses/fees, partial fills, cancel/replace, quote rejection, queue sensitivities, historical reference changes, predictive missingness, report escaping and failed/pruned/rejected search cover software contracts. `source-cutoff-focused.log` additionally rejects a source that advances the requested cutoff; the offending bytes and failed attempt survive without a report. |
| Fresh installed components | `installed-studies-final.log` and `installed-studies-final/`: copied consumer runs with the clean wheel and `-I` outside the checkout. Fresh feature/transform/model/policy/metric/chart code reaches two walk-forward folds, typed/JSON config, exact losing/no-trade studies, passive queue sensitivity, retained fit exclusions, fresh-process readers, deferred search resume and failed holdout protection. Extension source bytes are retained, not replaced by defaults. |
| Retained actual sources | `captured-studies-final.log` and `captured-studies-final/`: the same installed workflow reopens MR02's original 100-message OKX/Bitfinex captures, trades and references. Each venue makes two costed fills; fees are exactly 0.01681253 USDT and 0.02 USD respectively. Native observations and receipt clocks remain retained. This is source consumption under explicit simulation assumptions, not observed exchange fills or complete historical coverage. |
| Actual publication recovery | `clearml/publication.log`: the existing verifier publishes one ordinary study and all three search attempts to the pinned local ClearML service, including a failed trial. It loses a local receipt after remote success, resumes in a fresh process and proves unique remote tasks, exact downloaded artifact bytes and unchanged attempt histories. Credentials and service state stay in ignored local evidence; the task's compose stack is stopped after verification. No production service is deployed. |
| Complete local gate | `make-check-final.log`: full `make check`, including all 1,305 non-performance tests, typing/native stubs, architecture/engineering/dependency/security checks and clean wheel installation. `component-links.log` also checks the changed guides outside the default docs scan. The final gate uses a short macOS pytest path and a dedicated environment. |
| Diagnostics and scope | `make-check-initial.log` retains the earlier full pass; it does not replace the final gate after the source-cutoff regression. `source-cutoff-stale-install.log` is explicitly a transcription of an initial stale installed-wheel failure, with the rebuilt-wheel pass retained separately. Initial focused/source logs are preserved without relabeling them as final acceptance. |

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar03-main-env TMPDIR=/private/tmp \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar03-check' \
  make check > logs/mr03/make-check-final.log 2>&1

# Use the isolated wheel interpreter emitted by make check; copy consumers and
# research_workflows/ outside the checkout, then use absolute evidence paths.
"$STUDY_PYTHON" -I decision_study.py "$REPO/logs/mr03/installed-studies-final"
"$STUDY_PYTHON" -I captured_study.py \
  --selection "$REPO/logs/mr02/source-publication/selection.json" \
  --snapshots "$REPO/logs/mr02/source-publication/snapshots" \
  --raw "$REPO/logs/mr02/public-acquisition/raw" \
  --captures "$REPO/logs/mr02" --output "$REPO/logs/mr03/captured-studies-final"
ALPHA_CLEARML_LOCAL_ENV="$REPO/logs/mr03/clearml/local.env" \
  "$STUDY_PYTHON" -I clearml_publication.py \
  "$REPO/logs/mr03/installed-studies-final/attempts"
```

The exact accepted wheel and dependency export are retained under `logs/mr03/`,
with SHA-256 fingerprints. Output directories must be new when reproducing these
consumers; retain earlier attempts instead of overwriting evidence. The local
service uses the existing [ClearML profile](../../../configs/development/clearml/README.md).

Support remains cash-funded, single-account spot per fold, with up to 32 folds
and 1,024 decisions per schedule; search is a bounded 1–32-variant grid. Folds
have independent capital/state; initial/terminal marks are not an intraperiod
equity curve. Passive queue/latency assumptions are synthetic sensitivities.
Real captures use explicit receipt-as-matching clocks; Bitfinex L3 is aggregated
to visible depth without queue inference or invented trade prints. OKX resolves
then-known reference grids; Bitfinex uses explicitly authored 0.01 USD tick and
0.00001 BTC lot because the saved reference lacks those values. Bitfinex venue
grid/fill fidelity remains unqualified under MR11, not silently accepted by MR03.

Non-book inputs retain their own source family; neutral interfaces reject
unsupported products and dimensions. Supplied Python code remains trusted;
fingerprints are not authentication. Losing results are engineering acceptance,
not empirical strategy evidence. The existing QuantLib source-to-wheel admission
restriction still blocks release use under MR06. Feature services, shared-account
portfolio/execution, venue conformance, dashboards, capacity, MR17/G5 and production
readiness remain with their owners. No data purchase, live order or capital
activation is authorized by this delivery.

Reversal removes the additive study/intent/report APIs and their consumers together;
existing configured trade/book/model studies and saved schemas remain supported.
Keep new attempts and extension bytes with the matching wheel; older wheels do
not read the new schemas.
