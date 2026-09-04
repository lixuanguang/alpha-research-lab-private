# Monorepo Architecture

## Purpose and status

This document defines the target architecture and dependency model for the
institutional quantitative monorepo. It is subordinate to the
[implementation blueprint](../../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
and describes the target state. The first implemented thin-waist subsets are C01
[canonical instrument identity](instrument-identity.md) and C02
[venue calendars](venue-calendar.md); the remaining architecture is not implied to
exist in the bootstrap repository.

Detailed semantic boundaries are in [contracts.md](contracts.md). Testing,
operations, security, and promotion controls are in
[operations.md](operations.md). Delivery order is in the
[implementation roadmap](../roadmap/README.md).

Normative design principles and dependency rules are in
[principles.md](principles.md). Cross-cutting choices follow the
[architecture governance process](governance.md) and remain traceable in the
[decision log](decisions/README.md).

The design is an independent target architecture informed by public engineering,
SRE, software-supply-chain, model-risk, and algorithmic-trading principles. It is
not a reconstruction of any firm's proprietary systems.

## Architectural thesis

Use one source of truth for code, contracts, lineage, ownership, and change
governance while maintaining multiple deployables, security zones, performance
profiles, runtime lanes, and failure domains. Monorepo does not mean monolith.

The platform is defined by seven invariants:

1. Point-in-time causality.
2. One shared strategy kernel across research, replay, paper, shadow, canary, and
   live modes.
3. Immutable, signed release identity.
4. Independent risk controls outside the strategy process.
5. Deterministic replay of market, reference, order, fill, state, and control
   events.
6. Complete mandatory evidence before promotion.
7. Correlated monitoring of the full technical and economic chain.

## Control plane, data plane, and runtime lanes

```text
                            control plane
       research SDK | evidence/registry | MR/CI | promotion | monitoring
                                  |
                                  v
                              data plane
  sources -> immutable raw -> canonical events/master -> PIT lakehouse
                                                    -> online serving/event bus
                                  |
                                  v
                             runtime lanes
         batch/HPC | standard live services | low-latency controlled hosts
                                  |
                    independent risk gateway
                                  |
                       OMS/EMS and venue adapters
```

- The **control plane** manages experiments, evidence, artifacts, configuration,
  promotion, deployment, audit, and monitoring.
- The **data plane** preserves raw inputs, canonical events, temporal master data,
  point-in-time snapshots, corrections, lineage, and bounded-freshness serving.
- The **batch/HPC lane** supports research and batch production.
- The **standard live lane** supports event-driven services, normally through
  Kubernetes or an equivalent orchestrator.
- The **low-latency lane** uses immutable packages and tightly controlled hosts
  when measurements justify it. The hot path excludes general-purpose
  control-plane dependencies but still reports the same release identity, consumes
  compatible schemas, obeys external risk, and emits bounded audit/telemetry.

Schedulers, security zones, packaging, and performance budgets may differ by lane.
Contracts, evidence, independent risk, activation envelopes, audit, rollback, and
SLO requirements do not.

## The thin waist

The stable integration surface consists of:

1. Canonical identifiers, units, timestamps, and event contracts.
2. A strategy-kernel interface separating features, forecasts, targets, and
   execution intent.
3. An independent risk-decision contract.
4. A release-manifest and evidence schema.
5. Correlated telemetry and audit-event schemas.

Asset-specific lifecycles, venue protocols, storage engines, transports, and
runtime implementations evolve behind adapters. They may not contaminate this
stable surface with private symbol maps, infrastructure assumptions, or compiled
environment branches.

## Permitted dependency direction

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

The build graph must be acyclic and enforce these restrictions:

- Schemas and foundational libraries never depend on research, strategy,
  trading, or deployment packages.
- Production strategy packages never import notebooks, ad hoc analysis folders,
  research-only approximations, or workstation configuration.
- Features and models consume canonical point-in-time data, not vendor APIs.
- Portfolio construction produces targets; it does not place orders.
- Independent risk and kill paths do not depend on the strategy process being
  healthy.
- Venue-specific behavior is isolated behind certified adapters.
- Asset-specific accounting and lifecycle implementations conform to canonical
  interfaces and carry golden fixtures.
- Environment-specific configuration is validated data, not compiled conditional
  logic.
- Application entrypoints compose targets; reusable economic logic does not live
  in composition roots.

## Runtime modes and parity

| Mode | Capital | Data/clock | Required relationship |
| --- | --- | --- | --- |
| Unit/golden | None | Tiny fixture, deterministic clock | Exact or declared numeric oracle |
| Research | None | Immutable PIT snapshot, simulated clock | Shared kernel and component manifests |
| Deterministic replay | None | Canonical event log, replay clock | Decision/state trace parity |
| Paper | None | Live data, controlled paper execution | Full order lifecycle and recovery |
| Shadow | None | Live data, executable orders suppressed | Shared kernel, risk decisions, trace comparison |
| Canary | Bounded | Live data and venue | Signed minimal activation envelope |
| Production | Approved | Live data and venue | Full certified envelope and controls |

Mode differences belong in injected adapters and configuration. Deployment and
activation are separate: a deployed process remains unable to trade until an
independently authorized activation envelope is applied.

## Reference repository layout

```text
/
  MODULE.bazel
  .gitlab-ci.yml             # or forge-equivalent governed pipelines
  CODEOWNERS
  docs/
    architecture/
    runbooks/
    controls/
  schemas/
    identity/ market/ reference/ order/ fill/ position/ risk/ audit/
  core/
    time/ ids/ units/ numerics/ serialization/ randomness/ telemetry/
  data/
    contracts/ connectors/ normalization/ quality/ point_in_time/
    lineage/ catalog/ replay/ corrections/
  research/
    sdk/ datasets/ features/ labels/ experiments/ models/ reports/
  simulation/
    engine/ market_models/ fills/ costs/ scenarios/ accounting/
  portfolio/
    forecasts/ optimizers/ constraints/ allocation/
  risk/
    models/ pretrade/ limits/ stress/ liquidity/ reconciliation/
  trading/
    strategy_kernel/ runtime/ oms/ ems/ fix/ venue_adapters/ drop_copy/
  platform/
    registry/ promotion/ config/ deploy/ observability/ secrets/
  assets/
    equities/ futures/ options/ fx/ rates/ credit/ digital_assets/
  strategies/
    cross_sectional/ stat_arb/ market_making/ execution/ volatility/
  tests/
    unit/ property/ golden/ replay/ scenario/ integration/ load/ chaos/
  environments/
    dev/ ci/ replay/ staging/ paper/ shadow/ canary/ production/
  tools/
    cli/ codegen/ migrations/ evidence/ release/
```

This is the target created by B01 and later packages, not a request to create
empty directories. B01b moved governance implementation from the bootstrap
`src/alpha_research/` distribution into the owned `tools/governance` target and
left only compatibility facades in the former paths. Bulk datasets, trial
outputs, compiler outputs, deployable artifacts, and secrets stay outside Git;
Git retains schemas, manifests, build definitions, synthetic fixtures, and
policies.

[B01's governed repository topology](repository-topology.md) registers and checks
canonical tools, compatibility facades, engineering tests, and B02 build-test
sources. B01c enforces it through root, pre-commit, hosted-CI, A06, and A08
consumers. [B02](hermetic-build-graph.md) adds the current pinned build graph and
[B03](clean-machine-environment.md) adds the locked clean-machine development
shell. [B04](engineering-standards.md) adds the current language and static-quality
policy, checker, and property/state-machine target. [B05](ci-policy.md) adds the
affected/reverse-dependency fast lane and authoritative full merged-result lane;
[B07](dependency-admission.md) controls dependencies, and
[B08](artifact-supply-chain.md) controls whole-artifact evidence and consumption.
[C01](instrument-identity.md) adds canonical instrument identity and
[C02](venue-calendar.md) adds the versioned venue/session/calendar boundary. They
do not create the remaining target tree, production artifact registry, data
service, live calendar authority, or runtime.

## Build and reproducibility architecture

The target build is a pinned, hermetic Bazel graph for Python, justified C++ and/or
Rust, Protobuf, SQL generation, and documentation. B02 implements that graph for
the current Python, governance, documentation, SQL, and test-only Protobuf targets;
there is no native source to justify a native target yet. B03's Nix flake supplies
the supported reproducible prerequisite boundary and retains the uv lock as a
transitional resolution input to the current Bazel Python graph. B04 keeps C/C++
and Rust dormant and enforces the exact Python standards against that graph. B05
uses the graph for affected-owner/reverse-dependency selection and complete
merged-result validation while preserving the frozen-uv rollback.

The build system must:

- Declare source, toolchain, dependencies, generated inputs, environment, target
  platform, visibility, and ownership explicitly.
- Sandbox actions and reject undeclared workstation inputs or runtime package
  installation.
- Produce content-addressed artifacts and reproducible generation outputs.
- Run affected-target tests for speed and full merged-result/merge-train testing
  for integration safety.
- Support authenticated remote cache/execution only after cache isolation,
  correctness, deterministic seeds, and local fallback are demonstrated.
- Emit provenance, SPDX-compatible SBOMs, checksums, test evidence, signatures,
  and policy-verifiable attestations.

Cross-process APIs use versioned schemas, normally Protobuf for contracts and
Arrow/Parquet for analytical interchange. In-process Rust/C++ integration uses a
narrow reviewed ABI with explicit allocation, lifetime, errors, unwinding,
threading, layout, and version rules. Cross-language implementations share golden,
differential, and compatibility suites.

## Data and platform reference architecture

Reference technologies include an Iceberg-style point-in-time lakehouse,
Kafka/Redpanda-class event transport, MLflow-class registry, OpenLineage-class
lineage, Kubernetes/GitOps for standard services, immutable bare-metal deployment
for ultra-low latency, and OpenTelemetry with Prometheus/Grafana-class monitoring.
Alternatives are permitted only when they preserve the corresponding invariants,
evidence, SLOs, and failure controls.

No single database or transport is expected to serve research, online decisions,
order routing, audit, and monitoring equally well.

## Immutable release and activation model

A release is a signed manifest containing at least:

- Repository commit, reviewed MR identifiers, build platform, toolchain,
  dependency lock, provenance, SBOM, signature, and artifact digest.
- Model, feature graph, dataset snapshot references, schema versions, random-state
  policy, and validation report.
- Configuration and limit digests plus environment, accounts, venues, assets,
  universe, capital, and schedule.
- Required service versions and compatibility range.
- Dashboards, alerts, runbooks, rollback target, kill procedure, evidence bundle,
  waivers, and approvals.

Build once and promote by digest. Mutable tags and workstation artifacts are not
deployable identities. Every live process continuously reports its release and
includes it in decision, risk, order, fill, audit, and telemetry events.

Rollback covers binary, model, feature graph, configuration, limits, schema
compatibility, and state. Schema/state changes use expand-migrate-contract,
dual-read/write when required, and explicit backward-compatibility windows.

## Ownership and architecture decisions

Every package, schema, dataset, model, strategy, service, limit, venue adapter,
environment, and release has an accountable owner and criticality. Source access,
data entitlement, deployment authority, credentials, and capital permissions are
separate.

Create an ADR before a cross-cutting choice involving build tooling, languages,
schemas, storage, a service/process split, message transport, native boundary,
distributed compute, deployment substrate, observability, persistence, or event
ordering. Record the measured problem, alternatives, decision, consequences,
migration, rollback, owners, review date, and reversal plan.

The A02 framework, lifecycle, deprecation policy, exception process, template,
initial proposals, and deferred solo-bootstrap findings are maintained through
the [architecture governance process](governance.md). Proposed ADRs guide bounded
implementation but are not accepted until their required commit-bound approval
evidence exists.

## Public references

- [Why Google stores billions of lines of code in one repository](https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)
- [Bazel hermeticity](https://bazel.build/basics/hermeticity)
- [Nix and NixOS](https://nixos.org/)
- [Jane Street code review](https://www.janestreet.com/tech-talks/janestreet-code-review/)
- [Jane Street reproducible Python environments](https://blog.janestreet.com/building-reproducible-python-environments-with-xars/)
- [Hudson River Trading engineering](https://www.hudsonrivertrading.com/work-at-hrt/)
- [Citadel Securities engineering](https://www.citadelsecurities.com/careers/engineering/)

References inform the design but do not override the blueprint, effective venue
rules, legal requirements, measured behavior, or approved internal policy.
