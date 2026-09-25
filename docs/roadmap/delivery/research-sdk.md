# MR02 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared research/decision SDK scope**, 2026-09-24.
Owner: quant development. This is current infrastructure MR02, not a historical
milestone or empirical QR deliverable. The working tree was clean before this
additive implementation; changes remain uncommitted for founder review.

Delivered through existing functional owners:

- Named trade/book/reference/non-book numeric inputs, explicit clock/units/freshness,
  causal source projection and independent missingness/lineage. Public OKX/Bitfinex
  trades and venue assertions reuse MR01 readers; L2 and visible-order imbalance
  preserve source-specific receipt/event semantics and controls.
- Versioned ordered multi-feature schemas, pure batch/incremental transitions,
  exact values, entity/version/availability/TTL contracts and instance-bound
  checkpoints. Projection, stateful expanding means and a fresh nonlinear feature
  execute through the same feature session.
- Independent arbitrary outcomes and verified temporal sample alignment;
  train-only fitted transforms with explicit changed output signatures, generic
  estimator adapters and immutable reload
  state. Exact centering, nonlinear nearest-example inference and an external
  estimator exercise more than fixed return/linear schemas.
- Typed target-position, currency-exposure, limit-order and two-sided quote intents;
  feature/prediction signature admission and isolated stateful policies. Rule-only,
  learned and stateful reference consumers run through typed/serialized
  `DecisionRun`, `applications.explore.run_decisions` and `inspect_decisions`.
  Existing attempts retain completed/failed research traces and fitted bytes.
- Fresh feature/label/estimator/quote implementations in a copied installed
  consumer, with independent exact expectations and fresh-process continuation.
  Future perturbations preserve earlier outputs; changed signatures/units, corrupt
  state, foreign instances and unsupported product/calendar/capability combinations
  fail explicitly. Separate instruments retain independent state.

The [feature guide](../../../src/research/features/README.md#generalized-feature-lifecycle),
[model guide](../../../src/research/models/README.md#generalized-estimator-lifecycle),
[observation guide](../../../src/research/observations/README.md) and
[strategy guide](../../../src/strategies/README.md) own interfaces, runnable examples,
semantics and reversal. The
[fresh installed consumer](../../../tests/integration/consumers/research/decision_extensions.py)
and [saved-source consumer](../../../tests/integration/consumers/research/decision_sources.py)
are maintained acceptance workloads, not research recommendations.

Dependency ownership stays bounded. MR03 owns the application-composition and
local retained-result slice pulled forward for these consumers; its generalized
formal studies, execution/cost models, search, metrics/charts and reports remain
open. MR05 owns the research capability-declaration/admission slice, while its full
registry, candidate manifests and runtime loading remain open. MR16 owns the
public API/typing/OOP compliance slice; broader migration remains open. MR04
consumes the new feature version/entity/availability contract but still owns its
Feast extension, online/offline services, materialization and operational recovery.
Existing Feast/lakeFS/ClearML/search/analytical integrations are retained; none
is replaced or declared generalized merely by this delivery.

Evidence is retained in ignored `logs/mr02/`. The repository's previous `logs/`
directory disappeared during an interruption. Original MR01 samples and earlier
MR02 logs are consequently unavailable at their recorded paths. With explicit
founder authorization, MR02 evidence was recreated using fresh public samples;
these new observations do not reconstruct the historical MR01 acceptance record.
`validation-context.json` records that distinction and the installed artifact.

| Boundary | Evidence and limit |
| --- | --- |
| Exact and causal contracts | `focused-final.log`: 26 focused tests passed, including the installed fresh extension and public-data consumers. Independent means, nonlinear predictions, warm-up, TTL, late corrections, future perturbation, state integrity, changed transform width/units, horizon-specific label identity and restart are software evidence. |
| Retained external source bytes | `public-acquisition/`, `okx-capture/`, `bitfinex-capture/` and their logs retain fresh public responses and two bounded 100-message book captures. `source-publication/` pins publications and selections through the existing MR01 workflow: 241 selected trades, original local receipt clocks and replay continuation. `installed-sources/` and `installed-sources.log` retain completed wheel-based decisions for both venues, with all three selected numeric fields nonmissing. This establishes source consumption, not complete-tape or venue execution qualification. |
| Fresh installed extensions | `installed-extensions/` and `installed-extensions.log`: a copied feature/label/estimator/quote consumer uses the isolated wheel outside the checkout; exact forecasts 7/9, first bid/ask 106/108 and fresh-process restart agree. Actual fitted bytes, config, traces and attempts are retained. |
| Source-order regression | An earlier real-source run exposed distinct trades sharing event/knowledge timestamps. Its original failed-attempt bytes were lost with the logs; they are not reconstructed. The corrected projection uses retained native position for ties, with a dedicated independent regression in the focused suite and successful fresh-source consumers. |
| Full local validation | `make-check-final.log` retains the complete final gate, including static/native contracts, dependencies/security, all non-performance tests and clean wheel installation. `component-links.log` explicitly covers changed guides outside the default docs scan. Earlier observed full passes are not substituted for this retained final proof. |
| Environment and access diagnostics | An earlier collection failure followed overlapping uv commands changing the shared environment mode; its original log is unavailable. Final checks use one isolated task environment sequentially, with no disabled requirement. `public-acquisition.log` preserves a sandbox DNS failure followed by the successful authorized network retry. |

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar02-env TMPDIR=/private/tmp \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar02-check' \
  make check > logs/mr02/make-check-final.log 2>&1
```

The exact built wheel and SHA-256 are retained under `logs/mr02/wheels/`;
`wheel-sha256.txt` pins artifact bytes. Temporary environments are disposable.
The repository's existing QuantLib source-to-wheel restriction still blocks release
use; this development/CI acceptance does not resolve MR06 deployment admission.

Support is the declared research SDK and retained OKX/Bitfinex spot projections.
Non-book and other-calendar/product fixtures establish interfaces or explicit
refusal, not qualification of another live asset class. Custom components are
trusted supplied code with versioned identities; retain their exact implementation
alongside source data, configuration, state and the matching wheel. Digests are
not artifact authentication. Research processing times and synthetic reference
observations are labeled assumptions, not latency or market-fidelity measurements.

MR02 does not deliver generalized economic reports, passive-fill fidelity,
provisioned feature serving, paper/shadow deployment, execution/account controls,
capacity qualification or trusted candidate promotion. These remain with their
owning MRs, as do G1's full installed foundation acceptance and G2–G5. No empirical
strategy, QR onboarding, production deployment, data purchase, live order or capital
activation is accepted or authorized here.

Reversal removes these additive APIs and consumers together. Existing return,
linear, scheduled, saved-book and integration schemas remain readable. Preserve
new vector/checkpoint/model bytes with their matching implementation; older wheels
do not read the new schemas. Do not hand-edit checkpoint bindings to migrate state.
