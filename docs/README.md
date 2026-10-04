# Alpha Research Platform

After the research and paper-trading infrastructure is built and accepted at MR17,
quant research starts with an economic question: can an observable market state improve
a trading decision after costs, delay and risk? The planned agenda investigates
one execution venue and a narrow product/instrument scope, beginning with an
opportunity map and pressure/replenishment hypotheses.

Start with the [research guide](../examples/README.md) and
[ranked agenda](../examples/research-agenda.md). The four study workbooks cover
economic feasibility, selective liquidity-taking, liquidity shocks and selective
liquidity provision. They specify experiments and summarize supplied study
outputs; they do not contain empirical findings or run those strategies.

The [research delivery milestones](roadmap/research-program.md#post-infrastructure-research-milestones)
are research readiness, an executable end-to-end prototype, and an evidence-backed
decision. They own QR-01–QR-18 and are all **planned, not started**. Only surviving
candidates continue to forward validation and a deployment recommendation.

The platform currently supports bounded local research from retained market data
to exact spot simulation, model studies and reports. The
[package guides](architecture/README.md) describe these interfaces. The
[remaining roadmap](roadmap/README.md#delivery-order-and-dependencies)
owns completion of the OKX/Bitfinex spot stack before QR onboarding, including
research extension points, runtime, monitoring and capacity qualification.
QD's initial delivery ends at paper-trading capability. Live trading is
[KIV pending profitable OOS and forward paper evidence](roadmap/README.md#live-trading-kiv-and-reconsideration),
net of transaction costs, slippage and applicable digital-asset gas fees.
Candidate bundles load the same rule/model components into replay and local
paper/shadow runtime, including versioned Feast features and native public books.
The durable OMS preserves partial orders, pending exposure and restart state.
Paper economics do not qualify venue execution; no live trading service is activated.

The [architecture](architecture/README.md) owns package boundaries;
[research methodology](roadmap/research-program.md) owns evaluation and trial
records. Keep empirical research priorities separate from infrastructure delivery.

The [saved L2 command](research/l2-book-backtest.md) provides bounded reproducible
simulation. It does not establish empirical source coverage or a profitable strategy.

Every admitted package has a verified source binding, so no wheel-only exception
blocks release. See [dependency admission](architecture/dependency-admission.md#repository-owned-day-counts)
and the [release workflow](governance/workflow.md#build-a-release).

## Development environment

Use standard GIL-enabled CPython 3.14.7 and uv 0.12.7 on macOS arm64 or Linux
x86_64, then synchronize the single lock without an editable install:

```sh
uv python install
uv sync --frozen --no-editable
```

Always pass `--no-editable` to `uv sync` and `uv run`. An editable install lets a
run read source files that no release contains; the tests and recorded runs use the
installed package. `make` targets reinstall the project in editable mode, so build
a separate environment for any installed or signed run:
`UV_PROJECT_ENVIRONMENT=/private/tmp/<name> uv sync --frozen --no-editable`. Plain
`uv sync` in `.venv` would also drop the locked notebook kernel group, which installs
by default. Feature serving needs the separately locked
[Feast worker](../configs/development/research-worker/README.md#setup-and-lock-audit).
A QR starts from [the quickstart](../examples/qr-quickstart.md).

Before starting or resuming any research or study, run `make local-services-up`
from the repository root. The
[research-session prerequisites](../examples/README.md#before-every-research-session)
cover Docker Desktop, private local credentials and service access checks.

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
| `alpha-backtest books --help` | Run saved L2 EDA, book rules, IOC fills and exact spot accounting |
| `alpha-collect --help` | Capture supported live market-data sources within their declared source contracts |
| `make check` | Complete source checks and isolated wheel smoke |
| `make format`, `make format-check`, `make lint` | Python formatting and linting |
| `make typecheck` | Strict typing across source, tools, tests and owned native stubs |
| `make build`, `make wheel-smoke` | Build the runtime wheel; verify installation without governance |
| `make test` | Correctness and integration tests, excluding performance cases |
| `make integration-test`, `make performance-test` | Explicit integration or performance selection |
| `make engineering-standards-check` | Protected typing, import and docstring rules |
| `uv run --frozen --no-editable alpha-governance-engineering-standards import-audit PATH` | Check code outside the repository imports only supported platform names |
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
This installation boundary does not replace
the release workflow's signing and admission checks.

## Documentation map

| Start here | Contents |
| --- | --- |
| [Architecture](architecture/README.md) | Current architecture and implemented domain contracts |
| [Platform design](architecture/platform-design.md) | Planned shared modules, runtime lanes, contracts, recovery and scaling decisions |
| [Development workflow](governance/workflow.md) | Implementation, validation and founder activation rules |
| [Operations runbook](governance/operations.md) | Security, monitoring, stop and recovery requirements for a future deployment |
| [Platform infrastructure roadmap](roadmap/README.md) | Completion status, planned capabilities, dependencies and functional ownership |
| [Research guide](../examples/README.md) | Economic questions, four study workbooks, baseline comparisons and decision outputs |
| [Ranked research agenda](../examples/research-agenda.md) | A1–F8 hypotheses, initial MVPs, validation and expansion priorities |
| [Research studies and reports](../src/research/studies/README.md) | Retained saved studies, comparisons, diagnostics, configured reports, publication and serial pipelines |
| [Experiment attempts and temporal splits](../src/research/experiments/README.md) | Semantic run identity, temporal fitting/holdout rules and append-only attempt history |
| [Saved L2 workflow](research/l2-book-backtest.md) | Configured book simulation, input limits, accounting and recovery |
| [Research program](roadmap/research-program.md) | Research workstreams, implementation outputs, costed comparisons and holdout discipline |
| [Data sources](data_source/README.md) | Sources by asset class and data type, historical coverage, access limits and dated verification evidence |
| [Engineering guide](coding_standards/README.md) | Enforced clarity and numerical engineering requirements |
| [Instrument identity](architecture/instrument-identity.md), [venue calendars](architecture/venue-calendar.md), [financial units](architecture/financial-units.md) | Implemented domain contracts and golden datasets |
| [Data contracts](data/contracts.md), [point-in-time semantics](data/point-in-time-semantics.md), [data library](../src/market_data/README.md) | Implemented events, decoding, provenance and current construction example |

The [data command reference](../src/market_data/README.md) and
[collector guide](data/l3-collectors.md) own acquisition usage and limits.
[Backtesting](research/l2-book-backtest.md) has an installed offline command.
The [local paper operator commands](../src/applications/execute/README.md#local-operational-commands)
cover account controls and recovery; production deployment, activation and venue
stop/cancel remain unqualified.
Keep actual release identities, data provenance and unresolved dependency
evidence; no current result grants live readiness.
