# Alpha Research Platform

A monorepo growing toward institutional-grade multi-asset, multi-strategy research,
production trading and monitoring. The implemented Python libraries cover
instrument identity, venue calendars, financial units, exact serialization,
event provenance, an authored reference catalog, bounded Tardis/Binance
decoding, historical acquisition, saved-row reading, eligibility selection and
validated dataset publication/reopening with explicit quality scope. Native
Bitfinex and OKX order-book acquisition/replay, point-in-time trade queries and
configured EDA, retained experiment attempts, temporal split admission and versioned
observed-price feature/label studies are also available. Exact model construction,
evaluation and local ClearML integration are implemented with verified upstream
source admission; see the [model contract](../src/research/models/README.md). Empirical causal
dataset acceptance, simulation, accounting, risk enforcement, execution and
deployment remain future work. Start with the [QR implementation guide](../examples/README.md)
for current notebooks and the full research-to-production journey, with planned
activities clearly distinguished from implemented workflows.
One reproducible strategy baseline is the first delivery target; shared research,
portfolio infrastructure and independently operated strategies are the destination.

The [P1 experiment specification](research/p1-baseline.md) selects Binance public
BTCUSDT spot-trade archives and a fixed one-minute positive-return baseline.
The permitted saved hour has passed dataset publication with exploratory degraded
scope. Historical eligibility, coverage and revision-availability evidence remain
unresolved; no empirical strategy result is claimed.

The [platform infrastructure roadmap](roadmap/README.md) begins with researcher
dataset access. It owns future capability delivery, dependencies and acceptance.
Current capabilities are documented by function; the QR guide owns usage and the
research program owns methodology. Source ownership is documented in architecture.
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

Use standard GIL-enabled CPython 3.14.7 and uv 0.12.7 on macOS arm64 or Linux
x86_64, then synchronize the single lock:

```sh
uv python install
uv sync --frozen
```

Exact interpreter and dependency inputs live in
[pyproject.toml](../pyproject.toml), [uv.lock](../uv.lock), and
[.python-version](../.python-version). Git and Make support repository checks.
Development tooling is installed through the
`dev` dependency group; the runtime package has no dependency on governance or
repository policy files.

[Makefile](../Makefile) provides the standard commands. Hosted CI runs `make
source-check` and isolated runtime wheel installation on Linux and macOS. During
local development, run the checks and tests relevant to the changed behavior and
record what ran. `make check` remains the complete check entry point.

| Command | Use |
| --- | --- |
| `alpha-inspect-fixture --help` | Inspect one saved trade frame through an explicitly configured job |
| `alpha-acquire --help` | Acquire and resume supported historical source partitions |
| `alpha-dataset --help` | Publish validated saved acquisitions and inspect an explicit snapshot ID |
| `alpha-collect --help` | Capture supported live market-data sources within their declared source contracts |
| `make check` | Complete source checks and isolated wheel smoke |
| `make format`, `make format-check`, `make lint` | Python formatting and linting |
| `make typecheck` | Strict typing across source, tools, tests and owned native stubs |
| `make build`, `make wheel-smoke` | Build the runtime wheel; verify installation without governance |
| `make test` | Correctness and integration tests, excluding performance cases |
| `make integration-test`, `make performance-test` | Explicit integration or performance selection |
| `make engineering-standards-check` | Protected typing, import and docstring rules |
| `make architecture-check` | Local links and headings in `docs/**/*.md`; component READMEs require explicit inclusion |
| `make dependency-admission-check`, `make dependency-audit` | Frozen dependency sources, retained restrictions and vulnerability audit |
| `uv run --frozen alpha-governance-artifacts release-check` | Report release blockers; currently always fails closed |
| `make ci-secrets-check`, `make security` | Secret/private-key scanning and Bandit |
| `make governance-check` | Group the retained clarity, dependency and link checks |

For selected tests use:

```sh
uv run --frozen --no-editable pytest -q <test-paths>
```

The [architecture guide](architecture/README.md) explains the source and installed-package
checks. Runtime consumers can install the built wheel with its declared domain
dependencies; development tools are absent from the runtime distribution.
This installation boundary does not override
the QuantLib release restriction.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Architecture](architecture/README.md) | Current architecture and implemented domain contracts |
| [Platform design](architecture/platform-design.md) | Planned shared modules, runtime lanes, contracts, recovery and scaling decisions |
| [Development workflow](governance/workflow.md) | Implementation, validation and founder activation rules |
| [Operations runbook](governance/operations.md) | Security, monitoring, stop and recovery requirements for a future deployment |
| [Platform infrastructure roadmap](roadmap/README.md) | One backlog for reusable capabilities, MR dependencies, functional ownership and acceptance |
| [QR implementation guide](../examples/README.md) | Research activities: data selection/onboarding, features/labels, models/rules, backtesting, candidate promotion and monitoring; current versus planned support |
| [Frozen P1 experiment](research/p1-baseline.md) | Selected sample, strategy, timing, cost assumptions and experiment acceptance requirements |
| [Research program](roadmap/research-program.md) | Research workstreams, implementation outputs, costed comparisons and holdout discipline |
| [Data sources](data_source/README.md) | Sources by asset class and data type, historical coverage, access limits and dated verification evidence |
| [Engineering guide](coding_standards/README.md) | Enforced clarity and numerical engineering requirements |
| [Instrument identity](architecture/instrument-identity.md), [venue calendars](architecture/venue-calendar.md), [financial units](architecture/financial-units.md) | Implemented domain contracts and golden datasets |
| [Data contracts](data/contracts.md), [point-in-time semantics](data/point-in-time-semantics.md), [data library](../src/market_data/README.md) | Implemented events, decoding, provenance and current construction example |

The [data command reference](../src/market_data/README.md) and
[collector guide](data/l3-collectors.md) own command usage and limits. Backtesting,
paper trading, deployment, activation and trading stop commands remain planned.
Keep actual release identities, data provenance and unresolved dependency
evidence; no current result grants live readiness.
