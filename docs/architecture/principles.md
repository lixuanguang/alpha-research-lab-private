# Architecture Principles and Dependency Rules

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Package status | Partial under solo bootstrap |
| Accountable owner role | Platform |
| Change risk | R0 |
| Quality gates | QG01, QG13 |

This document makes the repository's architectural constraints reviewable. It is
subordinate to the root blueprint and complements the target topology in
[Monorepo Architecture](README.md), the [platform contracts](contracts.md), and
the [operations controls](operations.md). An ADR may refine a choice but may not
weaken a blueprint invariant or a non-waivable control.

## Governing principles

1. **Preserve point-in-time causality.** Event, receipt, ingestion, knowledge,
   and valid time remain distinct. A decision may consume only information whose
   knowledge time is no later than the decision time.
2. **Keep one strategy kernel.** Research, replay, paper, shadow, canary, and live
   modes inject adapters around the same deterministic decision logic.
3. **Build immutable identities.** Source, toolchain, dependencies, schemas,
   data/model/config/limit references, evidence, and approvals identify a release.
   Mutable tags and workstation artifacts are not deployable identities.
4. **Keep risk independent.** Pre-trade risk, limits, throttles, and kill paths
   must be able to constrain a failed or compromised strategy process.
5. **Make replay deterministic.** Ordering, clocks, random streams, corrections,
   state, and failure behavior are explicit and reproducible.
6. **Require evidence before promotion.** No score, PnL result, or implementation
   claim compensates for a failed mandatory gate.
7. **Observe the economic chain.** Platform, data, model, execution, risk, TCA,
   capacity, and PnL evidence correlate to the exact release.
8. **Use a thin stable waist.** Canonical identifiers, units, time/event schemas,
   the strategy kernel, risk decisions, release evidence, and audit/telemetry are
   stable integration surfaces. Vendors and infrastructure remain behind adapters.
9. **Separate source, runtime, and authority.** The monorepo is one source of
   truth, not one deployable, database, runtime lane, security zone, failure
   domain, or grant of data, deployment, credential, venue, or capital access.
10. **Prefer explicit safe failure.** Invalid, stale, unsupported, unauthorized,
    or incompatible state fails closed, pauses visibly, or uses a registered
    conservative fallback. Silent coercion or continuation is prohibited.
11. **Design for replacement and recovery.** Versioned interfaces, compatibility
    windows, state ownership, reconciliation, and rollback are part of the design,
    not later operational work.
12. **Choose technology from evidence.** Reference technologies establish a
    reviewable baseline. Substitutions require an ADR showing equivalent
    invariants, isolation, reproducibility, security, operations, and evidence.

## Dependency direction

Dependencies point toward stable contracts and policy:

```text
schemas -> core libraries -----------------------------------------------+
              |                                                         |
              +-> data --------------------------------------------------+
              +-> research -> strategy kernel ---------------------------+
              +-> simulation --------------------------------------------+
              +-> portfolio and risk ------------------------------------+
              +-> trading -----------------------------------------------+
                                                                        v
                     strategy and asset packages -> certification suites
                                                                        |
                     platform registry/deploy/telemetry -----------------+
```

The following rules are mandatory:

- The build graph is acyclic; every target declares direct dependencies,
  visibility, owner, supported platform, and generated inputs.
- Schemas and foundational libraries do not depend on research, strategy,
  trading, deployment, notebooks, or composition roots.
- Research may consume production-capable domain libraries. Production code may
  not consume notebooks, ad hoc analysis, research-only approximations, or
  workstation configuration.
- Features and models consume canonical point-in-time data rather than vendor
  APIs. Provider details remain inside connectors and normalizers.
- Portfolio construction emits targets and never places orders. Execution turns
  intent into orders only after external risk decisions.
- Risk and kill controls do not depend on strategy health or strategy-owned
  state. Strategies cannot change their own activation or risk envelope.
- Venue, asset-lifecycle, storage, transport, deployment, and telemetry variants
  implement narrow canonical interfaces and carry conformance evidence.
- Environment differences are validated configuration, not compiled branches.
  Application entrypoints compose owned targets; reusable policy does not live in
  entrypoints.
- Cross-process boundaries use versioned schemas. Native in-process boundaries
  use a narrow reviewed ABI with explicit allocation, lifetime, error, unwinding,
  threading, layout, and version rules.

Automated source-graph enforcement belongs to B01 and B05. Until then, ADR review
and the existing repository checks make these rules normative without claiming
that the future build-policy controls already exist.

## Change rule

A cross-cutting change to build tooling, languages, schemas, storage, process or
service boundaries, message transport, native interoperability, distributed
compute, runtime lanes, deployment, observability, persistence, or event ordering
requires an ADR under the [architecture governance process](governance.md).
Changes also update affected contracts, tests, compatibility, migration, rollback,
operations, and roadmap evidence in the same reviewable sequence.

