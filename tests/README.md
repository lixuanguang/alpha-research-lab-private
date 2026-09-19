# Tests and retained inputs

This guide describes the maintained test layout and how to run its isolated
consumers. The [engineering guide](../docs/coding_standards/README.md#stable-names-and-test-support-layout)
owns naming requirements; the [development workflow](../docs/governance/workflow.md)
owns validation and merge requirements.

## Layout

| Location | Responsibility |
| --- | --- |
| `unit/` | Domain and component tests, including existing integration-marked cases beside their owning component |
| `engineering/` | Packaging, dependency, source-standard and governance tests |
| `golden/` | Independently specified domain expectations |
| `fixtures/` | Static input bytes organized by domain and scenario; no executable Python |
| `support/subprocesses/` | Child-process acquisition fakes and deliberate publication interruptions |
| `integration/test_*.py` | Discovered workflow tests, including acquisition through saved EDA |
| `integration/consumers/` | Standalone installed-package scenarios grouped into datasets, eligibility, query, replay and capture |

The static inputs include Tardis-framed trades and Coinbase book messages under
`fixtures/market_data/`, eligibility histories under `fixtures/eligibility/`, a
canonical trade partition under `fixtures/replay/`, and an explicit synthetic
contract under `fixtures/instruments/`.

[Assumptions and membership](fixtures/eligibility/assumptions-and-membership.json)
distinguishes later research assumptions from historically available synthetic
membership evidence. [Membership corrections](fixtures/eligibility/membership-corrections.json)
adds decision-time correction and delisting scenarios. These are different inputs,
not interchangeable copies of a generic eligibility file.

## Execution and isolation

Run from the repository root:

```sh
# All correctness tests, including integration cases; excludes performance cases.
make test

# Only the installed acquisition/resume/publication/EDA workflow.
uv run --frozen --no-editable pytest -q -m integration tests/integration/test_ingestion_workflow.py

# Existing component integration cases as well as workflow integration tests.
make integration-test
```

Plain pytest uses the configured marker filter, which excludes integration and
performance cases. A file under `consumers/` is not automatically a pytest test.
The ingestion, capture recovery, saved-book, health and parity consumers have
pytest callers. Other consumers remain manual acceptance programs; moving them
does not add CI coverage. The recovery probe needs an explicitly selected saved
Bitfinex capture; the synthetic acceptance consumers need only copied inputs.

Consumers intentionally run as fresh processes with `python -I`, copied scripts
and inputs, a working directory outside the checkout, and the installed runtime.
They must not import repository test helpers or add the checkout to `sys.path`.
The subprocess support scripts may terminate without cleanup using `os._exit`;
invoke them through their test or consumer, never in the pytest process itself.
The package's real orchestration stays in `src/applications/`;
consumers compose it with synthetic transports, failure injection and assertions.

For manual installed checks, copy the selected consumer and its inputs into a
fresh external directory, preserving basenames. Use the installed interpreter
to run `python -I <copied-consumer> <inputs>`; `eda_consumer.py` and
`ingestion_workflow.py` additionally require a fresh output-directory argument.

| Consumers | Copied inputs |
| --- | --- |
| Dataset and query consumers | `configs/data-jobs/binance-archive.json`, `configs/reference/binance-archive-spot.json`; readers of eligibility also need `fixtures/eligibility/membership-corrections.json` |
| `read_occurrences.py` | Archive inputs above plus `configs/data-jobs/fixture-inspection.json` and `configs/reference/binance-spot.json` |
| `read_eligibility.py` | Archive reference catalog and `fixtures/eligibility/assumptions-and-membership.json` |
| `select_eligibility.py` | Archive reference catalog and `fixtures/eligibility/membership-corrections.json` |
| `publish_snapshot.py` | Dataset inputs plus `support/subprocesses/interrupt_snapshot.py` |
| `dataset_command.py` | Dataset inputs plus `support/subprocesses/interrupt_command.py` |
| `ingestion_workflow.py` | Dataset inputs, `support/subprocesses/interrupt_command.py`, and `configs/live/okx-btc-usdt.json` |
| `eda_consumer.py` | Query inputs plus `fixtures/instruments/contract.json` |
| `replay_consumer.py` | `fixtures/replay/canonical.json`, `configs/data-jobs/fixture-inspection.json`, `configs/reference/binance-spot.json` |

Fixture and support paths in this table are relative to `tests/`; configuration
paths are relative to the repository root. Capture consumers have different
arguments for saved captures and synthetic endpoints; use their existing pytest
callers or the maintained [engineer notebook](../examples/infrastructure-diagnostics.ipynb).
The [QR notebook](../examples/research-foundations.ipynb) follows research activities
and uses the existing installed handoff as its default synthetic input setup.
The explicit [live counterparts](../examples/README.md#start-with-your-research-question)
exercise bounded public capture and saved-input reopening; they are manual external-source
checks, not network-dependent unit tests. Run each through the [existing notebook runner](../examples/notebook-operations.md#running-a-notebook)
when their executable cells change; the configured source checks do not discover
notebook cells.

## Functional layout verification

`engineering/test_source_layout.py` exercises forbidden dependency directions,
private/module API bypasses, duplicate commands, installed inventory faults and
pre-refactor snapshot reopening. Existing behavioral test groups keep their names;
their imports use functional APIs, with internal imports reserved for focused tests
and fault injection. No `research/features` or `applications/features` exists yet.

`make wheel-smoke` installs the frozen runtime into a clean environment outside
the checkout. It imports every shipped API, checks package resources and identity
scope, and runs the four existing commands with copied synthetic/saved inputs.
It reuses ingestion/recovery consumers for acquisition resume, dataset admission,
EDA, pinned mixed trade/book selection, fresh-process reopening and book replay;
governance is absent from this installation. On macOS,
`TMPDIR=/private/tmp make check` keeps Unix-domain socket paths within OS limits.

The `fixtures/datasets/historical_snapshot` fixture was produced before migration.
Its original wheel/revision, canonical bytes and implementation identity are
retained in `provenance.json`; tests do not regenerate it under current code.

The [research access tests](unit/data/test_research_access.py) exercise published
mixed inputs, late corrections, membership withdrawal, unknown archive clocks,
exact receipt cutoffs, controls, coverage, field/unit incompatibility and missing
raw bytes. The installed handoff selects the configured `spot-comparison` job;
synthetic HTTP and book messages establish software behavior only. No source access,
empirical completeness or deployment qualification is asserted.
