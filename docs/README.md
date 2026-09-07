# Alpha Research Platform

A Python workspace for quantitative research. The implemented domain libraries
cover instrument identity, venue calendars, and financial units. Data ingestion,
simulation, risk enforcement, order execution, and production deployment remain
future work. The first delivery target is one reproducible strategy baseline with
explicit data availability, realistic costs, and accounting.

The [development workflow](governance/workflow.md) owns development and founder
activation decisions. The institutional blueprint and package roadmap are historical
planning material, not prerequisites for implementation. QuantLib 1.43 remains
restricted to isolated development/CI through 2026-10-04 because its
source-to-wheel binding is unverified; artifact release remains blocked. See the
[dependency decision](architecture/dependency-admission.md).

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

The [CI guide](architecture/ci-policy.md) explains the source and installed-package
checks. Runtime consumers can install the built wheel with its declared domain
dependencies; development tools and the retired `alpha-research-ci` command are
absent from the runtime distribution. This installation boundary does not override
the QuantLib release restriction.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Cleanup plan](cleanup/README.md) | Cleanup scope, decisions and measured validation |
| [Architecture](architecture/README.md) | Architecture and implemented domain contracts |
| [Development workflow](governance/workflow.md) | Implementation, validation and founder activation rules |
| [Research program](roadmap/research-program.md) | Research protocol and remaining historical planning context |
| [Coding standards](coding_standards/README.md) | Enforced clarity and numerical engineering requirements |
| [Financial units](architecture/financial-units.md) | Exact units and native convention boundaries |

Keep actual release identities, data provenance and unresolved dependency evidence.
Synthetic historical evidence and the old package catalog confer no current
approval or live readiness. Documentation consolidation and the practical backlog
are the next cleanup slice.
