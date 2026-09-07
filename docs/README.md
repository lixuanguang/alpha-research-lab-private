# Alpha Research Platform

Implementation workspace for a multi-asset quantitative platform covering
research, simulation, portfolio/risk, trading, and controlled deployment. The
[implementation blueprint](../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
defines the target requirements; the docs below describe repository contracts and
delivery order.

## Current status

The repository has governance and build tooling, plus the first domain contracts:
instrument identity, venue calendars, and financial units (C01-C03). It does not
yet implement the data platform, simulator, independent risk gateway, OMS/EMS, or
production deployment. The proposed first workload is a digital-asset
factor-residual strategy under its separate certification package.

The [generated program status](governance/program-status.md) shows demonstrated
implementation, the next technical package, retained findings and any active
handover. The [development workflow](governance/workflow.md) separates engineering
completion from institutional acceptance and operation authority. QuantLib 1.43
has a development admission expiring 2026-10-04 with unverified source-to-wheel
binding; B08 artifact release remains blocked. See
[financial units](architecture/financial-units.md) for the boundary.

## Development environment

With uv and Bazelisk available, install the locked environment:

```sh
uv sync --frozen
```

Exact versions live in [pyproject.toml](../pyproject.toml),
[uv.lock](../uv.lock), [.python-version](../.python-version),
[.bazelversion](../.bazelversion), and [MODULE.bazel](../MODULE.bazel).
For a clean machine, follow the
[Nix bootstrap guide](architecture/clean-machine-environment.md#documented-prerequisites-and-bootstrap).

[Makefile](../Makefile) is the root command interface. Bazel is the default build
backend; the frozen-uv path is retained for rollback. Governance targets invoke
installed `alpha-governance-*` commands without ambient `PYTHONPATH`.

| Command | Use |
| --- | --- |
| `make format`, `make format-check`, `make lint`, `make typecheck` | Python formatting and static checks |
| `make build`, `make test` | Build the representative Bazel graph; run focused hermetic-build tests |
| `make ci-fast CI_BASE_REF=<base> CI_HEAD_REF=HEAD` | Validate affected targets and reverse dependencies |
| `make check` / `make ci-full` | Authoritative full validation; also the default for bare `make` |
| `make rollback-check` | Complete frozen-uv validation, integration tests, smoke import, and package build |
| `make integration-test`, `make performance-test` | Dedicated integration and non-blocking performance checks |

Use the focused checks while changing the corresponding contract:

| Command | Contract |
| --- | --- |
| `make architecture-check` | ADR metadata and local documentation links |
| `make governance-check`, `make program-status` | Validate shared policies; render program status after a state change |
| `make ownership-check`, `make topology-check` | Owners, source coverage, dependency direction, and visibility |
| `make change-risk-check`, `make evidence-check` | Change classification and SHA-bound evidence |
| `make inventory-check` | Resource inventory and lineage |
| `make security-controls-check` | Threat model and control evidence |
| `make program-governance-check` | Package dependencies, readiness, and KPIs |
| `make engineering-standards-check` | Language admission and static-quality policy |
| `make dependency-admission-check` | Dependency sources, digests, locks, licenses, and platforms |
| `make dependency-audit` | Admitted pip-audit signal and vulnerability decisions |
| `make artifact-supply-chain-check` | SBOM, provenance, signing, publication, and consumption |
| `make ci-policy-check`, `make ci-secrets-check`, `make ci-schema-check` | CI policy, tracked-source secrets, and schema compatibility |
| `make remote-execution-policy-check` | Remote trust, sharding, resource, and fallback policy |

Remote execution commands and their protected-context prerequisites are documented
in [remote execution](architecture/remote-execution.md). See the
[build graph](architecture/hermetic-build-graph.md) and
[CI policy](architecture/ci-policy.md) for target coverage and lane behavior.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Solo-maintainer cleanup plan](cleanup/README.md) | Repository audit and proposed simplification of docs, code, governance, CI, and tests |
| [Architecture](architecture/README.md) | System overview and links to build and domain contracts |
| [Development workflow](governance/workflow.md) | The one active implementation, evidence, validation, and handover workflow |
| [Program status](governance/program-status.md) | Generated implementation, governance, readiness, and finding view |
| [Implementation roadmap](roadmap/README.md) | 96 packages, dependencies, milestones, and solo-bootstrap rules |
| [Research program](roadmap/research-program.md) | Empirical stages for the first strategy candidate |
| [Coding standards](coding_standards/README.md) | Shared rules and language guides |
| [Repository charter](governance/repository-charter.md) | Scope and external-system boundaries |
| [Domain ownership](governance/domain-ownership.md) | Accountable owners and review policy |
| [Change-risk classification](governance/change-risk-classification.md) | R0-R4 gates, reviewers, rollout, and retention |
| [Merge evidence](governance/merge-evidence.md) | MR fields, evidence manifests, and validation |
| [Resource inventory](governance/resource-inventory.md) | Versioned resources, dependencies, and lineage |
| [Threat model](governance/threat-model.md) | Security controls, trust boundaries, and jurisdiction profiles |
| [Program governance](governance/program-governance.md) | Readiness registry, KPI definitions, and dashboard |

Maintain each rule in its owning contract and link to it from overview pages.
Exact policy values belong in the adjacent TOML records; retained evidence belongs
with its manifest. Completed migration diaries remain available in Git history.

## Working agreement

Follow the [development workflow](governance/workflow.md). Preserve the
[architecture principles](architecture/principles.md), target ownership, and
compatibility. Cross-cutting decisions follow the [ADR process](architecture/governance.md).
