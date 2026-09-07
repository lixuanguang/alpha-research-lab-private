# Alpha Research Platform

A monorepo growing toward institutional-grade multi-asset, multi-strategy research,
production trading and monitoring. The implemented Python domain libraries cover
instrument identity, venue calendars and financial units. Data ingestion,
simulation, risk enforcement, execution and deployment remain future work.
One reproducible strategy baseline is the first delivery target; shared research,
portfolio infrastructure and independently operated strategies are the destination.

The [platform roadmap](roadmap/README.md) sets phased deliverables and evidence.
The [platform design](architecture/platform-design.md) preserves intended module
boundaries, interfaces, runtime lanes and scaling choices. Technical correctness,
reproducibility and trading safety accompany the features that need them. Team
ownership, independent approvals and organizational controls are the lowest
priority workstream, introduced as actual contributors and operators join.

The [development workflow](governance/workflow.md) owns development and founder
activation decisions. QuantLib 1.43 remains
restricted to isolated development/CI through 2026-10-04 because its
source-to-wheel binding is unverified; artifact release remains blocked. See the
[dependency decision](architecture/README.md#dependency-and-release-boundaries).

## Development environment

Install Python 3.12.14 and uv 0.12.7, then synchronize the single lock:

```sh
uv sync --frozen
```

Exact interpreter and dependency inputs live in
[pyproject.toml](../pyproject.toml), [uv.lock](../uv.lock), and
[.python-version](../.python-version). Git and Make support repository checks.
The dependency check also needs Cosign 3.1.3 for retained native attestations;
hosted source validation installs it. Development tooling is installed through the
`dev` dependency group; the runtime package has no dependency on governance or
repository policy files.

[Makefile](../Makefile) provides the standard commands. Hosted CI runs `make
source-check` and isolated runtime wheel installation on Linux and macOS. During
local development, run the checks and tests relevant to the changed behavior and
record what ran. `make check` remains the complete check entry point.

| Command | Use |
| --- | --- |
| `make check` | Complete source checks and isolated wheel smoke |
| `make format`, `make format-check`, `make lint` | Python formatting and linting |
| `make typecheck` | Strict typing across source, tools, tests and owned native stubs |
| `make build`, `make wheel-smoke` | Build the runtime wheel; verify installation without governance |
| `make test` | Correctness and integration tests, excluding performance cases |
| `make integration-test`, `make performance-test` | Explicit integration or performance selection |
| `make engineering-standards-check` | Protected typing, import and docstring rules |
| `make architecture-check` | Local documentation links |
| `make dependency-admission-check`, `make dependency-audit` | Frozen dependency sources, retained restrictions and vulnerability audit |
| `make artifact-supply-chain-check` | Retained artifact/release boundary |
| `make ci-secrets-check`, `make security` | Secret/private-key scanning and Bandit |
| `make governance-check` | Group the retained clarity, dependency, artifact and link checks |

For selected tests use:

```sh
uv run --frozen --no-editable pytest -q <test-paths>
```

The [architecture guide](architecture/README.md) explains the source and installed-package
checks. Runtime consumers can install the built wheel with its declared domain
dependencies; development tools and the retired `alpha-research-ci` command are
absent from the runtime distribution. This installation boundary does not override
the QuantLib release restriction.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Cleanup plan](cleanup/README.md) | Cleanup scope, decisions and measured validation |
| [Architecture](architecture/README.md) | Current architecture and implemented domain contracts |
| [Platform design](architecture/platform-design.md) | Planned shared modules, runtime lanes, contracts, recovery and scaling decisions |
| [Development workflow](governance/workflow.md) | Implementation, validation and founder activation rules |
| [Operations runbook](governance/operations.md) | Security, monitoring, stop and recovery requirements for a future deployment |
| [Platform roadmap](roadmap/README.md) | Phased multi-asset, multi-strategy research, production, monitoring and scaling work |
| [Research program](roadmap/research-program.md) | Research workstreams, implementation outputs, costed comparisons and holdout discipline |
| [Engineering guide](coding_standards/README.md) | Enforced clarity and numerical engineering requirements |
| [Instrument identity](architecture/instrument-identity.md), [venue calendars](architecture/venue-calendar.md), [financial units](architecture/financial-units.md) | Implemented domain contracts and golden datasets |

Data ingestion, backtesting, paper/replay, deployment, activation, monitoring and
stop commands are planned. Follow the roadmap and add commands here as those
capabilities are implemented and tested. Keep actual release identities, data
provenance and unresolved dependency evidence; no current result grants live
readiness.
