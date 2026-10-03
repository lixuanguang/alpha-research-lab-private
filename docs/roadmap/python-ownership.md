# MR16 Python ownership and enforcement

Owner: quant development. Status: **design approved by the owner (2026-10-04); implementation in progress.** The [roadmap](README.md#runtime-operations-and-handoff)
owns MR16 delivery status. The [engineering guide](../coding_standards/README.md#python-scope-and-migration)
owns the rules. This page covers three things: how far the maintained Python diverges
from those rules today, what the checker already enforces, and the proposed enforcement,
migration and acceptance.

## Inventory (main at 3044d52, 2026-10-04)

**Method.** The inventory was taken with an AST scan of every `.py` and `.pyi` file under
the checker's four roots (`src`, `tests`, `tools/governance/src`, `tools/typing/stubs`)
and under `examples/`. No untracked files were present. Ignored historical
copies under `logs/` are evidence, not maintained source, and are excluded.

Scope: 347 files under `src` (84,788 lines), 264 under `tests` (103,296 lines), 27 under
governance (6,519 lines), 24 native stubs (1,377 lines) and 1 example script.

**Module-level functions.** This counts every `def` whose enclosing scope is the module,
including definitions inside module-level `if` and `try` blocks. There are 414 in total.

| Area | Command `main` | Other public | Private (`_name`) | Exempt by design |
| --- | --- | --- | --- | --- |
| `src/applications` | 7 | 42 | 6 | — |
| `src` libraries | — | 6 (`configuration` 2, `serialization` 3, `strategies` 1) | 20 (`configuration` 9, `execution` 8, `accounting` 1, `market_data` 1, `serialization` 1) | 5 lazy `__getattr__` exports |
| `tools/governance/src` | 6 | 11 | 20 | — |
| `tools/typing/stubs` | — | — | — | 10 upstream free functions |
| `tests` | 50 script `main`s (45 consumers, 5 subprocess support) | 134 `test_*` functions in 27 files; 5 module-level fixtures in 5 files | 91 helpers in 36 files | — |
| `examples` | 1 (`run_notebook.py`) | — | — | — |

- **Applications.** The 42 public functions in `src/applications` (`acquire`, `run_backtest`,
  `run_paper_services`, `evaluate_study` and others) are orchestrator candidates. Whether
  each one actually orchestrates is a review judgment. Some, such as `fetch_partition`,
  `compare_vectorbt` and `render_paper_monitoring`, need that review. The 6 private
  application helpers (`acquire/workflow.py:_archive`, `explore/offline.py` 3,
  `explore/studies.py` 2) are not orchestrators.
- **Libraries.** These are the non-orchestrator functions in `src` libraries:
  - `configuration/venue_secrets.py`: 11, including log-redaction installation and
    core-dump disabling;
  - `execution/account_state.py`: 7 row and key helpers on the account journal path;
  - `execution/account_admission.py`: 1 (`_replaced`);
  - `serialization/durable.py`: 4 (`sync_directory`, `publish_directory`,
    `require_sqlite_layout`, `_schema`), whose callers are spread over 20 files in `src`
    and `tests`;
  - `strategies/reference.py`: 1 (`reference_policy`), referenced in 8 files;
  - `accounting/accounts.py`: 1 (`_exact_money`);
  - `market_data/adapters/venues/coinbase/auth.py`: 1 (`_decoded`).
- **Governance tooling.** The tooling, including the engineering checker itself
  (`checker.py`: 6 functions), has 31 non-command functions. Most of them are in
  `dependency_admission/policy.py` (15) and `ci_policy` (7).

**Nested functions.** There are 77 nested functions in 32 files. One is in `src`:
`market_data/query/reader.py:287` (`one`, inside `QueryReader`). The other 76 are in
31 test files; the largest counts are in `tests/unit/execution/test_venue_gateway.py` (10),
`tests/integration/consumers/runtime/test_capacity_reads.py` (9) and
`tests/engineering/test_ci_policy.py` (7).

**Lambdas.** There are 85 lambdas, and none of them is a sort key.
- `src` has 11:
  - `execution/account_admission.py:1121–1171`: 7 lambdas that attribute history events
    to accounts and are passed to the clock folders in `_history_times`. They are
    behaviour.
  - `runtime/jobs.py` (2) and `runtime/workspace.py` (2): 4 `iter(lambda: f.read(n), b"")`
    chunk sentinels.
- `tests` has 74, in 20 files: 34 positional callbacks, 11 keyword callbacks, 3
  `default_factory`, 4 assigned and 22 others.

**Test layout.** 216 `Test*` classes hold 1,414 test methods. 134 test functions (8.7%)
sit outside classes. Test data and fixture helpers sit at module level as well.

**Native libraries.** The stubbed libraries are `alphalens`, `clearml`, `duckdb`,
`exchange_calendars`, `lakefs_sdk`, `pandas`, `pandera`, `polars`, `quantstats` and
`vectorbt`. They are imported by 15 `src` modules, and every call except one is made
inside a class.
- `applications/backtest/configured.py:run_worker` imports and calls `clearml.Task` in a
  module-level function.
- `applications/backtest/configured.py` and `applications/backtest/command.py` import
  `lakefs_sdk` in an application. The adapter class `_StorageAccess` therefore lives in
  the orchestrator layer, not a library.
- In tests, `tests/integration/consumers/datasets/versioned_storage.py` calls `lakefs_sdk`
  from module-level functions.

Whether each class that holds these calls is a genuine owned adapter is a review judgment.

**Imports into `src` from outside `src`.** The checker never inspects these imports.

| Kind | Unit tests | Integration, engineering and support | Total |
| --- | --- | --- | --- |
| Owner public API (`owner` module, name in `__all__`) | — | — | 1,463 statements |
| Deep module (below the owner API) | 93 in 44 files | 29 in 18 files | 122 |
| Private module or name | 18 in 16 files | 2 in 2 files | 20 |
| Submodule imported through the API (`from configuration import venue_secrets`, `from applications.collect import workflow`) | 2 | — | 2 |

- **Private imports.** These concentrate on `execution.account_state` (`_FirmHead`,
  `_strip`, `_assemble`, `_row_values` and others), `applications.execute.*` (`_SourceChild`,
  `_AccountHealth`, `_DecodedBookObservation`), `runtime.shared_paper`, and the base
  models of `financial_units` and `reference_data`.
- **Missing exports.** 45 public names imported by tests are not in their owner's `__all__`,
  across 20 deep modules. Examples are `applications.execute.services.PaperServices`,
  `execution.account_state.AccountStateStore`, `execution.venues.contracts.*` and
  `telemetry.dashboard.POINT_LIMIT`.
- **Path mutation.** 5 consumers (`research/decision_study.py`, `research/candidate_workflow.py`,
  `runtime/live_paper.py`, `runtime/account_operations.py`, `runtime/portfolio_account.py`)
  prepend their own directory to `sys.path` to load sibling modules such as the
  `research_workflows` extension package. The runtime consumers and their tests import siblings
  (`capacity_inputs` and others) through pytest's rootdir insertion; 27 files do this,
  including the private `capacity_deliveries._IndexedSharedDelivery`.

**Reference-workflow imports.** The maintained reference consumers are 58 non-test modules
under `tests/integration/consumers`. Between them they use 44 owner APIs (404 distinct
names) and 13 deep modules (37 names). Two of the deep imports are private
(`execution.account_state._AccountTransaction` and related names, and
`applications.execute.source_service._DecodedBookObservation`). The example notebooks
import no project packages.

**Packaging.**
- **Example script.** `examples/run_notebook.py` is maintained source outside every
  configured scope: the checker, Ruff, mypy and Bandit all skip it. It has an
  `if __name__ == "__main__"` block, and it imports `nbformat`, `nbclient` and
  `jupyter_client`, which are neither declared nor locked. It relies on a mutable kernel
  stack that a plain `uv sync` removes.
- **Exports.** Exports are checked statically: `__all__` must be bound, and lazy exports are
  checked for their shape. The installed wheel smoke imports every package initializer,
  but it does not resolve each `__all__` name. The three partial distributions
  (`packages/collector`, `execution`, `contracts`) hand-list their files and have no
  installed export check.
- **Owner APIs.** Every functional owner has an `__init__` API. The only exception is the
  private `reference_data._validation`, which the checker already allows by name.

## What the checker enforces today

`make engineering-standards-check` (`alpha-governance-engineering-standards`) runs four
groups of checks:
- **Tooling configuration.** Strict mypy flags, Ruff rule families and the pytest warning
  policy, with no excludes or ignores.
- **Python source, over the four roots.** Import headings and order, no explicit `Any`,
  Google docstrings, and suppression metadata with an expiry.
- **Source layout, over `src` only.**
  - The retired `alpha_research` namespace is refused.
  - Dependency direction is enforced (libraries cannot import applications; configuration
    and neutral contracts cannot import services).
  - Cross-owner imports must go through the owner's `__init__` API and cannot use private
    names.
  - Imported names must be in the owner's `__all__`.
  - Only initializers declare `__all__`, and exports must be bound.
  - Runnable `main` entry points are allowed only in applications, with one per owner and
    no `__main__` or `if __name__` blocks.
  - Command scripts must bind `applications.<owner>:main`.
- **Format compatibility.** Wording that keeps an earlier format alive is refused, as are
  `_vN` names.

It does **not** enforce any of the following:
- the orchestrator-only rule for module-level functions;
- nested functions or lambdas;
- test functions outside classes;
- native-library calls outside classes;
- any import rule for `tests`, `tools` or `examples`;
- the scope of `examples/`;
- installed resolution of `__all__`.

The guide says this explicitly. It also says the checker has no waiver mechanism.

## Proposed enforcement

Add an `OwnershipChecker` under `engineering_standards`. Like the other checks, it is
AST-only and fail-closed, and it is called from `validate_repository`. Its scope is the
four current roots plus `examples/`. Ruff, mypy and Bandit extend to `examples/` in the
same change, so that file is formatted, linted and type-checked like the rest. The rules:

1. **Module-level functions.** A module-level function is a finding unless it is one of the
   following:
   - (a) a function in a `.pyi` file under `tools/typing/stubs`, which mirrors an upstream
     free function;
   - (b) an `@overload` signature whose implementation is itself permitted;
   - (c) a checked lazy-export `__getattr__` in an `__init__.py` (the shape the layout
     checker already verifies);
   - (d) a **public** function in an `applications.<owner>` module, the orchestrator layer;
   - (e) a `main` command function in a governance command package, a test consumer or
     subprocess script, or an example script;
   - (f) a `pytest_*` hook in a `conftest.py`.

   Private functions are never orchestrators. Test functions, fixtures and helpers must be
   methods. Whether a permitted orchestrator actually orchestrates stays a review
   requirement.
2. **Nested functions.** A `def` or `async def` inside a function or method is a finding.
   There is no exemption.
3. **Lambdas.** Every lambda is a finding. There is no exemption; the current code has no
   sort-key lambdas to justify one. The four `iter(...)` sentinels can use
   `functools.partial(source.read, n)`, which is behaviour-identical.
4. **Native-library calls.** A stubbed library is identified by a directory under
   `tools/typing/stubs`, so adding a stub automatically brings that library under the rule.
   Its names may be referenced only inside class bodies, and may not be imported by
   `applications.*` modules. Only module-level imports and type annotations are allowed
   outside a class. Whether the class is a cohesive adapter stays a review requirement.
5. **Imports from outside `src`.** Imports from `tests`, `tools/governance/src` and
   `examples` into owned packages use the same rule as cross-owner imports inside `src`:
   - no private module or private name, anywhere;
   - reference workflows (`tests/integration`, `tests/engineering`, `tests/support`,
     `examples`) import only names in an owner's `__all__`;
   - unit tests under `tests/unit` may also import **public** names from deep modules,
     because they test the module that owns them, and exporting every tested class would
     widen the supported API only for tests;
   - no `sys.path` mutation in maintained source.
6. **The checker itself** is migrated to classes in the first milestone, so the new rules
   apply to it.

**Debt ledger.** Rather than migrate about 510 findings in one change (32 `src`, 31 governance and 230 test functions; 77 nested functions; 85 lambdas; 3 native uses; 51 imports), the checker milestone
seeds a committed ledger, `tools/governance/ownership-ledger.toml`.
- **Entry key.** Each entry is keyed by `(path, rule, qualified symbol)`, not by line,
  with an occurrence count for lambda and import rules.
- **Validation.**
  - A finding not in the ledger fails.
  - A ledger entry whose count is above the current count, or that has no current finding,
    fails as stale, so every fix must also delete its entry.
  - Entries must be sorted and unique.
- **Growth control.** The working ledger and every committed version since the
  merge-base with `main` must each be no larger, entry by entry, than the version before
  it. Only the first version, which seeds the ledger, is unconstrained. If Git or the base
  cannot be resolved while a ledger exists, the check fails closed.
- **Lifetime.** The ledger is temporary: MR16 acceptance requires it to be empty and
  removed, together with the ledger support.

The guide's "no waiver" sentence changes to describe exactly this shrink-only ledger and
its removal at MR16 acceptance.

**Behavioral tests.** These are written first, in `tests/engineering`. Each rule gets
violating and compliant fixtures, including the exemption boundaries: a private
application function is refused; `main` outside the allowed locations is refused; a stub
`.pyi` is accepted, but the same function in a `.py` file is refused. The ledger tests
cover:
- a new finding failing;
- a recorded finding passing;
- a fixed finding with a stale entry failing;
- a raised count failing;
- an entry added relative to the merge-base failing;
- an unreadable or malformed ledger failing closed.

A final test confirms that the repository passes with the seeded ledger.

## Supported imports contract

The supported Python API is the `__all__` of each functional owner's `__init__.py`:
- the 15 top-level packages;
- the owner subpackages of the grouping namespaces `market_data`,
  `market_data.adapters.*`, `reference_data`, `research` and `applications`.

Deep modules, private names, grouping namespaces and command implementation modules are
not supported, even when importable. The reference workflows (the consumers, integration
tests, subprocess support and examples) are the executable consumers of this contract.
After migration they use owner APIs only. That moves 29 deep and 2 private imports, and
the owners export what those workflows legitimately need (for example `PaperServices`,
`AccountStateStore`, the venue contract records, `ServiceBookInputs`). Names that only
the capacity harness needs as private internals are replaced with supported equivalents
or test doubles. They are never exported as private names.

The contract is published in the [platform design](../architecture/platform-design.md#functional-apis-and-application-entrypoints)
together with the owner list. The installed check grows to resolve every `__all__` name
in the runtime wheel and in each of the three partial distributions (`collector`,
`execution`, `contracts`), including lazy exports.

## Migration order

Every step migrates one package together with its callers, exports, tests and
documentation, and removes its ledger entries. The full suite must pass unchanged in
behaviour, with the same goldens, journal and wire schemas, configuration identities and
error messages.

**Milestones.** Each milestone is one commit.
1. **Checker and ledger.** The rules, their behavioral tests and the seeded ledger; the
   guide update; `examples/` brought into the ownership checker's scope.
2. **Governance tooling.** 31 functions and 7 nested functions in its tests;
   `tests/engineering` test functions (46) and helpers (7). This is lowest risk and puts
   the checker under its own rules.
3. **Foundations.** `serialization.durable` becomes a durable-filesystem class, with its
   20 caller files; then `accounting`, `strategies.reference_policy` (8 files),
   `market_data` (the Coinbase auth helper, `QueryReader.one`), and the `runtime` sentinel
   lambdas. Their unit tests move to classes in the same steps.
4. **`configuration.venue_secrets`.** A secrets reader and a process-hardening owner. These
   are process-global side effects (log redaction, core dumps), so the redaction and
   refusal tests must pass unchanged.
5. **`execution`.** The `account_state` row and key helpers and the `account_admission`
   attribution lambdas become methods; the private test imports (`_FirmHead`, `_strip`,
   `_assemble` and others) are replaced with public behaviour. This is the account-journal
   hot path: the history-scaling tests and journal goldens must pass unchanged, and the
   schemas are not touched.
6. **`applications`.** The 6 private helpers become methods. `lakefs_sdk` and `clearml` use
   moves into library adapters. All 42 public functions are reviewed, and a function that
   does not orchestrate becomes a method of its owner. The missing exports for reference
   workflows are added, along with the installed export check.
7. **Remaining unit tests by package.** Test functions, fixtures, helpers, nested functions
   and lambdas in `data`, `execution`, `financial_units`, `core`, `runtime`, `simulation`,
   `venue_calendar`, `instrument_identity`, `configuration`, `research` and `telemetry`.
8. **Integration tests and consumers.** The capacity harness goes last, since it is also
   the harness for the deferred stage 2b. This step covers its 20-function
   `account_history_capacity.py`, the `capacity_deliveries` private import, the `sys.path`
   mutation in five consumers, and `examples/run_notebook.py` with its locked `notebooks`
   group, owned stubs and Ruff, mypy and Bandit scope. The ledger is then empty and is
   removed.

**Stop points.** If a migration would change runtime behaviour, a public wire or journal
schema, a signed configuration identity, or the meaning of stage-1/2a evidence, I stop and
ask. Recorded stage-1/2a evidence keeps its frozen commits and is never rerun or rewritten.

## MR16 acceptance criteria

1. The ownership rules above are enforced over `src`, `tests`, governance, stubs and
   `examples`, with behavioral tests for every rule, exemption and ledger property.
2. The ledger is empty and removed. The guide states the enforced rules, and its "pending
   migration" text is replaced, not kept alongside.
3. Every remaining module-level function is a stub function, an overload, a lazy export, a
   reviewed application orchestrator, a command `main` or a pytest hook. The orchestrator
   review is recorded on this page.
4. The supported imports contract is published. Reference workflows import only owner
   APIs, and the installed runtime and partial distributions resolve every exported name.
5. Maintained scripts declare and lock their direct dependencies. This depends on the
   owner decision on the notebook runner, below.
6. `make check`, the integration and performance lanes, and the Linux strict mypy run all
   pass, with test counts reported as run. No golden, schema, configuration identity or
   evidence semantics change.
7. The [engineering guide](../coding_standards/README.md), [tests guide](../../tests/README.md),
   [platform design](../architecture/platform-design.md) and [QR guide](../../examples/README.md)
   describe the result (D01/D18).

## Owner decisions (approved 2026-10-04)

The owner approved this design on 2026-10-04, with these decisions:

1. **Ledger growth control.** The ledger can only shrink. The checker compares the working
   ledger with every committed version since the merge-base with `main` (or `origin/main`)
   and fails if any entry was added or raised after the ledger first appeared. If Git or
   the base cannot be resolved while a ledger exists, the check fails closed. The ledger
   and its support are removed at MR16 acceptance.
2. **Unit-test deep imports.** `tests/unit` may import public names from deep modules.
   Private modules and names are refused everywhere, and every other area imports only
   owner APIs.
3. **The notebook runner.** It gets a locked `notebooks` dependency group, added to
   `default-groups` and kept out of every runtime and partial distribution, through
   dependency admission. `nbclient` and `nbformat` ship no type information, so the
   group, owned stubs and the extension of Ruff, mypy and Bandit to `examples/` land with
   the runner's migration in milestone 8. Until then the ownership checker already scans
   `examples/`, and the runner's findings sit in the ledger.
4. **Capacity harness timing.** The harness is migrated in MR16, before the deferred
   stage 2b, which runs on the migrated harness under its own declaration and rehearsals.

## Progress

- **Milestone 1 (2026-10-04): checker and ledger.** `OwnershipChecker` and the
  shrink-only ledger are enforced by `make engineering-standards-check`, with behavioral
  tests in `tests/engineering/test_ownership.py`. The seeded ledger records 555 findings
  under 504 entries: 293 module-level functions, 77 nested functions, 85 lambdas, 3
  native calls, 3 native imports in applications, 35 private, 52 deep and 2 unexported
  imports, and 5 `sys.path` mutations. These match the inventory above.
- **Milestone 2 (2026-10-04): governance tooling.** The governance package's 31
  module-level functions are now methods of `ArchitectureGovernanceService`,
  `SecretScanner`, `SecretScanCommand`, `DependencyPolicy`, `PipAuditReport`,
  `DependencyRepository` and `EngineeringStandards`. The package exports those classes
  instead of the functions. The `tests/engineering` test functions, helpers and nested
  doubles are in classes. The ledger shrank from 555 to 464 findings.
- **Milestones 3–5 (2026-10-04): foundations, configuration and execution.**
  - `serialization` exports `DurableDirectory` and `SqliteLayout` instead of three
    functions (callers in 20 files). `strategies` exports `ReferencePolicies.create`
    instead of `reference_policy`.
  - The accounting, Coinbase, query-reader and runtime helpers moved into their owning
    classes; the chunk-read lambdas became `functools.partial`.
  - `configuration.venue_secrets` splits into `SecretFile` and `CredentialRedaction`.
    The process-wide registry and lock are now class state with the same copy-on-write
    and frame-locals behaviour.
  - The account-admission attribution lambdas became methods. `_Latest.of` does not key
    on the callback, so behaviour is unchanged.
  - The journal head, row and summary classes that unit tests need are now public names
    of `execution.account_state`, but are not exported. The record types carry no wire
    tags, so the journal format is unchanged. `_AccountTransaction`, `_SavedDecision` and
    `_SavedPortfolioBatch` stay private pending the capacity-harness decision.
  - The runtime, accounting, configuration and execution unit tests moved into classes,
    with callable test doubles. The ledger shrank from 464 to 319 findings.
- **Milestone 6 (2026-10-04): applications and supported imports.**
  - **Orchestrator review.** All 42 public module-level functions in `src/applications`
    were reviewed as workflow orchestrators: each composes, resumes, sequences or retains
    a workflow over library owners. The private helpers became the subcommand
    orchestrator `run_archive`, the `OfflineFeatureSource` checks, and
    `StudyComponents.evaluate`.
  - **Native libraries.** lakeFS client construction moved into
    `LakeFSStorage.connect`/`close`, and the ClearML worker task into
    `research.studies.PipelineStepTask`. Applications no longer import native libraries.
  - **New exports.**
    - `applications.execute` lazily exports `ServiceBookInputs`, `PaperServiceControl`,
      `PaperServiceOwners` and `run_paper_services`; the lazy form keeps the independent
      execution distribution importable.
    - `market_data.collection` exports `CaptureSegmentWriter`.
  - **Reference workflows** now import those names, and every other already-exported
    name, through owner APIs.
  - **Held for the capacity-harness decision:** `execution.account_state`
    (`AccountStateStore` and the private transaction records) and
    `source_service._DecodedBookObservation`. The ledger shrank from 319 to 245 findings.
