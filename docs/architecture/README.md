# Monorepo Architecture

This is the target architecture under the
[implementation blueprint](../../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf).
Current implementation status is in the [documentation home](../README.md).
The [principles](principles.md) define the invariants and permitted dependency
direction; the [roadmap](../roadmap/README.md) records historical package
provenance and the current research direction.

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

The control plane manages experiments, evidence, artifacts, configuration,
promotion, deployment, audit, and monitoring. The data plane retains raw inputs,
canonical events, temporal master data, point-in-time snapshots, corrections,
lineage, and bounded-freshness serving.

Batch/HPC supports research and batch production. Standard live services use an
orchestrator; measured latency needs may justify immutable packages on controlled
hosts. The hot path excludes general-purpose control-plane dependencies and emits
bounded telemetry. All lanes share contract, evidence, independent-risk,
activation, audit, rollback, and SLO requirements.

## Stable integration surface

Adapters isolate asset lifecycles, venue protocols, storage, transport, and runtime
choices behind canonical identifiers/units/time/events, the strategy kernel,
independent risk decisions, release/evidence manifests, and audit/telemetry schemas.
The [platform contracts](contracts.md) define those semantic boundaries.

| Mode | Capital | Data and required parity |
| --- | --- | --- |
| Unit/golden | None | Deterministic fixtures with exact or declared numeric oracles |
| Research | None | Immutable PIT snapshots, shared kernel and component manifests |
| Replay | None | Canonical event logs with decision/state trace parity |
| Paper | None | Live data, controlled paper execution, full lifecycle and recovery |
| Shadow | None | Live data, orders suppressed, risk decisions and trace comparison |
| Canary | Bounded | Live venue under a signed minimal activation envelope |
| Production | Approved | Full certified envelope and controls |

Mode differences are injected adapters and validated configuration. Deployment and
activation remain separate; a process cannot trade until independently authorized.

## Repository boundaries

Organize source by economic or platform responsibility: schemas/core, data,
research, simulation, portfolio/risk, trading, platform services, assets, and
strategies. Tests, environments, and tools support those owned targets. Populate
directories only when their owning package is implemented.

The repository keeps only implemented domain packages and the development
tooling that validates them. Bulk datasets, trial outputs, compiler
outputs, deployable artifacts, and secrets stay outside Git. Git retains source,
schemas, manifests, synthetic fixtures, and policies.

## Build and domain contracts

Each contract contains its interfaces, validation, rollback, evidence, and open
findings. Adjacent TOML records provide machine-readable policy where applicable.

| Package | Contract |
| --- | --- |
| B02 | [Pinned hermetic build graph](hermetic-build-graph.md) (historical) |
| B03 | [Clean-machine developer environment](clean-machine-environment.md) (historical) |
| B04 | [Engineering standards](engineering-standards.md) |
| B05 | [Source validation and CI policy](ci-policy.md) |
| B06 | [Remote execution, sharding, and fallback](remote-execution.md) (retired) |
| B07 | [Dependency admission](dependency-admission.md) |
| B08 | [Artifact supply chain](artifact-supply-chain.md) |
| C01 | [Instrument identity and temporal symbology](instrument-identity.md) |
| C02 | [Venue calendars and market status](venue-calendar.md) |
| C03 | [Financial units and conventions](financial-units.md) |

## Decisions and operations

- [Principles and dependency rules](principles.md): mandatory architectural constraints.
- [Architecture decisions](governance.md) and [ADR notes](decisions/README.md):
  technology choices, alternatives, consequences, and reversal.
- [Platform contracts](contracts.md): data, research/model, accounting, execution,
  and asset-extension requirements.
- [Operations boundary](operations.md): current implementation limits and the
  path to a real release and activation.

Reference technologies are documented with an ADR when the choice is expensive
to reverse and pass the dependency checks that apply to the actual consumer.
Build once and promote immutable artifacts by digest; releases and
rollback bind code, model, data/schema references, configuration, limits, state,
and evidence under the [operations runbook](../governance/operations.md).
