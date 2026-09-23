# Alpha Research Platform

Current scope: bounded local research from retained market data to exact spot
simulation, model studies and reports. MRs 1–9A are implemented and closed within
their recorded limits; [MR10–MR21](roadmap/README.md#delivery-order-and-dependencies) define future
candidate, deployment and operating work. No paper or live trading service is
qualified or activated.

Start with the [researcher guide](../examples/README.md). The maintained data
journeys use [saved OKX L2 backtesting](research/l2-book-backtest.md) and
[bounded Bitfinex capture/replay](data/l3-collectors.md). The [roadmap](roadmap/README.md)
owns capability status and the OKX/Bitfinex source policy;
[architecture](architecture/README.md) owns current package boundaries and
[research methodology](roadmap/research-program.md) owns evaluation choices.

The accepted [saved-data baseline](research/saved-baseline-acceptance.md) is a
reproducible simulation, not empirical causal-source or strategy qualification.
Legacy Binance/Tardis P1 work is deferred and unaccepted; its records are listed
under [historical evidence](#historical-evidence).

QuantLib's unresolved source-to-wheel binding permits isolated development/CI
through 2026-10-04 and blocks release use. See the
[dependency restriction](architecture/dependency-admission.md#quantlib-restriction)
and [release workflow](governance/workflow.md#build-a-release).

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
| `alpha-backtest books --help` | Run saved L2 EDA, book rules, IOC fills and exact spot accounting |
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
| [Platform infrastructure roadmap](roadmap/README.md) | Completion status, planned capabilities, dependencies and functional ownership |
| [QR implementation guide](../examples/README.md) | Research activities: data selection/onboarding, features/labels, models/rules, backtesting, candidate promotion and monitoring; current versus planned support |
| [Research studies and reports](../src/research/studies/README.md) | Retained saved studies, comparisons, diagnostics, configured reports, publication and serial pipelines |
| [Experiment attempts and temporal splits](../src/research/experiments/README.md) | Semantic run identity, temporal fitting/holdout rules and append-only attempt history |
| [Saved L2 workflow](research/l2-book-backtest.md) | Configured book simulation, real-source results and offline recovery |
| [Research program](roadmap/research-program.md) | Research workstreams, implementation outputs, costed comparisons and holdout discipline |
| [Data sources](data_source/README.md) | Sources by asset class and data type, historical coverage, access limits and dated verification evidence |
| [Engineering guide](coding_standards/README.md) | Enforced clarity and numerical engineering requirements |
| [Instrument identity](architecture/instrument-identity.md), [venue calendars](architecture/venue-calendar.md), [financial units](architecture/financial-units.md) | Implemented domain contracts and golden datasets |
| [Data contracts](data/contracts.md), [point-in-time semantics](data/point-in-time-semantics.md), [data library](../src/market_data/README.md) | Implemented events, decoding, provenance and current construction example |

The [data command reference](../src/market_data/README.md) and
[collector guide](data/l3-collectors.md) own acquisition usage and limits.
[Backtesting](research/l2-book-backtest.md) has an installed offline command;
paper trading, deployment, activation and trading stop commands remain planned.
Keep actual release identities, data provenance and unresolved dependency
evidence; no current result grants live readiness.

## Historical evidence

These records explain closed milestones or deferred work; they are not current
quickstarts or additional implementation gates. Their hashes, measured results
and limitations apply to the revisions and inputs identified in each record.

- [MR1–MR9A delivery history](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/history-mr1-to-mr9a.md) and
  [completed maintenance](roadmap/post-mr9a-maintenance-review.md).
- [Saved OKX baseline acceptance](research/saved-baseline-acceptance.md).
- [Frozen P1 specification](research/p1-baseline.md),
  [qualification evidence](research/source-qualification.md) and
  [provider investigation](research/provider-records.md). No outreach is pending.
- [Legacy P1 reproduction](research/legacy-p1-reproduction.md), requiring its
  matching historical checkout and environment.
