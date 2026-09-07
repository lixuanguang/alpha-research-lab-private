# Alpha Research Platform

Implementation workspace for a multi-asset quantitative platform covering
research, simulation, portfolio/risk, trading, and controlled deployment. The
[implementation blueprint](../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
defines the target requirements; the docs below describe repository contracts and
delivery order.

## Current status

The repository has the first domain contracts: instrument identity, venue
calendars, and financial units (C01-C03). It does not yet implement the data
platform, simulator, independent risk gateway, OMS/EMS, or production
deployment. The proposed first workload is a digital-asset factor-residual
strategy under its separate certification package. The former Bazel, Nix,
remote-execution, and custom affected-target CI surfaces are retained only as
historical records while the active path uses uv and one source check.

The [generated program status](governance/program-status.md) shows demonstrated
implementation, the next technical package, retained findings and any active
handover. The [development workflow](governance/workflow.md) separates engineering
completion from institutional acceptance and operation authority. QuantLib 1.43
has a development admission expiring 2026-10-04 with unverified source-to-wheel
binding; B08 artifact release remains blocked. See
[financial units](architecture/financial-units.md) for the boundary.

## Development environment

Install the locked environment with Python 3.12.14 and uv:

```sh
uv sync --frozen
```

Exact Python, uv, and dependency versions live in
[pyproject.toml](../pyproject.toml), [uv.lock](../uv.lock), and
[.python-version](../.python-version). A clean checkout needs only those pinned
inputs and a working uv installation for environment synchronization. `make check`
also needs Git, GNU Make, and Cosign 3.1.3; hosted CI installs the pinned Cosign
release.

[Makefile](../Makefile) is the root command interface. `make check` is the
required source and policy validation command; focused commands are optional
while developing. Governance targets invoke installed `alpha-governance-*`
commands without ambient `PYTHONPATH`.

| Command | Use |
| --- | --- |
| `make check` | Required source, policy, test, and package validation |
| `make format`, `make format-check`, `make lint`, `make typecheck` | Optional focused Python formatting and static checks |
| `make build`, `make test` | Optional local package build and default tests |
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
| `make ci-secrets-check` | Tracked-source secrets and private-key scanning |

Use `uv run --frozen --no-editable pytest -q <test-paths>` for focused tests. The
[CI policy](architecture/ci-policy.md) documents the retained source check and
secret scanner. The [hermetic build graph](architecture/hermetic-build-graph.md),
[clean-machine environment](architecture/clean-machine-environment.md), and
[remote-execution policy](architecture/remote-execution.md) remain historical
records and do not add active setup or check prerequisites.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Solo-maintainer cleanup plan](cleanup/README.md) | Repository audit and proposed simplification of docs, code, governance, CI, and tests |
| [Architecture](architecture/README.md) | System overview and links to current domain contracts |
| [Development workflow](governance/workflow.md) | The one active implementation, evidence, validation, and handover workflow |
| [Program status](governance/program-status.md) | Generated implementation, governance, readiness, and finding view |
| [Implementation roadmap](roadmap/README.md) | 96-package implementation roadmap and current research direction |
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
