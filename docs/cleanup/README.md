# Repository cleanup plan for a solo quant founder

Audit date: 2026-09-07. Baseline: `97775789cfc21425abf4afcbb0498dd5ec69ea89`.
Status: steps 1 and 2 implemented and locally validated; step 2 hosted CI
validation remains pending. Steps 3–6 remain planned. The measured
baseline and audit findings below describe the repository before cleanup. The
working tree was clean at the start of the audit.

**Recommendation: keep the financial domain code, replace most of the custom
governance platform with ordinary development tools, and organize delivery around
one reproducible strategy progressing from research to monitored live operation.
Bring governance implementation below 3,000 lines while retaining typing,
import-style, and docstring enforcement and a smaller set of cohesive classes.**

The largest opportunity is reducing the number of concepts and files that must
change together. Deleting useful numerical tests would save little development
time: the current domain suite passed 184 tests in 2.36 seconds during this audit.
Prioritize removing retired policy obligations, their implementations, and their
tests together.

This extends the earlier [solo-founder migration](../roadmap/solo-founder-governance-migration.md),
whose steps 1–4 are already recorded as implemented. That migration established
founder implementation authority and a four-section PR. Retain those improvements.
This plan goes further by retiring infrastructure that still encodes the
institutional operating model, including prerequisites for future solo go-live.
Implementation must update the owning policies alongside their enforcement;
this document alone does not supersede the current operating rules.

## Clarity requirements to preserve

The founder's refinement to this plan keeps function typing, import conventions,
and explanatory docstrings as enforced engineering requirements. Preserve their
current scope across runtime source, governance tooling, tests, and owned stubs,
including the existing strict mypy settings. Do not introduce blanket typing
exclusions, disable import rules, or remove required documentation to meet a size goal.

Keep class-based organization where it identifies a meaningful concept, groups
related behavior, owns state, or establishes an invariant. Reduce the number of
classes by retiring unused capabilities, consolidating duplicate representations,
and removing forwarding layers. A coherent stateless validator can still justify
a class; state is not the only criterion. Low-level functions remain appropriate
without an individual expiry/fingerprint record.

Use Ruff and mypy for the rules they demonstrably cover. Keep a compact custom
checker for remaining project-specific requirements, including import headings,
explicit-`Any` forms, and applicable Google-style docstring sections. Before
replacing an existing checker, establish the same accepted/rejected behavior on
representative fixtures, including aliases, relative/`TYPE_CHECKING` imports and
private/public documentation requirements. Do not assume similarly named tool
rules provide equivalent coverage. Retain semantic review of whether docstrings
actually explain the behavior.

## Measured baseline

Inventory covers Git-tracked files under `docs/`, `src/`, `tools/`, `tests/`, and
root build/CI configuration. Sizes below are logical bytes, rounded to decimal
MB/KB. Python line counts include comments, blanks, and docstrings.

| Surface | Observed size | Implication |
| --- | --- | --- |
| Entire tracked checkout | 377 files; 4.47 MB | This is already a small download; maintenance is the larger problem. |
| Documentation, including policy/evidence records | 171 files; 1.23 MB | Many files describe or validate process rather than the next research task. |
| Canonical governance Python | 67 files; 31,309 lines; 188 class definitions | About 6.6 times the implemented financial domain code; count includes models, exceptions and protocols. |
| Financial units, instrument identity, venue calendars | 9 Python files; 4,759 lines | These are the three implemented domain capabilities. |
| Engineering tests | 25 Python files; 13,288 lines | 536 collected cases, including parameterized cases and optional markers. |
| Domain unit tests | 3 Python files; 3,396 lines | 187 collected cases; 184 run by the default marker selection. |
| Function-design exceptions | 486 records; 5,349 lines; 243 KB | Every record concerns `PYC001`; 350 low-level, 77 compatibility, 59 framework exceptions. |
| Developer entry points | 13 governance executables; 23 pre-commit hooks | A large command and configuration surface for one maintainer. |
| Historical evidence under `docs/governance/evidence/` | 105 files; 358 KB | Includes synthetic examples and real signature/source records; disposition must distinguish them. |

Governance Python plus engineering-test Python is about 81% of all tracked Python
lines. This is a footprint measure, not a claim that 81% of the code is useless.
The [current status](../governance/program-status.md) records 19 implemented
packages out of 96. The [docs home](../README.md#current-status) correctly says
there is no implemented data platform, simulator, risk gateway, OMS/EMS, or
production deployment yet. The audit found no implemented strategy workflow
consuming the three domain libraries outside their own cross-domain imports.

Local disk use is a different issue: `du` reported approximately 495 MiB for the
checkout, including a 298 MiB `.venv`, 154 MiB `.mypy_cache`, 10 MiB `.uv-cache`,
and 15 MiB `.git`. Generated caches and artifacts dominate local storage.
Removing tracked documentation will not reclaim those caches or erase Git history.

## Findings and decisions

These are maintainability findings under the requested single-person operating
model, not production-incident findings. All are **P2, high confidence, advisory
for this audit**. Their common risk dimension is reliability/operability: routine
changes require coordinating machinery that does not directly prove research or
trading behavior. The protected invariant is that a solo owner can change and
verify an actual capability without unrelated organizational prerequisites.

| Finding | Evidence and concrete maintenance trigger | Recommended decision |
| --- | --- | --- |
| Function policy creates ongoing administrative work | At the audit baseline, the Python policy required individual exceptions for module-level functions. `docs/architecture/python-standards-exceptions.toml` bound symbols to owner, expiry, and AST fingerprint, so editing a legitimate function could require a policy-record update. | Step 1 removes `PYC001` and its exception system. The [current Python policy](../coding_standards/python.md#classes-and-object-design) permits functions and ordinary test functions without registration, keeps cohesive classes, and preserves typing, import-style and docstring rules. |
| Governance is a runtime dependency | [Root project, line 13](../../pyproject.toml#L13) requires the governance distribution; the baseline `src/alpha_research/BUILD.bazel:21` also depended on it. [Compatibility exports](../../src/alpha_research/program_governance/registry.py#L1) and governance tests retain the old namespace. | Move surviving tooling to development-only use. Remove governance facades and `alpha-research-ci` after updating repository callers. Keep the deployable package independent of docs and policy registries. |
| Multiple call layers preserve the old API without adding domain behavior | [Public program loader, line 2096](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L2096) calls a private compatibility function, then a service method, then another private loader. The public and service methods both translate the same error types. | Retire this subsystem where possible; otherwise keep one entry point, one implementation, and one error-translation boundary. Remove test-only compatibility seams with their callers. |
| CI repeatedly checks the same source through different routes | The baseline `tools/governance/src/alpha_research_governance/ci_policy/runner.py:715` ran all pre-commit hooks, Bazel build/test, then `rollback-check`. [Makefile](../../Makefile) makes rollback rerun lint, format, typing, governance, and pytest. [Hosted CI](../../.github/workflows/ci.yml) also runs separate affected and full jobs. | Use one required source-validation job and one build/install smoke check. Remove the custom affected-target scheduler and permanent second build backend after proving replacement coverage. |
| Tests freeze repository shape and historical status | [Root command test, line 56](../../tests/engineering/test_root_commands.py#L56) asserts an exact command sequence; [package test, line 92](../../tests/engineering/test_package_definition.py#L92) freezes the governance entry-point set; [C03 evidence test, line 90](../../tests/engineering/test_financial_units_evidence.py#L90) requires `partial` status and historical finding IDs. Routine simplification causes failures unrelated to numerical correctness. | Retire obsolete assertions with their contracts. Preserve small tests for real installed imports, command failures, integrity checks, and domain outcomes. |
| Research remains subordinate to a large platform program | [Research program, line 5](../roadmap/research-program.md#purpose) is subordinate to 96 packages; its [enablement map](../roadmap/research-program.md#platform-enablement-map) requires large C–K capability groups. [Roadmap parser, line 924](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L924) requires all 96 IDs. Removing a speculative work package requires parser/policy/test changes. | Replace the executable roadmap with a short, human-maintained backlog for one data source, strategy, and operating target. Implement prerequisites for that workload as it needs them. |
| Active documentation still contains historical execution instructions | [Topology contract, line 78](../architecture/repository-topology.md#canonical-targets-and-enforced-consumers) says the program derives B02 next, while [generated status](../governance/program-status.md) selects C04. Its source-target description also predates C03. | Remove historical delivery narratives from active contracts and eliminate duplicate status fields. Keep one current status/backlog page. |

The CI finding establishes duplicated work from command wiring; no current full-CI
duration or hosted cost was measured. The roadmap finding concerns requirements
for claiming stage completion; existing policy already permits earlier synthetic
experiments. Missing hires no longer block ordinary implementation, and ordinary
changes already avoid per-package evidence packs.

## Target working model

Keep one Python package, one dependency lock, one standard check command, and a
small number of operational entry points. Use the existing uv, Ruff, mypy, pytest,
Hypothesis, and packaging tools. Make can remain a short list of aliases.
Do not add another task framework, policy DSL, or replacement governance service.

The first useful delivery sequence is:

```text
versioned data + explicit availability times
    -> reproducible baseline with realistic costs and accounting
    -> shared strategy logic exercised in replay and paper
    -> build and verify a release
    -> explicit founder activation with enforced limits
    -> reconcile, monitor, stop, recover
```

Keep shared strategy logic in a small number of cohesive classes with typed,
documented methods and low-level functions where appropriate. Use an adapter for an actual
data or broker boundary; introduce a protocol when a second implementation or a
meaningful test boundary needs it. Keep risk enforcement outside strategy decision
logic so the strategy cannot authorize itself. Research does not need a service
mesh, event bus, multi-language schema platform, or distributed build service.
Those remain options when a measured workload requires them.

Use one real deployment target, with the current Mac development environment and
Linux deployment checks as needed. A supervised process with explicit persistent
state is a reasonable starting design for a workload that fits it. Confirm latency,
availability, and broker requirements before choosing its process topology.

| Stage | Minimum useful record and behavior | What should not be a routine prerequisite |
| --- | --- | --- |
| Explore | Hypothesis, data provenance, explicit timestamps, simple baseline; secrets kept out of source. | Completing a platform package catalog or writing a model-review report for every exploratory run. |
| Compare/select | Append-only record of compared trials, code/config/data identity, seed, split rules, net results, costs and sensitivity; protect the final holdout from tuning. | An experiment-registry service or institutional acceptance state machine. |
| Paper/replay | Same strategy logic; verify order sizing, costs, positions, stale-data behavior, duplicate handling, disconnect/restart, and reconciliation. | A second production implementation of the strategy or irrelevant asset-class certification. |
| Deploy | Build once; record artifact digest, commit, dependency lock, config/model/data references, limits, environment and rollback artifact; test installation and state compatibility. | Per-library release report packs or an organization-wide signing platform before selecting a real release path. |
| Activate | Founder makes a separate explicit activation decision. Default trading off; enforce order/notional/exposure/loss limits outside strategy logic, safe credential scope, restart reconciliation, and a tested stop/cancel path. | Signatures from fictitious independent employees. Update the current operation policy before adopting founder activation. |
| Monitor/recover | Alert on stale feed, missing heartbeat, reject/error bursts, position/cash mismatch and limit breaches; retain orders/fills and state. Test alert delivery, backups/restore, stop, rollback and reconciliation before resuming. | A general KPI warehouse, mandatory distributed traces, or an SRE program for every library. |

Keep one release/activation record and one runbook per actual deployed strategy or
service. Choose numeric operating thresholds for the actual venue and strategy
before activation. A canary should have explicit exposure and duration bounds,
stop conditions, and post-run reconciliation. If the sole operator is unavailable,
the system needs a defined safe response; an unowned alert is not a control.
The current repository does not implement these runtime behaviors yet.

Actual data-use, venue, security, and legal obligations remain applicable. This
plan removes internal ceremony; it does not certify compliance or live readiness.

## Code and tooling disposition

Paths in this table are relative to the repository root. Retire a feature's
configuration, callers, build targets, tests, and documentation in the same slice.
Here `tools/governance/.../` abbreviates
`tools/governance/src/alpha_research_governance/`.

| Area | Disposition | Replacement or condition |
| --- | --- | --- |
| `src/alpha_research/{instrument_identity,venue_calendar,financial_units}/` | Keep initially. | Preserve units, strict external validation, temporal identity, UTC/DST, bounded calendars, rounding and independent goldens. These protect numerical/model validity and data integrity. |
| Governance modules under `src/alpha_research/`, including `_models.py` | Remove compatibility surface after caller migration. | Nine implemented domain Python files do not import these facades. Search imports, string module paths and entry points; migrate remaining tests/tools together. Check known external consumers before dropping a promised public API. |
| `tools/governance/.../{program_governance,inventory,repository_topology}/` | Retire active registries and their parsers. | One backlog; version references in actual research/release records; normal package imports. No source-file ownership registry for one owner. |
| `tools/governance/.../{change_risk,evidence}/`, `operating_model.py`, `ownership_governance.py` | Replace the general framework with a short development/activation policy. | Retain the current short PR template as guidance. CI result plus commit identifies development validation; validate only the manifest that an actual release consumer relies on. |
| `tools/governance/.../security_controls/` and associated inventory/control maps | Retire the institutional registry after extracting real controls. | One concise security/operations runbook: secrets, access, data rights, deployment privileges, dependency issues and response. Preserve enforceable runtime checks. |
| `tools/governance/.../engineering_standards/` | Preserve typing, import-style and docstring enforcement in a compact checker; retire the surrounding policy/exception/debt framework. | Keep configured Ruff, strict mypy and their current checking scope. Retain custom rules where equivalent tool coverage is unproven. Remove `PYC001` registration independently of the protected clarity rules; retain numerical guidance and behavioral tests. |
| `tools/governance/.../ci_policy/` | Retire scheduler, policy parser, and custom KPI/event framework. | Direct CI steps and retained CI logs. Keep secret detection and failure propagation through existing tools. |
| `tools/governance/.../remote_execution/` | Retire now. | Remove remote job/sharding/cache-policy surfaces. Reconsider only after local/hosted build measurements demonstrate a need. |
| `tools/governance/.../{dependency_admission,artifact_supply_chain}/` | Shrink substantially; preserve current restrictions until replaced explicitly. | Frozen dependencies, vulnerability checks, relevant license/source decisions, and build/install verification. For deployment, retain artifact identity and trusted-origin/integrity verification; use existing tool outputs instead of a general evidence framework. |
| `architecture_governance.py` | Keep link validation; retire mandatory ADR schemas and approval parsing. | A small local-link check and a few short decisions explaining expensive-to-reverse choices. |
| Bazel files, `requirements.bazel.txt`, `tools/build/`, SQL/proto build probes | Retire after uv path proves the retained capability set. | Frozen uv environment, pytest, and a wheel built and imported outside the checkout. Keep real compatibility tests if a production schema or generated artifact is later introduced. |
| `flake.nix`, `flake.lock`, `.envrc`, `environments/dev/` | Remove the duplicate bootstrap path after one clean Mac/Linux bootstrap succeeds. | Document Python/uv prerequisites and the single setup command. Keeping Nix is reasonable if it is the founder's chosen environment; then it must replace, rather than duplicate, the maintained setup contract. |
| `tools/typing/` and strict typing configuration | Preserve enforcement and consumed native contracts. | Keep current strict settings, including `disallow_any_expr` and `disallow_any_decorated`, across source, tests, tooling and stubs. Remove a stub only with its retired dependency or consumer. Simplify redundant type plumbing without weakening the checked contract or runtime validation. |

QuantLib requires a separate, explicit decision. The [current admission, line 246](../architecture/dependency-admission.toml#L246)
permits isolated development/CI through **2026-10-04**, records unverified
source-to-wheel binding, and blocks graph artifact releases. Deleting its validator
would not resolve that uncertainty. Keep this decision and relevant evidence while
QuantLib is retained. If the first strategy does not use day-count or settlement
conventions, consider isolating the native convention adapter as an optional
dependency; update eager imports, extras, locks and both base/extra install checks.
Do not rewrite financial conventions from scratch merely to remove the dependency.

## Reduce call hierarchy without destroying useful boundaries

The [program loader](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L2074)
has this concrete path, excluding the import-only facade:

```text
load_program(...)
  -> _load_program(...)                         # compatibility seam
    -> ProgramRepository(...).load_program(...)
      -> ProgramRepository._load_program(...)
        -> parsing/validation helpers
```

Retiring the program framework eliminates the path. If temporarily retained,
call `ProgramRepository(root).load_program(path)` directly and translate boundary
errors once. Similarly, [classify_change, line 102](../../tools/governance/src/alpha_research_governance/change_risk/classification.py#L102)
only constructs a classifier and calls it: retain the reusable policy-owning
class as the canonical API when classification remains a useful capability; remove
its forwarding function after migrating callers. Retire the class itself if the
whole policy capability is removed. Re-export modules are import indirection, not extra runtime calls.

For retained code:

- Inline a one-caller wrapper when it only forwards arguments or repeats an error
  translation. Keep helpers that name a real algorithm or isolate I/O.
- Keep classes for meaningful concepts and related behavior, including catalogs,
  broker sessions, persistence and cohesive validation. Consolidate classes only
  when their responsibilities and lifetime agree. Remove one-method forwarding
  classes and duplicate parser/report types before changing useful domain classes.
  Keep low-level functions where clearer; do not enforce a call-depth quota.
- Validate external data once at each trust boundary. Keep cross-field/domain
  invariants and validation of unsafe copied/constructed instances where callers
  can supply them. Do not replace Decimal/Fraction arithmetic with floats to save lines.
- Preserve enforced Google-style docstrings and all applicable sections. Remove
  redundant forwarding APIs together with their duplicated documentation. For
  surviving APIs, explain intent, units, time semantics, mutability, side effects,
  errors and non-obvious rationale; do not strip useful prose to reduce line count.
- Avoid a generic shared model framework as a cleanup shortcut. C01/C02 currently
  permit trusted Pydantic copy behavior; C03 overrides `model_copy` to revalidate.
  Preserve or intentionally migrate those distinct contracts before consolidating.
- Keep array-based research calculations practical. Boundary records need strict
  validation; an internal numerical array or test fixture does not need a bespoke
  Pydantic service and exception registration merely to satisfy style rules.

## Test cleanup by protected behavior

The observed pytest collection contained 723 cases: 536 engineering and 187 domain.
This includes optional markers and excludes the separate Bazel build probes;
it is not a full Bazel test count. Many engineering tests are meaningful while
their corresponding framework remains supported. Remove them because a requirement
is retired or a stronger boundary check covers it, not because they are numerous.

| Existing tests | Assessment and action | Smallest evidence to retain |
| --- | --- | --- |
| `tests/unit/test_instrument_identity.py` | Keep: meaningful temporal, ambiguity, correction-history and checksum behavior. | Golden resolution, symbol reuse at half-open boundaries, invalid/overlapping/cyclic mappings and round trips. |
| `tests/unit/test_venue_calendar.py` | Keep: meaningful adapter/timezone and session-state behavior. | DST gap/fold, holidays, half-days/breaks, overrides, stale/invalid source data, market-state boundaries and version compatibility. |
| `tests/unit/test_financial_units.py` | Keep: meaningful financial invariants and native boundary behavior. | Hand-calculated day counts, rounding/ticks/lots, currency mismatch, exact-context independence, settlement coverage, native failure and copy-validation cases. |
| `tests/engineering/test_{instrument_identity,venue_calendar,financial_units}_evidence.py` | Retire after historical package profiles cease to be active contracts. These check synthetic partial-status/report bindings, not the calculation oracle. | Preserve the three golden datasets and their behavioral consumers. Retain digest verification where an actual runtime/release consumes a digest. |
| `test_python_{debt,source_standards,typing}.py`, relevant `test_engineering_standards.py` cases | Keep coverage for typing, import style, docstrings and enforcement wiring. Retire tests only for removed exception/fingerprint/policy behavior or proven duplicate coverage. | Passing/failing fixtures for the retained standards, including alias/import/docstring edge cases; configured Ruff/mypy runs at unchanged strictness and scope; native-stub conformance for retained adapters. |
| `test_root_commands.py`, `test_package_definition.py` | Replace exact command/dependency-list snapshots. | Build a wheel, install it in a clean environment without governance, import public runtime APIs, exercise one real CLI boundary, and ensure check failures fail CI. |
| `test_{program,inventory,ownership,evidence}_governance.py`, `test_package_evidence.py`, `test_change_risk.py`, `test_repository_{governance,topology}.py`, `test_security_controls.py` | Retire with the removed registries/policies. | Tests for retained release parsing, path/integrity checks, and actual execution controls. Do not port historical finding IDs or reviewer matching to a new framework. |
| `test_ci_policy.py`, `test_ci_runner.py`, `test_remote_execution.py` | Retire custom scheduling/sharding/policy tests with those features. | A real required CI job, checked artifact installation, secret scanning, and observable nonzero failure behavior. |
| `test_dependency_admission.py`, `test_artifact_supply_chain.py` | Reduce after replacement release/dependency boundaries exist. Tamper, unexpected source, unsafe path and invalid identity tests remain useful for any retained consumer. | Focused success plus rejection cases at the actual artifact consumer; current unresolved dependency decision remains visible. |
| `tests/build/` and build-only SQL/proto fixtures | Retire Bazel environment/probe tests with Bazel. They protect build properties, so uv pytest alone is not proof of equivalence. | Clean bootstrap and installed-artifact smoke tests on supported environments; migrate any still-required real generation or isolation guarantee explicitly. |
| Performance-marked tests | Keep out of the default correctness suite, as configured today. | Run the affected benchmark for a material performance change; remove obsolete governance benchmarks with their code. |

Do not delete tests of accounting, time availability, duplicate orders/fills,
limit enforcement, reconciliation or recovery to hit a test-count target. Most
execution/research pipeline tests do not exist yet: add them with those behaviors,
using a few decisive scenarios rather than testing every helper independently.
Parameterize repeated cases only when it makes the test easier to maintain;
parameterization alone does not reduce executed work.

## Documentation disposition

Aim for roughly 8–12 active explanatory pages, plus concise retained decisions and
necessary fixtures/reference records. This is a planning target, not a CI quota.

| Current material | Target |
| --- | --- |
| `docs/README.md` | Keep as the single entry point: current capabilities, setup, check, research, paper, deploy, stop and monitor commands as they become real. A root README can be a small pointer. |
| Architecture overview, principles and broad contracts | One current architecture page. Keep the three domain-contract pages for units, identity and calendars. |
| `docs/coding_standards/{README,python}.md` plus enforcement prose | One concise engineering guide preserving enforced function typing, import organization, explanatory Google-style docstrings, cohesive class design, boundary validation, financial/time invariants and behavior-based tests. Retire unused C/C++ and Rust guides until those languages enter the project. |
| Governance workflow, ownership, change classes, quality gates, threat/control maps | One workflow page and one operational runbook with concrete triggers; remove repeated role and gate catalogs. |
| 96-package roadmap, generated program state, large research-stage framework | One prioritized backlog and one practical research protocol. Start with the smallest costed PIT baseline; preserve trial/holdout discipline without requiring all platform services. |
| ADRs and completed migration diaries | Keep only decisions that still explain current constraints. Historical material is recoverable from this baseline commit; avoid a duplicate archive tree in the active checkout. |
| Blueprint PDF (489 KB) | Retire as active implementation authority. Keep in Git history or a deliberately chosen reference location after removing policy, test and documentation dependencies on it. |
| Evidence examples and native signature/source records | Remove synthetic institutional packs after their consumers retire. Keep unresolved admission evidence, financial goldens and actual release/research identities. Store future large run outputs outside Git with durable references and appropriate retention. |

Do not simply delete everything under `docs/governance/evidence/`: some native
signature and source-review files support the still-active QuantLib decision.
Expired CI logs also cannot serve as the only durable provenance for a deployed
strategy. Retain the small release identity and the data/artifacts needed to
reproduce it for its operational lifetime and applicable retention needs.

## Implementation sequence

Each row is a bounded cleanup slice, not a new governance gate. Use an ordinary
branch and reviewable commits; the recorded baseline provides history and reversal.
Avoid a permanent compatibility layer or a second policy profile as the migration result.

| Order | Concrete changes | Exit evidence |
| --- | --- | --- |
| 1. Preserve clarity; remove exception bureaucracy — complete | Recorded the protected typing/import/docstring rules and their existing tests. Retained useful class organization; removed `PYC001`, its 486 function-exception records, reconciliation/fingerprint machinery and exclusive tests. | Strict typing, retained import/docstring fixtures and domain tests pass; ordinary functions need no expiry/fingerprint record. See [step 1 results](#step-1-results). |
| 2. Establish the smaller CI/build path — implemented | Inventoried Bazel guarantees, made frozen uv source checks and installed-wheel smoke validation authoritative, retained security checks, and updated Make, workflow, hooks and affected tests together. Removed Bazel, remote execution, the custom scheduler and the Nix bootstrap path. | Fresh local macOS setup, focused affected-code checks, external wheel imports and failure propagation passed. Hosted macOS/Linux jobs are configured but have not run for this change. Every former Bazel-only guarantee has a replacement or explicit retirement decision. See [step 2 results](#step-2-results). |
| 3. Retire policy frameworks and runtime coupling | Replace development, release and founder activation rules; remove program/ownership/topology/inventory/role and historical evidence machinery. Update all registries that still exist in that slice. Move surviving tools out of runtime dependencies, remove facades/entry points, regenerate the one lock. | Domain package installs without governance/docs; current tests and entry points use supported imports; no active check requires 96 IDs, legacy finding IDs or unavailable staff. QuantLib restriction remains enforced or is explicitly resolved/revised. |
| 4. Consolidate docs and fixtures | Replace active overview/workflow/backlog pages, remove stale package narratives and synthetic packs, prune unused ADRs/blueprint references. Remove retired tests and their build/data declarations together. | Local links pass; retained goldens and real release/admission evidence remain reachable; all setup/operation instructions refer to actual commands or are clearly marked planned. |
| 5. Reduce classes and finish the line budget | Remove forwarding wrappers, duplicate error translation and duplicate parser/report/model classes; retain useful classifications and cohesive services. Keep typing, import-style and docstring enforcement unchanged. Review optional native adapters without altering domain contracts implicitly. | Governance implementation is below 3,000 physical lines with fewer classes; clarity checks and domain invariants pass. Native checks and base/optional installs pass if changed. Show simpler callers and preserved explanations. |
| 6. Resume strategy delivery | Build one data-to-net-report baseline, then paper/replay and the minimal deploy/activate/monitor path described above. Add missing safety tests as those behaviors appear. | A reproducible research result first; later, a bounded paper/canary run with reconciliation, alerts, stop and rollback evidence. Do not spend the next cycle building a replacement governance framework. |

During migration, remove a required check only when its requirement is retired or
its replacement has passed. A check that remains required must not be disabled
merely because the migration makes it fail. Keep policy changes and affected
callers/tests coherent within each slice. Hosted CI runs the full required lane;
local validation for step 2 runs only affected tests, as requested by the founder.
Preserve the hosted required-check name or update its
branch rule with the replacement job, where such a rule exists. Do not run obsolete
and replacement stacks forever.

### Step 1 results

Implemented on 2026-09-07 using two Luna subagents at extra-high reasoning, with
integration review and focused validation. The
[protected clarity checks](../architecture/engineering-standards.md#protected-clarity-checks)
record the retained rules and their regression coverage. Python and engineering
policies now permit ordinary functions without registration; typing, import
organization and applicable Google-style docstrings remain enforced.

Removed all 486 function exceptions and the 5,349-line register. Replaced
`python_debt.py` with `python_standards.py`: the repository scanner shrank from
258 to 66 physical lines and from four classes to one. It reports source findings
directly, scans new `.py`/`.pyi` files, and fails on missing roots or unreadable
source. The source checker no longer emits `PYC001`; retained diagnostic identities
are unchanged. Build data, test entry points, topology ownership and hook selection
were updated together. No clarity checker was replaced with an assumed equivalent.

Validation used the existing pinned environment and current checkout code via
`PYTHONPATH=src:tools/governance/src`. Only relevant tests were executed:

| Validation | Result |
| --- | --- |
| `pytest -q tests/engineering/test_python_standards.py tests/engineering/test_python_source_standards.py tests/engineering/test_engineering_standards.py` | 64 passed; one performance case deselected. |
| `pytest -q tests/engineering/test_python_typing.py tests/unit/test_instrument_identity.py tests/unit/test_venue_calendar.py tests/unit/test_financial_units.py` | 202 passed; three performance cases deselected. |
| Bazel `//tests/engineering:python_standards_test` and `//tests/engineering:engineering_standards_test`, with `--config=ci` | Both passed; the renamed entry point ran all 43 scanner tests. The policy target ran 20 cases, skipped its existing repository-only case, and deselected one performance case; repository validation passed locally. |
| `mypy --strict src tests tools/governance/src tools/typing/stubs` | Passed on all 141 current source files with the unchanged strict configuration. |
| Ruff check and format check on the five changed Python files | Passed. |
| Engineering-standards, repository-topology and architecture/link validators | Passed without the exception register. |
| Pre-commit configuration and engineering-hook selection comparison | Valid; every retained tracked path and new Python/stub probe keeps its prior selection. Only the retired register drops out. |
| Previous/current source-checker comparison | All retained findings matched across 46 existing snippets under runtime, test and stub paths: 138 comparisons. Only `PYC001` findings disappeared. |

No full pytest suite, full CI lane, performance suite, or native-stub conformance
run was needed for this slice. Domain implementations, native boundaries,
dependency pins and lockfiles were unchanged. Step 2 is recorded below;
steps 3–6 remain separate work.

### Step 2 build-contract disposition

The step 2 inventory distinguishes retained behavior from guarantees specific to
the retired build system. The smaller path does not claim Bazel-equivalent
hermeticity or a Nix-pinned operating system.

| Previous consumer | Protected behavior and step 2 disposition |
| --- | --- |
| Bazel Python unit and engineering targets | Retain the applicable pytest cases and independent financial goldens. Invoke pytest directly in the frozen uv environment. Retire only tests for removed scheduling, sharding, bootstrap and build-probe contracts. |
| Build-graph and developer-environment probes | Replace the dual-backend and Nix/Bazel version snapshots with frozen uv setup, locked dependencies, and installed-wheel validation. Python and uv remain pinned; the host OS and ordinary shell utilities are prerequisites rather than Nix-managed inputs. |
| Bazel sandbox/runfiles probes | Retire the Bazel-specific guarantee that tests see only declared runfiles and a filtered host environment. Installed-wheel smoke checks instead verify package origins outside the checkout using isolated Python. These checks do not provide a general filesystem or process sandbox. |
| Synthetic SQL template, substitution rejection and Buf schema probes | Retire these fixtures with their unused generation/toolchain capability. There is no production SQL generator or protobuf schema consumer to migrate. A future real generator or schema must supply its own compatibility tests. |
| Affected-target scheduler, full/fast equivalence, event records | Replace custom selection and event emission with direct CI commands and ordinary CI logs. Preserve the existing authoritative hosted check name and nonzero failure propagation. |
| Remote cache, deterministic shards, quarantine and local fallback | Retire the unused remote-execution capability, credentials, policy and exclusive tests. There is one local/hosted uv path; remote build claims and automatic retries are not retained. |
| Secret scanning, security analysis, dependency admission and artifact integrity | Retain fail-closed scanning and existing security/admission/integrity checks. Removing Bazel/Nix lock surfaces does not resolve the QuantLib source-to-wheel uncertainty or authorize releases. |
| Native type stubs and runtime imports | Retain the configured strict typing scope, native stubtest and public domain APIs. Verify distribution imports from an installed environment. Governance runtime decoupling remains step 3. |

Source freshness is part of the new build contract. Both project manifests use
explicit uv cache keys for their source files, following the
[uv cache-key behavior](https://docs.astral.sh/uv/concepts/cache/). A disposable
checkout created a fresh Python 3.12.14 environment with 75 locked packages. After
a nested source-file edit in each local distribution, another frozen noneditable
run rebuilt both packages; installed source-file SHA-256 digests matched the edits.
This probe modified only temporary copies of the source.

### Step 2 results

Implemented on 2026-09-07 using three Luna subagents at extra-high reasoning,
with integration review and affected-code validation. `make check` now composes
one source-validation path and one installed-wheel smoke check. Hosted CI runs
source validation once, then macOS/Linux wheel checks. The `macos-14` runner matches
the admitted Apple Silicon platform in the
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The existing required-check
name, `Authoritative merged-result full lane`, is preserved and explicitly fails
if either upstream source validation or macOS smoke fails. Pull-request validation
still checks the actual merged commit and its base/head parents.

The local hook set shrank from 23 to 11, grouping the retained governance checks.
Removed the custom affected-target scheduler, event-log machinery, remote execution,
Bazel files and build probes, Nix files and bootstrap scripts, and their exclusive
tests and policy records. Historical build decisions remain clearly marked until
the documentation cleanup. Native stubs and typing/import/docstring enforcement
keep their existing scope and strictness.

Dependency admission now validates the single `uv.lock`. Artifact verification
binds that lock and the root project manifest, retains Syft/Cosign identities and
integrity checks, and records the normalized uv build command. Artifact manifests
use schema v2; old v1 bundles require rebuilding under the new contract. Actual
QuantLib admission still permits only bounded development/CI bootstrap and blocks
artifact releases. No admission uncertainty was waived.

Only relevant pytest files and cases were run. The validation groups below overlap
where later focused runs verify integration fixes; they are not an additive suite
count.

| Validation | Result |
| --- | --- |
| Dependency-admission and artifact-supply-chain tests | 130 passed, preserving success, tamper, unsafe-path, identity, audit and rejection cases. |
| Affected inventory, program, topology, ownership, CI, engineering-standards, package-definition and root-command tests | 136 passed; five integration/performance cases deselected by the default marker filter. |
| Final focused CI, package-definition and root-command follow-up | 17 passed after the integration fixes. |
| Python-typing tests after removing retired lock-parser cases | 10 passed. |
| Ownership hook integration case | One passed after allowing dependency downloads for its temporary checkout. |
| Standards repository and CLI cases after removing obsolete Bazel skips | Two passed. |
| Native-stub conformance for the retained installed dependencies | `mypy.stubtest` passed for QuantLib, exchange_calendars and pandas: 1,548 modules checked. |
| Fresh macOS frozen setup and source-cache refresh | Passed with Python 3.12.14; both installed distributions refreshed after nested source edits in a disposable checkout. |
| Wheel build and isolated installation | Both wheels built with the locked backend, 22 external runtime packages installed with hashes and binary-only enforcement, and all 24 installed distributions passed dependency compatibility checks. Isolated imports and the installed CLI rejection case passed outside the checkout. |
| Actual hosted merge-identity shell step | Accepted matching checkout/base/head identities and rejected a wrong PR head and a wrong checked-out merge commit. |
| Retained validators | Architecture links, topology, inventory, ownership, program and engineering standards passed. Dependency admission and artifact policy CLIs passed with Cosign 3.1.3; QuantLib remained release-blocking. |
| Static and configuration checks | Strict mypy, Ruff and focused Bandit checks passed on affected Python files. Frozen lock verification, pre-commit configuration validation, tracked-file secret scanning and scanning the new smoke module passed. |

Hosted CI has not executed this change. Local macOS evidence establishes the
replacement path here; Linux and hosted macOS validation remain pending in the
configured jobs. No full local pytest suite, full CI lane, performance suite,
or artifact signing/publishing lifecycle was run.
Financial implementations, the three domain goldens, dependency pins, `uv.lock`
and existing admission/evidence files are unchanged. Governance remains a runtime
dependency until step 3.

## Success measures and stopping point

The governance implementation limit is **strictly below 3,000 physical source
lines (at most 2,999)**, on the same counting basis as the 31,309-line audit
baseline: include comments, blank lines and docstrings. Count all retained
handwritten governance implementation, including shared helpers, compatibility
code, owned stubs and scripts moved elsewhere. Moving code to another directory
or embedding it in configuration does not remove it from the budget. Count
third-party dependencies separately; do not vendor or relabel owned code to hide it.
Governance tests and declarative configuration/docs are reported separately and
reduced by retained behavior; the 3,000-line cap here concerns implementation.

A starting allocation reserves room for explanatory code and docstrings:

| Retained responsibility | Planning allowance in physical lines |
| --- | ---: |
| Typing/import/docstring enforcement beyond configured Ruff/mypy coverage | 1,400 |
| Actual dependency/release identity and integrity checks | 600 |
| Local documentation-link validation | 250 |
| CLI/check orchestration and shared boundary records | 250 |
| Unallocated headroom | 499 |
| **Maximum combined implementation** | **2,999** |

Allocations may move between responsibilities; the combined cap stays fixed.
If retained correctness and clarity do not fit, remove more obsolete capability
or use an equivalent existing tool. Do not compress statements, delete explanatory
docstrings, weaken typing, or merge unrelated responsibilities just to pass the count.
This budget is a design estimate, not evidence that a replacement already fits.

Additional success measures:

- Reduce governance classes substantially from the measured 188. Aim for roughly
  15–25 remaining class definitions, including models, protocols and exceptions,
  as a planning guide. Preserve distinct concepts when useful; avoid a hard class
  quota that encourages oversized classes or erases important types.
- Preserve enforced function typing, import style and explanatory docstrings at
  the current strictness and scope throughout the cleanup.
- Reduce active explanatory documentation to roughly 8–12 pages and retire the
  exception register. Keep small reference evidence where it still has a consumer.
- Have one required CI validation route, a small local hook set, and no governance
  runtime dependency. Keep only one supported build/setup contract.
- Make a normal strategy change touch strategy code/config, its relevant tests,
  and at most its short research record or runbook when behavior requires it.
- Measure CI before/after on the same machine and revision class. An initial goal
  is warm local checks within a few minutes and hosted validation within 10 minutes;
  adjust from actual bottlenecks. No current full-CI baseline was captured here.
- Track removed files/lines and simplified workflows. Do not set a required test
  count or replace policy bureaucracy with a permanent cleanup-metrics service.

Stop the broad cleanup once the standard development path is simple, runtime code
is isolated, obsolete frameworks are gone, governance implementation is below
3,000 lines, and the retained clarity requirements pass. Defer deeper domain refactors until
they make the next strategy task materially easier.

For local disk reclamation, optionally clear reproducible `.mypy_cache`,
`.pytest_cache`, `.ruff_cache`, `.uv-cache`, old `build/` and `dist/` outputs after
checking they contain nothing needed. Current non-environment caches/artifacts
offer roughly 165–170 MiB of potential reclamation, at the cost of cache rebuilds.
Removing `.venv` could reclaim another 298 MiB but requires reinstalling it.
No cache deletion or Git-history rewrite is part of this audit; the approximately
15 MiB Git directory does not justify a disruptive history rewrite.

## Validation and limits

The following records the original documentation audit; implementation validation
is recorded in [step 1 results](#step-1-results) and [step 2 results](#step-2-results).
The audit used the local checkout
and existing Python environment:

```sh
git status --short
git ls-files
git count-objects -vH
du -sh . .git .venv
.venv/bin/python -m pytest --collect-only -q -o addopts='' -p no:cacheprovider
PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q tests/unit -p no:cacheprovider --durations=5
PYTHONPATH=src:tools/governance/src .venv/bin/python -m alpha_research_governance.architecture_governance
```

Collection: **723 cases**. Focused domain validation: **184 passed, 3 deselected,
2.36 seconds**. The deselections are the three performance-marked domain tests.
Architecture/link validation passed for **14 ADRs** before this plan was added;
the same checker also passed after adding the plan and its index link. File, AST,
and TOML inventories supplied the footprint and exception counts above.

Review profile: research/domain foundations, Tier 2 for retained financial and
temporal contracts; the initial audit changed only documentation. The audit
traced representative loader, adapter, model, test, build and policy paths. It is
not an exhaustive correctness review of all 55,376 Python lines. Existing domain
test evidence is useful and locally passing; policy-test removals are conditional
on retirement; live risk/recovery evidence is not yet implemented.

No full Bazel/Nix/hosted CI, fresh install, dependency audit, performance suite,
broker connection, deployment or live-control exercise was run. Source-path
injection above deliberately tested current checkout code; it does not demonstrate
installed-package isolation. The implementation slices must establish that boundary.
