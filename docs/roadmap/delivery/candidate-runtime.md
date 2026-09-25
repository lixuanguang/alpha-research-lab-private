# MR05 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for candidate packaging and local intent-only runtime binding**,
2026-09-24. Owner: quant development. This is the current infrastructure MR05;
it does not accept a QR strategy, deploy a service or activate trading.

Delivered through existing functional owners:

- `research.experiments.CandidateBundle` retains immutable rule-only and learned
  manifests and verified content objects. The resolved dataset selection, completed
  MR03 experiment/attempt, exact report, feature schema, chosen fold's fitted bytes,
  component implementation/parameter identities, and candidate remain linked.
  Changed or unrelated components cannot borrow another report's acceptance.
- `configuration.CapabilityRegistry` resolves all six capability families through
  explicit environment selections. Product, venue, calendar, mode, named channel,
  depth, clock, field units, freshness, lifecycle and order operations fail closed.
  Requirements remain distinct from fixture/read-only/external qualification.
- `runtime.CandidateLoader` recreates the registered feature, policy, optional
  transform/model and metric/chart definitions. Replay and runtime use identical
  candidate bytes without implicit refitting, dynamic import or built-in fallback.
  `CandidateDeployment` links placement to the candidate and its resolved input,
  instance, universe and profile identities without adding executable authority.
- `applications.explore.run_candidate` and `runtime.CandidateFeatureFeed` provide the
  public source and offline/online feature paths. Exact fitted-state availability,
  signatures, warm-up, cadence and combined feature/policy checkpoints preserve
  causal state. Invalid transitions cannot partially commit. Stale, missing,
  changed-version or unavailable online features pause with unchanged state.

The [candidate guide](../../../src/research/experiments/README.md#candidate-bundles)
and [runtime guide](../../../src/runtime/README.md#candidate-loading-and-intent-evaluation)
own supported interfaces and failure behavior. The installed reference consumer
authors a fresh feature, transform, estimator, order/target policies, metric and
chart through those interfaces. Both candidates originate in completed costed
MR03 studies; their outputs and fitted provenance remain engineering evidence.

Acceptance commands and retained evidence live in ignored `logs/mr05/`:

| Boundary | Evidence and result |
| --- | --- |
| Candidate integrity and provenance | `bundle-focused.log`: completed-attempt/result linkage, exact selected artifacts, substitution/corruption, unsafe paths, qualification and idempotent publication |
| Typed admission | Focused registry tests cover all six families, incompatible signatures/modes, unknown selections and explicit OKX/Bitfinex clock distinctions |
| Atomic state and failure semantics | `runtime-focused.log`: policy/order failure rollback, cadence, warm-up, gap reset/pause, restart isolation, corrupt checkpoint and real SQLite freshness/missing/expiry boundaries |
| Installed fresh extensions | `candidate-focused-final.log`, `candidate-installed-source.log`: rule-order and learned-target studies/bundles; replay/runtime/source/offline parity; five pre-read rejection scenarios per candidate; exact fresh-process restart |
| Actual feature-store adapter | `candidate-feast.log`, `candidate-installed-feast.log`: same bundles through isolated Feast 0.66.0; source/offline/online parity and stale/service-loss/version-change pauses |
| Final local gate | `make-check.log` retains the complete `make check`, including isolated wheel installation. `final-installed-source.log` and `final-installed-feast.log` renew candidate proofs against that wheel; `final-source/` and `final-feast/` retain the actual bundles, attempts, deployments, traces and summaries |

Reproduce the focused installed workflow and complete gate from the repository:

```sh
ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  uv run --frozen --no-editable pytest -q -m integration \
  --basetemp=/private/tmp/mr05-accept \
  tests/integration/test_candidate_workflow.py

PYTEST_ADDOPTS=--basetemp=/private/tmp/mr05-check \
  ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  make check > logs/mr05/make-check.log 2>&1
```

The final outside-checkout consumer uses the clean wheel-smoke interpreter with
`-I`, copied `candidate_workflow.py` and `decision_study.py` beside the
`research_workflows/` support directory, an absolute output directory, and optional
final argument `feast`. Its worker executes the installed
`applications.explore.command` bytes in the independently locked environment.
No production service or private venue API is used. Existing MR01 source and
MR04 service/restore evidence remains valid because their protocols and stores
are unchanged; new candidate consumption is qualified separately above.

Dependency ownership remains explicit. MR07 owns the delivered intent-evaluation,
atomic checkpoint and serving-pause prerequisite slice; supervision, live inputs,
durable order journal, OMS, risk reservation and reconciliation were still open
at MR05 acceptance. Their dedicated-account increment is recorded under MR07 below.
MR12 owns the carried metric/chart definitions, while runtime dashboards and
alert delivery remain open. MR13 owns the placement-identity slice; its independent
activation envelope, limits and recovery controls remain open. No entire later
milestone, G3–G5 or formal QR onboarding is accepted by this work.

The accepted economic scope remains bounded spot `DecisionStudy` candidates with
named market/reference/non-book inputs. Registry contracts preserve generalized
products and sources, but unimplemented economics reject explicitly. The OKX and
Bitfinex read-only profiles preserve their distinct clocks/representations;
neither is private execution conformance. Actual MR11 venue adapters and evidence
can be registered when available. At MR05 acceptance, runtime modes only emitted
intents; MR07 below adds modeled paper order/account effects while preserving
suppressed executable submission. Component
digests are integrity checks, not MR06 trusted installation. Exact environment
matching is currently required; independent deployable graphs, trusted compatibility,
and the existing QuantLib release restriction remain MR06. Feature generations
are pinned; selecting another version requires an explicit new binding. No
capacity, empirical alpha, live-input fidelity or deployment readiness is claimed.

Reversal removes the new candidate workflows, records and factory exports together;
retain matching wheels/bundles/checkpoints for reproduction. Existing study,
source, feature-store and job record schemas are unchanged. Older runtimes reject
the new candidate schemas and must not silently reinterpret their state.
