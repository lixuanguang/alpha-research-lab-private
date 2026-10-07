# Development environment

Use standard GIL-enabled CPython 3.14.7 and uv 0.12.7 on macOS arm64 or Linux x86_64,
then synchronize the single lock without an editable install:

```sh
uv python install
uv sync --frozen --no-editable
```

Always pass `--no-editable` to `uv sync` and `uv run`. An editable install lets a run
read source files that no release contains; the tests and recorded runs use the
installed package.
- `make` targets reinstall the project in editable mode, so build a separate
  environment for any installed or signed run:
  `UV_PROJECT_ENVIRONMENT=<path> uv sync --frozen --no-editable`.
- A plain `uv sync` in `.venv` also drops the locked notebook kernel group, which
  installs by default.
- Feature serving needs the separately locked [Feast worker](../local-services/feast-worker.md).

Before starting or resuming any research, run `make local-services-up` from the
repository root. The [research-session prerequisites](../research/guide.md#before-every-research-session)
cover Docker Desktop, private local credentials and service access checks;
[local services](../local-services/lakefs.md) covers first-time setup.

Exact interpreter and dependency inputs live in [pyproject.toml](../../pyproject.toml),
[uv.lock](../../uv.lock) and [.python-version](../../.python-version). Development tooling
installs through the `dev` dependency group; the runtime package has no dependency on
governance or repository policy files.

## Commands

The [Makefile](../../Makefile) provides the standard commands. During development, run
the checks and tests relevant to the change and record what ran; `make check` is the
complete local entry point.

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
| `make architecture-check` | Local links and headings in `docs/**/*.md` |
| `make dependency-admission-check`, `make dependency-audit` | Frozen dependency sources, retained restrictions and vulnerability audit |
| `uv run --frozen alpha-governance-artifacts release-check` | Report release blockers; currently always fails closed |
| `make ci-secrets-check`, `make security` | Secret and private-key scanning, and Bandit |
| `make governance-check` | The clarity, dependency and link checks together |

For selected tests:

```sh
uv run --frozen --no-editable pytest -q <test-paths>
```

[Testing](testing.md) describes the test layout and lanes. Hosted CI runs only on pull
requests to `main` labelled `ready-to-merge`; its merged-result lane is authoritative
before merge.

## Validation lanes

A change is validated in four lanes, each in its own environment so editable and
non-editable installs cannot race:

| Lane | Command |
| --- | --- |
| Complete checks | `make check` |
| Integration, with the Feast worker | `ALPHA_FEAST_WORKER_PYTHON=<worker python> uv run --frozen --no-editable pytest -q -m integration` |
| Performance | `uv run --frozen --no-editable pytest -q -m performance` |
| Linux strict typing | `uv run --frozen --no-editable mypy --strict --platform linux src tests tools/governance/src tools/typing/stubs examples extensions` |

Timing-ratio performance tests can fail under load; rerun them alone. Tests that open
Unix sockets need a short `--basetemp` (for example under `/private/tmp`) on macOS.

The [architecture overview](../architecture/overview.md) explains the source and
installed-package checks. Runtime consumers can install the built wheel with its
declared domain dependencies; development tools are absent from the runtime
distribution. This installation boundary does not replace the release workflow's
signing and admission checks.
