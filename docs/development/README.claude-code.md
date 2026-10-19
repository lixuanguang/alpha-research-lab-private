# Claude Code development and review process

Use Claude Opus 5.5 to develop and review this systematic-trading monorepo with
explicit domain contracts, proportionate checks, and review evidence tied to the
delivered revision.

Owner: repository founder. Status: operating guide and copy-paste prompt library.
Existing auditor skill, reviewer agent, and helper scripts inspected on 2026-10-08.
Claude product documentation was checked on 2026-10-07. This guide reuses the
checked-in configuration; file presence does not by itself establish discovery
in a running Claude session or completion of an audit.

This guide implements the existing [development workflow](../governance/workflow.md).
The owning repository contracts take precedence if this guide becomes stale.
It does not add institutional approval gates or grant deployment or trading authority.

## Contents

- [1. Model and reasoning levels](#1-model-and-reasoning-levels)
- [2. Repository context and commands](#2-repository-context-and-commands)
- [3. Verify and reuse the existing setup](#3-verify-and-reuse-the-existing-setup)
- [4. Initial audit and remediation roadmap](#4-initial-audit-and-remediation-roadmap)
- [5. Per-task development and review loop](#5-per-task-development-and-review-loop)
- [6. Optional additional review tools](#6-optional-additional-review-tools)
- [7. Milestone audits and configuration upkeep](#7-milestone-audits-and-configuration-upkeep)
- [8. Severity and domain review guidance](#8-severity-and-domain-review-guidance)
- [9. Daily checklist](#9-daily-checklist)

## 1. Model and reasoning levels

### Select Opus 5.5 explicitly

From the repository root, start Claude Code:

```sh
claude --model claude-opus-5-5 --effort medium
```

For an existing Claude session, enter these separately:

```text
/model claude-opus-5-5
/effort medium
```

These use the Anthropic model identifier. Other providers may require their own
deployment identifier. Verify the selected model in the session; the `opus` alias
can change. Current documentation requires Claude Code 2.1.280 or later for Opus
5.5. [Model selection documentation](https://code.claude.com/docs/en/model-config#model-aliases)

Opus 5.5 supports `low`, `medium`, `high`, `xhigh`, and `max`; its default is
`medium`. Set actual effort with `/effort`, not with a heading inside a prompt.
Typed settings below `max` can persist per model; `max` is normally session-only.
Environment or organizational settings can affect the effective level. Verify it
after changing it. [Effort documentation](https://code.claude.com/docs/en/model-config#adjust-effort-level)

### Recommended effort policy

The following is this guide's recommendation for this repository, not a claim that
a model setting guarantees correctness. Select by uncertainty and consequences.
Keep a useful setting through a coherent task rather than switching for each command.

| Work | Default effort | Escalation |
| --- | --- | --- |
| Existing setup verification | `high` | `xhigh` for conflicting contracts |
| CLAUDE.md upkeep and justified configuration changes | `high` | `xhigh` for substantive policy ambiguity |
| Initial or milestone domain audit | `xhigh` | `max` for a specific unresolved critical question |
| Validate disputed audit findings | `high` | `xhigh` for temporal, numerical, or stateful reasoning |
| Remediation roadmap | `high` | `xhigh` for cross-package ordering or state transitions |
| Scope and straightforward design | `high` | `xhigh` for material trading semantics |
| Financial, PIT, concurrency, or recovery design | `xhigh` | `max` only if difficult ambiguity remains |
| Routine implementation and local simplification | `medium` | `high` for interacting state; `xhigh` for difficult semantics |
| Select tests and define independent expectations | `high` | `xhigh` for financial or temporal oracles |
| Execute already-selected checks and summarize results | `low` | `high` when diagnosis is needed |
| Diagnose unexpected failures | `high` | `xhigh`, then `max` if justified by unresolved complexity |
| Fresh code and domain review | `high` | `xhigh` for material trading or recovery changes |
| Resolve confirmed findings | `high` | `xhigh` for difficult semantic fixes |
| Prepare PR text | `medium` | `high` if evidence or scope needs reconciliation |

Use `/effort xhigh` or `/effort max` for an escalation, then restore the normal
level afterwards. Do not make `max` a permanent requirement for anything mentioning
trading. Anthropic notes diminishing returns and possible overthinking at `max`.
[Effort selection guidance](https://code.claude.com/docs/en/model-config#choose-an-effort-level)

### How to use the prompts

Run slash commands in Claude Code, shell commands in a terminal, and paste the
prose prompts into the indicated session. Replace placeholders such as `<TASK>`,
`<BASE>`, `<HEAD>`, and `<PR_NUMBER>` before use. Shell examples containing angle
brackets are templates, not literal commands to execute.

The auditor and reviewer already exist. Verify their discovery once if needed,
then start at section 5 for a change, or section 4 for a bounded audit. Reuse a
valid previous audit instead of restarting it because this guide changed.
Sections 6 and 7 are conditional; no skill-creation stage is required.

For a material change, the normal sequence is:

```text
Scope/design: high (xhigh for difficult semantics)
  -> implement: medium/high
  -> affected checks: low for execution, high for diagnosis
  -> existing trading-reviewer: high/xhigh
  -> resolve findings: high/xhigh
  -> final evidence and PR: low/medium, plus required CI
```

The installed skill owns review method, heuristics, and report structure. This
README owns the workflow and the section 8 priority/domain guidance that the
skill references. Supply task-specific scope and evidence in prompts instead of
recreating the skill's full checklist.

## 2. Repository context and commands

### Sources of truth

| Topic | Owning source |
| --- | --- |
| Current capability and roadmap | [Documentation index](../README.md), [roadmap](../roadmap/overview.md) |
| Engineering rules and format replacement | [Engineering standards](engineering-standards.md) |
| Implementation, merge, release, activation | [Development workflow](../governance/workflow.md) |
| Environment and installed execution | [Environment](environment.md) |
| Test discovery and maintained integration paths | [Testing](testing.md) |
| Current package boundaries | [Architecture overview](../architecture/overview.md) |
| Temporal meaning and availability | [PIT semantics](../data/point-in-time-semantics.md) |
| Research selection and empirical claims | [Study protocol](../research/study-protocol.md) |
| Actual check commands and CI trigger | [Makefile](../../Makefile), [CI workflow](../../.github/workflows/ci.yml) |
| PR structure | [PR template](../../.github/pull_request_template.md) |

Current supported delivery concerns OKX/Bitfinex spot research and paper/shadow
trading. Review implemented paths against their contracts. Mark future or
unqualified live capabilities explicitly; do not report their absence as a defect
unless the change promises them. Live activation remains outside this workflow.

The engineering guide requires more than generic KISS/SOLID advice: cohesive
classes own reusable behavior, module-level functions perform real orchestration,
consumers use supported owner APIs, and numerical, temporal, typing, and docstring
contracts remain intact. Link these rules from agent instructions rather than
maintaining competing copies.

### Local feedback and the complete gate

Run commands from the repository root. Use the pinned environment and
`--no-editable` for direct `uv run` and `uv sync` commands. Do not synchronize an
environment while tests, notebooks, or workers are using it. Follow the environment
guide for separate installed/signed runs; existing Make targets can change the
development environment's install mode.

| Purpose | Command template |
| --- | --- |
| Affected lint | `uv run --frozen --no-editable ruff check <paths>` |
| Affected formatting check | `uv run --frozen --no-editable ruff format --check <paths>` |
| Affected strict typing | `uv run --frozen --no-editable mypy --strict <paths>` |
| Affected ordinary tests | `uv run --frozen --no-editable pytest -q <test-paths>` |
| Affected integration tests | `uv run --frozen --no-editable pytest -q -m integration <test-paths>` |
| Relevant performance tests | `uv run --frozen --no-editable pytest -q -m performance <test-paths>` |
| Complete configured typing, including stubtest | `make typecheck` |
| Engineering rules | `make engineering-standards-check` |
| Documentation-local links and anchors | `make architecture-check` |
| Correctness tests, including integration | `make test` |
| Installed artifact boundary | `make wheel-smoke` |
| Complete local merge-check entry point | `make check` |

Plain pytest excludes integration and performance tests through configuration.
Select affected integration tests explicitly. `make test` includes integration and
excludes performance. Scripts in `tests/integration/consumers/` are not themselves
automatically discovered tests. A passing command with no relevant tests is not
validation. The architecture command checks documentation links; it does not prove
correct dependency direction.

During development, choose affected checks and reverse dependencies. Run complete
static scope for changes to global enforcement. Preserve the complete hosted merge
gate; use local `make check` when reproducing that gate is useful. Performance and
external-service qualification require their own evidence when affected.

## 3. Verify and reuse the existing setup

### 3.1 Confirm the existing components

**Effort:** `high`. **Mode:** read-only. **Result:** confirmation that the existing
configuration is discoverable, with only concrete gaps reported.

These components are already present in the repository:

| Component | Existing responsibility |
| --- | --- |
| [Auditor skill](../../.claude/skills/systematic-trading-platform-auditor/SKILL.md) | Diff review and bounded audit modes, domain routing, evidence rules, findings and report format |
| [Review heuristics](../../.claude/skills/systematic-trading-platform-auditor/references/review-heuristics.md) | Repository-specific false positives, declared limitations, and patterns worth tracing |
| [Trading reviewer](../../.claude/agents/trading-reviewer.md) | Fresh review using the preloaded auditor skill; Opus 5.5 with `Read`, `Glob`, and `Grep` |
| [Reference checker](../../.claude/skills/systematic-trading-platform-auditor/scripts/check_references.py) | Detect stale paths, headings, and symbols referenced by the skill and agent |
| [Hazard scanner](../../.claude/skills/systematic-trading-platform-auditor/scripts/scan_hazards.py) | Produce scoped code-search leads for manual investigation |
| [Architecture inspector](../../.claude/skills/systematic-trading-platform-auditor/scripts/inspect_architecture.py) | Inspect owner imports and affected dependents |

The skill defines how to review; the agent provides the separate review context
and restricted tool set. Reuse both. The agent has no fixed effort field, so use
the session's selected effort and verify overrides. Its available tools cannot
run Git, tests, or helper scripts; the caller supplies that evidence.

Use this once if discovery or configuration has not already been verified:

```text
Verify the existing Claude review setup without modifying or recreating it.

Read:
- .claude/skills/systematic-trading-platform-auditor/SKILL.md
- its references/review-heuristics.md and scripts
- .claude/agents/trading-reviewer.md
- any applicable CLAUDE.md and the owning repository contracts.

Confirm that Claude discovers systematic-trading-platform-auditor and
trading-reviewer, that the agent preloads the skill, and that the effective
model is Opus 5.5 with the selected effort. Confirm its read-only tool list.

Check the skill's reference checker and run it if the existing environment is
available. Report missing or stale references precisely. Read the existing
configuration before recommending any changes; do not create duplicate skills,
reviewer agents, checklists, or plugins. Preserve current settings and hooks.

Return verified components, concrete gaps, and the next applicable review step.
If discovery cannot be checked in this session, distinguish that from file presence.
```

### 3.2 Maintain permanent context only if needed

**Effort:** `high`. **Mode:** the prompt below writes only `CLAUDE.md`.
**Result:** concise navigation to the existing process, if that context is missing
or stale. This is not a prerequisite to invoke the auditor directly.

The root `CLAUDE.md` was absent when this guide was refreshed. A direct skill
invocation or the existing reviewer can still use the repository's contracts.
If adding permanent context is useful, use this targeted prompt instead of
regenerating the auditor or running a broad bootstrap:

```text
Create or update only the root CLAUDE.md with concise persistent context.
First inspect current instructions and the repository's owning documents.

Include current scope, the main package map, links to engineering/testing/workflow
contracts, and actual validation entry points. Reference the existing
systematic-trading-platform-auditor skill and trading-reviewer agent for material
trading reviews, and docs/development/README.claude-code.md for their workflow.

Do not copy their procedures or heuristics into CLAUDE.md. Do not recreate or
edit the skill, agent, settings, or hooks. Verify repository-specific statements
and distinguish research/paper capability from future live qualification.
If the existing context is already sufficient, leave it unchanged.
```

### 3.3 Choose the review entry point

**Effort:** `high` for normal review, `xhigh` for a material audit or difficult
semantics. Select it before invoking the skill or starting the reviewer.

| Need | Entry point | Evidence handling |
| --- | --- | --- |
| Fresh review of an implementation | Ask for the existing non-fork `trading-reviewer`, using section 5.4 | Caller supplies exact patch, scope identity, requirements, and command results |
| Bounded audit with local Git or offline checks | Invoke the existing auditor in a separate Claude session | Auditor may collect local evidence under its shell-mode restrictions |
| Quick examination in the current chat | Invoke the auditor directly | Useful review, but it retains this chat's prior reasoning |

For a separate audit session, start from the repository root:

```sh
claude --model claude-opus-5-5 --effort xhigh
```

Then invoke the installed skill with explicit scope:

```text
/systematic-trading-platform-auditor Audit <SUBSYSTEM_OR_SCOPE> using the bounded-audit mode. Follow the installed skill's evidence, operating, and output rules.
```

For a direct diff review in a fresh session:

```text
/systematic-trading-platform-auditor Review <EXACT_BASE...HEAD_OR_WORKING_TREE_SCOPE> using diff-review mode. Follow the installed skill and report missing evidence explicitly.
```

Use `/effort high` for the ordinary diff review. Skill invocation in the current
chat is not the same as starting a fresh reviewer. A non-fork custom subagent has
its own initial context; a conversation fork carries earlier reasoning.
[Subagent context](https://code.claude.com/docs/en/sub-agents#what-loads-at-startup)

The installed skill prohibits network, venue, and local-service access during an
audit, including acquisition and live consumers. It also excludes secrets and
repository code edits. Select offline checks accordingly. Required service or
external-boundary validation belongs to the separately authorized development
validation stage; report that evidence separately, with its revision and limits.
The existing reviewer agent returns its report in chat. In shell mode, the skill
saves audit reports under `logs/audits/<YYYY-MM-DD>-<scope>.md` without overwriting
an existing report. This report write does not authorize code remediation.

Follow the skill's plain-language summary and stable `F1`, `F2`, ... identifiers.
Preserve those identifiers when challenging or fixing findings. Use the skill's
full report format rather than replacing it with a competing prompt template.

### 3.4 Use the existing helper scripts selectively

**Effort:** `low` to run a selected command; `high` to interpret its output.
**Mode:** local inspection. **Result:** reference integrity or investigation leads.

Run the reference check after relevant documentation/configuration changes:

```sh
uv run --frozen --no-editable python \
  .claude/skills/systematic-trading-platform-auditor/scripts/check_references.py
```

For a scoped hazard search, replace the path before running:

```sh
uv run --frozen --no-editable python \
  .claude/skills/systematic-trading-platform-auditor/scripts/scan_hazards.py <AFFECTED_PATH>
```

For import/dependent evidence, replace the module before running:

```sh
uv run --frozen --no-editable python \
  .claude/skills/systematic-trading-platform-auditor/scripts/inspect_architecture.py \
  --dependents <AFFECTED_MODULE> --transitive
```

Use `--help` for supported filters. If a shared environment is in use, the skill
permits `.venv/bin/python` to run the already-available scripts without a uv sync.
Do not make all three scripts a mandatory gate for every PR. Hazard/import output
is evidence to investigate, not a confirmed defect or a replacement for the
engineering checker. Attach relevant output when the restricted reviewer needs it.

### 3.5 Optional tool recommendations

**Effort:** `high`. **Result:** a small, justified tool selection.

The optional official `claude-code-setup` plugin provides automation recommendations;
it is not required for this guide. If installed, its namespaced skill is
`/claude-code-setup:claude-automation-recommender`.
[Setup plugin](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/claude-code-setup/README.md)

```text
Recommend only tools that fill a concrete gap in this repository's current
Claude Code workflow. Do not install or reconfigure anything.

For each recommendation give its purpose, existing overlap, required access,
configuration effort, and whether it is optional. Prefer the existing command
line tools when they already solve the problem.

Assess editor navigation, version-specific library documentation, GitHub access,
and optional additional review separately. Avoid stacking multiple workflow
frameworks or reviewers that repeat the same work. Preserve current safeguards.
```

Pyright LSP may aid navigation; strict mypy remains the repository gate. Treat
Superpowers, Context7, CodeRabbit, Serena, and simplification tools as optional.
If a workflow plugin is selected, reconcile its stages with this guide instead
of running two complete procedures. Hooks provide local feedback; required CI
and actual repository settings determine merge enforcement.

## 4. Initial audit and remediation roadmap

Use this section to establish a justified backlog. It is not a prerequisite for
every ordinary change. Break a large audit into bounded domains; never equate a
long report with complete coverage.

### 4.1 Audit the implemented platform

**Effort:** `xhigh`. **Mode:** code-read-only, with the skill's optional offline
checks and shell-mode report output. **Result:** evidenced findings and a coverage
map. Use an existing applicable audit when its scope and evidence remain valid.

Use the installed skill directly in a separate session, or provide this scope to
the existing reviewer together with the required evidence:

```text
Use the existing systematic-trading-platform-auditor skill in bounded-audit mode.
Scope: <SUBSYSTEM_OR_SCOPE>.
Purpose or question: <WHAT_THIS_AUDIT_SHOULD_ESTABLISH>.
Revision and available evidence: <REVISION_AND_EVIDENCE>.
Previous audit, if relevant: <REPORT_PATH_OR_NONE>.

Follow the installed skill's contracts, heuristics, operating restrictions,
coverage map, and report format. Inspect the current implementation; reuse valid
prior evidence without inheriting an old verdict. Do not recreate the skill,
change code, or run network/service/venue checks.

Use only relevant helper scripts and offline reproductions. Separate their
leads from confirmed defects. If this is the restricted trading-reviewer,
request missing command evidence from the caller instead of claiming execution.

Return the skill's audit report with its plain-language summary and stable F IDs.
In shell mode save it to the skill's audit-report location without overwriting an
existing file; in the read-only agent return it in conversation.
```

### 4.2 Challenge consequential or disputed findings

**Effort:** `high`, or `xhigh` for difficult semantics. **Mode:** read-only.
**Result:** retained, corrected, rejected, or still-unresolved findings.

This is a targeted verification pass. It need not repeat the full audit. For an
independent second assessment, first give a fresh reviewer the neutral scope and
contracts; provide the disputed findings after its initial assessment.

```text
Validate <FINDING_IDS> from <AUDIT_REPORT> using the installed auditor skill.
Preserve the existing F IDs and the report revision identity.

For each, identify the exact reachable path and governing invariant, construct
the failure scenario, inspect existing tests, and seek evidence that would
falsify the claim. Distinguish an actual defect from an unimplemented future
capability or an interpretation that the contract does not support.

Classify each as confirmed, corrected, rejected, or unresolved. For unresolved
material questions, state the specific evidence needed and the affected use.
Do not lower impact merely because confidence is incomplete; keep them separate.

Return the corrected findings and any concrete coverage omission discovered.
Do not modify code or restart an unrestricted whole-repository audit.
```

### 4.3 Turn validated findings into small changes

**Effort:** `high`; `xhigh` for consequential dependencies.
**Mode:** planning only. **Result:** a finishable implementation sequence.

```text
Convert <VALIDATED_FINDING_IDS_AND_REPORT> into a bounded remediation roadmap.
Do not implement it yet. Preserve the mapping from each task to its source F IDs.

For each independently reviewable change specify:
- the problem and violated invariant;
- affected owners, consumers, and interfaces;
- the observable end state and acceptance criteria;
- the smallest coherent implementation approach;
- decisive regression/boundary evidence and reusable existing evidence;
- dependencies and safely independent work;
- format replacement, artifact rebuild, recovery, and reversal implications
  only where applicable.

Order by concrete impact, exposure, and dependencies, not by whether a problem
is called architecture, performance, or finance. Keep speculative cleanup out
of the critical path. Flag uncertain abstractions and remove redundant gates.

Use the repository's format-replacement policy, existing testing tools, and
current paper/research scope. Do not add approval roles or a new evidence system.
Return a numbered sequence with clear completion conditions.
```

For a consequential plan, use this focused challenge before implementation:

```text
Review <PLAN> against its source findings and repository contracts.
Do not modify files.

Look for incorrect ordering, missed consumers, oversized changes, tests with
circular expectations, hidden semantic changes, unnecessary abstractions, and
unaddressed artifact/state replacement. For disputed items recommend retain,
modify, split, or remove with concrete reasons.

Return only necessary corrections and the resulting sequence. Stop when the
implementation decisions and sufficient acceptance evidence are clear.
```

## 5. Per-task development and review loop

```text
Scope and acceptance
  -> design/challenge when needed
  -> implementation with meaningful tests
  -> affected checks
  -> one fresh software/domain review
  -> resolve findings and refresh affected evidence
  -> PR and required CI for the final candidate
```

For non-behavioral or mechanical changes, combine scope, implementation, and brief
review. For material PIT, numerical, accounting, risk, order-state, or recovery
changes, deepen the relevant reasoning. Optional design challenge and extra
review are responses to real uncertainty, not universal stages.

### 5.1 Scope, design, and choose the proof

**Effort:** `high`; `xhigh` for difficult trading semantics.
**Mode:** planning/read-only. **Result:** concise scope and acceptance contract.

```text
Prepare implementation of <TASK>.
Do not modify code in this step.

Inspect the relevant subsystem, its necessary callers/callees, current tests,
and governing repository contracts. Identify current behavior, desired behavior,
affected public/data interfaces, and explicit non-goals.

Propose the smallest coherent design. State the invariants at risk and any
effect on information availability, event order, units, fills, positions, PnL,
limits, determinism, persistence, or recovery that actually applies.

Select the cheapest sufficient proof: existing tests to reuse, defect regression
to demonstrate, independently derived expectations, and boundary checks needed.
Explain any substantial new harness work. Do not require every test category.

Run only useful affected baseline checks when existing evidence is insufficient.
Record commands/results and distinguish pre-existing failures. Do not demand a
clean whole-repository baseline before addressing a bounded defect.

Return the design, affected owners/consumers, acceptance criteria, checks, and
reversal implications. Surface only consequential unresolved decisions.
```

For consequential unresolved design questions, run this in fresh context at
`xhigh`; escalate a specific hard question to `max` if necessary:

```text
Challenge <DESIGN> for <TASK> using the actual contracts and reachable inputs.
Do not modify files.

Try to falsify its relevant causal, numerical, state-transition, idempotency,
or recovery properties. Consider duplicate/out-of-order events, stale inputs,
partial failures, uncertain external outcomes, and concurrent state only where
those paths exist. Check whether proposed tests use independent expectations.

For each real concern give a concrete scenario and minimal correction.
Separate theoretical concerns from supported risks. If no actionable issue
remains, say so and list the invariants implementation must preserve.
```

### 5.2 Implement with tests

**Effort:** `medium` for a clear bounded change; `high` for interacting state;
`xhigh` for difficult financial/temporal implementation.
**Mode:** authorized implementation. **Result:** coherent code, callers, tests,
and documentation changes.

The engineering guide requires a regression test that fails without each defect
fix. Demonstrate that for the intended reason. Implementation and tests can be
developed together; there is no separate approval gate between them. The
requirements and contracts define behavior, while tests supply evidence.

```text
Implement <TASK> using <DESIGN_AND_ACCEPTANCE_CRITERIA>.

Make the smallest coherent change and carry it through affected callers,
exports, tests, and documentation. Preserve unrelated working-tree changes.
Follow the repository's engineering and format-replacement rules.

For a defect, add or strengthen a regression and demonstrate that it fails
without the fix for the intended reason. For new behavior or refactoring,
use appropriate contract and boundary evidence without manufacturing a failing
baseline. Expected financial/temporal results must have an independent basis.

Preserve strict typing, explicit units/time semantics, supported public APIs,
cohesive ownership, and meaningful Google-style documentation. Do not broaden
scope, add speculative abstractions, or suppress failures to obtain a pass.

Run affected tests and static checks. Diagnose task-related failures and finish
the authorized change. Ask only if a material requirement or scope decision
cannot be resolved from the accepted task and repository contracts.

Return changed behavior, deviations, exact check results, and remaining limits.
```

Optional local simplification, at `medium`:

```text
Inspect only the changed behavior and supporting code for unnecessary complexity.
Apply a simplification only when it clearly improves clarity within this task.
Preserve domain concepts, exact semantics, failure checks, and package boundaries.
Do not introduce unrelated cleanup. Rerun checks affected by substantive edits
and report those edits before the final review.
```

### 5.3 Validate and diagnose

**Effort:** `low` for executing an established command set; `high` for diagnosis.
**Result:** evidence of the current state, not merely a list of intended checks.

```text
Validate <TASK> against <ACCEPTANCE_CRITERIA_AND_SELECTED_CHECKS>.

Run the affected configured checks, including relevant callers and integration
boundaries. Select integration/performance markers explicitly when needed.
Include installed artifact evidence when the changed contract requires it.

Report exact commands, exit status, relevant tests executed, skips/deselections,
and any unavailable checks. Compare with the baseline where one exists.
Distinguish new failures, resolved failures, and unchanged pre-existing failures.

Do not edit code in this validation step, update goldens automatically, weaken
assertions, or claim success for a skipped/unreached boundary. Identify any
failure needing diagnosis and continue independent checks that remain useful.
```

When a failure needs diagnosis, use `high`, or `xhigh` for complex state:

```text
Diagnose <FAILURE> from its observable symptom to its root cause.
Classify it as product, test/harness, source data, environment, access, or
pre-existing behavior. Use the smallest reproduction that can settle the cause.

If the correction is within the authorized task, implement the minimal fix and
rerun affected checks. Otherwise explain the precise blocker and continue
unblocked work. Do not weaken contracts or assertions merely to pass.

Before an expensive rerun, state the changed condition or hypothesis it tests.
For uncertain stateful external actions, reconcile the outcome before retrying.
Return cause, evidence, correction, and refreshed validation.
```

### 5.4 Run one fresh code and domain review

**Effort:** `high`; `xhigh` for material trading semantics or recovery.
**Mode:** reviewer is read-only. **Result:** evidence-based findings for an exact
state, including a valid outcome of no actionable findings.

Set the desired effort before starting the existing `trading-reviewer`:

```text
/effort high
```

Prepare and delegate from the implementation session:

```text
Prepare a fresh review of <EXACT_CHANGE_SCOPE> using the existing trading-reviewer.
Do not recreate or reconfigure it. Do not make code changes during preparation
or while it reviews this state.

Resolve the base, head, and merge base for a branch/PR review. For an uncommitted
review include staged, unstaged, and relevant untracked content: git diff alone
does not include untracked files. Record dirty state and the exact included paths.

Provide the reviewer the complete patch, task requirements, relevant contracts,
and exact validation evidence. Use a temporary file outside the repository when
the patch is too large for the delegation message. Preserve its identity until
review and disposition finish. Do not include secrets or private raw datasets.

Start a new non-fork trading-reviewer on Opus 5.5 at the selected effort.
Verify that configuration overrides have not changed the effective model/effort.
Do not send your own conclusions or previous findings in the initial request.
Use the reviewer prompt below as its task.

The reviewer cannot run commands. If it requests a focused reproduction or
missing Git context, supply that evidence separately and let it reassess.
Use offline checks within the audit restrictions; identify separately authorized
external validation as separate evidence. Return the skill-format report,
including its plain-language summary and stable F IDs, without endorsing every claim.
```

Give the existing reviewer this short task prompt; its preloaded skill supplies
the review procedure, heuristics, evidence standard, and output format:

```text
Review <EXACT_BASE_HEAD_OR_WORKING_TREE_SCOPE> using your preloaded
systematic-trading-platform-auditor skill in diff-review mode.

Task and acceptance: <REQUIREMENTS>.
Complete patch and scope identity: <PATCH_AND_METADATA>.
Validation evidence: <COMMANDS_RESULTS_AND_LIMITS>.
Specific unresolved question, if any: <QUESTION_OR_NONE>.

Follow the installed skill and owning repository contracts. Return its complete
report with a plain-language summary and stable F IDs. Identify missing essential
evidence precisely. Do not modify files, run commands, or post comments.
```

### 5.5 Validate and resolve findings

**Effort:** `high`; `xhigh` for difficult semantics.
**Mode:** fixes are authorized by the following prompt.
**Result:** disposition of findings and refreshed evidence.

Return to the main implementation session for this step. The installed auditor
and restricted reviewer remain review-only. The following prompt authorizes the
bounded fixes; if the task already authorizes them, carry that authorization
forward without asking again. Do not ask the read-only reviewer to edit code.

```text
In the implementation session, validate and resolve <FINDING_IDS> from
<REVIEW_REPORT> for <TASK>. Keep the original F IDs stable.

For each finding inspect the actual path and contract, reproduce or otherwise
establish the claim, and classify it as confirmed, rejected with evidence,
optional, or unresolved. Do not automatically implement every reviewer suggestion.

Fix confirmed defects within the task. Add/strengthen the required regression,
make the smallest coherent correction, and rerun affected checks. Preserve
valid existing evidence when the correction cannot affect its boundary.

Return a mapping of F ID -> disposition -> regression/evidence -> change ->
validation result. Keep material unresolved questions visible with the evidence
needed to settle them. Separate optional future work from required fixes.

Request a focused re-review of changed behavior where fixes alter the prior
review conclusion. Do not restart every earlier audit or run repeated complete
suites without a changed risk. Finish when acceptance and relevant review
questions are satisfied for the delivered state.
```

### 5.6 Final evidence, PR, and merge candidate

**Effort:** `low` for selected final checks, `high` for unresolved readiness
questions, `medium` for PR writing.
**Result:** an honest PR description and validation of the final candidate.

```text
Prepare <TASK> for a pull request.

Inspect the final diff and revision identity. Verify that acceptance criteria
are met, relevant findings are resolved/dispositioned, and collected validation
covers the delivered state. Refresh evidence affected by late edits, rebases,
conflict resolution, dependencies, configuration, or changed inputs.

Run remaining affected local checks. Do not rerun expensive unaffected proofs
by habit or substitute a fresh success for the history of failed attempts.

Use .github/pull_request_template.md:
1. Problem / change
2. Affected scope
3. Validation result
4. Risks / reversal

Include exact commands/results and pending CI. Add migration/rebuild, benchmark,
or operational detail only where it helps assess this change. Distinguish
implemented behavior, tested evidence, empirical research, and unqualified use.

Prepare the PR title and body. If pushing and opening a PR are already authorized
for this task, complete those actions; otherwise return the prepared text.
Do not merge or deploy on the strength of an AI readiness recommendation.
```

The current CI workflow runs on a PR into `main` when it receives the
`ready-to-merge` label. It does not run for every pushed commit. After new commits,
remove and re-add the label. Require successful checks for the actual candidate;
if the base moves, ensure the tested merged-result identity is still applicable.
An earlier green check is not evidence for a different base/head combination.
[CI trigger and merged-result checks](../../.github/workflows/ci.yml)

Use this prompt when preparing the actual merge candidate:

```text
Check merge-candidate evidence for <PR_NUMBER> without merging it.

Inspect the current base/head, review state, and the configured required CI lane.
If this task authorizes triggering CI, apply or refresh ready-to-merge as required
by this repository's workflow; otherwise state the remaining trigger action.

Verify source validation, platform smoke, and merged-result checks belong to
the candidate being assessed. Report failed, pending, skipped, or missing gates.
Inspect actual branch/ruleset requirements if access is available; do not infer
remote branch protection from the workflow YAML alone.

Return technical readiness, exact candidate identity, and remaining blockers.
A draft PR may exist before readiness; merge requires the actual required gates.
```

## 6. Optional additional review tools

Use an additional reviewer to answer a concrete unresolved question or inspect a
high-impact boundary. Do not require native review, the custom reviewer,
Ultrareview, and CodeRabbit sequentially for every change.

### Native local review

**Effort:** explicitly `high` or `xhigh`. Example targets must be replaced with
your actual branch names or PR number:

```text
/code-review high <BASE>...<HEAD>
/code-review xhigh <PR_NUMBER>
```

Omit `--fix` and `--comment` for review without editing or posting. Native review
can serve as a quick general review; it does not automatically establish use of
the custom domain skill or fresh-context independence. It reads `CLAUDE.md`, but
local review does not read `REVIEW.md`. Hosted Code Review separately supports
`REVIEW.md`. Pass explicit scope and effort rather than relying on remembered
defaults. [Native and hosted review documentation](https://code.claude.com/docs/en/code-review)

### Ultrareview

**Effort:** managed cloud review; `ultra` is not an Opus effort level. This guide
does not claim that its fleet uses the parent session's pinned model or effort.

```text
/code-review ultra <BASE>
```

Or, for the remote PR rather than local changes:

```text
/code-review ultra <PR_NUMBER>
```

Cloud availability depends on authentication/provider. Inspect the launch dialog
for scope and cost: branch mode uploads repository state, while PR mode clones
the remote PR and does not include unpushed local edits. Keep the run without
posting unless posting is intended. If unavailable, the command can fall back to
local review; report which actually ran. Cloud review completion is not evidence
that no bugs were found. [Ultrareview documentation](https://code.claude.com/docs/en/ultrareview)

### Other plugins and external reviewers

The separately installed `code-review` plugin is not identical to the native
command. Its current command source specifies reviewer models and GitHub posting
behavior. A parent Opus setting does not establish the plugin's execution model.
Inspect the installed plugin and invocation before adopting it.
[Official plugin command source](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-review/commands/code-review.md)

For CodeRabbit or any additional reviewer, validate findings using section 5.5.
For a read-only triage first, use `high` or `xhigh` with:

```text
Assess <EXTERNAL_REVIEW_FINDINGS> against <EXACT_REVIEWED_REVISION>.
Do not modify code yet.

For each non-trivial claim identify the path, governing invariant, reachable
trigger, and evidence. Classify it as confirmed, rejected, optional, or unresolved.
Explain architectural conflicts or unnecessary complexity in suggested fixes.
Propose the smallest correction and decisive regression for confirmed defects.
State revision mismatches and do not assume old comments describe the current code.
```

## 7. Milestone audits and configuration upkeep

### 7.1 Revisit cross-cutting correctness after a real milestone

**Effort:** `xhigh`; reserve `max` for specific unresolved problems.
**Mode:** read-only. **Triggers:** a new supported venue/asset, changed simulation
or accounting semantics, a new stateful runtime, or a major architecture boundary.

```text
Use the systematic-trading-platform-auditor skill to review <MILESTONE_SCOPE>.
Do not modify code.

Establish the current implementation and compare it with the previous relevant
milestone and current contracts. Trace the changed end-to-end boundaries and
look for semantic drift, mismatched ownership, and invalidated research evidence.

Re-establish important conclusions from code and evidence rather than inheriting
old verdicts. Preserve valid historical records and distinguish current results.
Classify each area as reviewed, partial, not reviewed, or not applicable.

Follow the installed skill's operating restrictions and audit report format,
including its plain-language summary, stable F IDs, and report location in shell
mode. Identify evidence that needs renewal and small remediation slices. Do not
reopen settled choices or expand into future live qualification without a
concrete reason.
```

### 7.2 Refresh Claude configuration when its assumptions change

**Effort:** `high`. **Mode:** recommendations first. **Triggers:** changed package
boundaries, language/toolchain, CI, model/version, or selected plugins.

```text
Review the Claude Code setup after <CHANGE>.
Inspect the actual CLAUDE.md, skill, agent, settings, hooks, and owning repository
documents. Verify model identifiers, effective effort, tool availability, and
review command behavior against current official documentation.

Identify stale facts, broken links, duplicated instructions, ineffective hooks,
and tools that no longer add value. Recommend the smallest coherent update.
Preserve existing safeguards and repository standards. Run the existing skill's
reference checker after relevant document/path changes. Propose targeted edits
only for demonstrated gaps; do not regenerate the skill or add a second reviewer
by default. Do not install tools or rewrite runtime code during this assessment.
```

## 8. Severity and domain review guidance

The existing auditor explicitly references this section for severity and domain
checks. Keep these headings stable. Its SKILL.md and heuristics own the detailed
review method and report format; this section does not replace them.

### Finding classification

Severity measures impact and urgency under a reachable trigger. Financial,
temporal, security, architecture, and performance are domains, not priority levels.

| Priority | Interpretation |
| --- | --- |
| P0 — critical | Reachable critical failure requiring immediate containment, such as catastrophic exposure or unrecoverable authoritative-state loss |
| P1 — high | Material correctness, research validity, control, security, or operational failure requiring correction before the affected use |
| P2 — medium | Bounded but substantive defect or demonstrated contract violation |
| P3 — low | Small actionable issue with limited impact |

For each finding, record domain, confidence, and disposition separately. A
high-impact uncertainty belongs under material unresolved questions until the
evidence establishes the defect. It may still prevent a readiness recommendation
for the affected use. Explain what evidence would resolve it. A low-impact issue
does not become critical merely because it concerns money. The installed skill
classifies a confirmed defect that prevents trusting the affected research,
paper, accounting, or control use as at least P1; a P2 is a bounded defect for
which that use can proceed with the limitation stated.

Report confirmed defects, material unresolved questions, and optional improvements
separately. Pre-existing findings belong in a separate note during a diff review
unless the change makes them newly reachable. Omit cosmetic preferences unless
reviewing an explicit applicable standard.

### Select checks by changed behavior

| Affected domain | Questions and decisive evidence |
| --- | --- |
| Architecture and interfaces | Do owners enforce their contracts? Are consumers using public APIs? Are dependency direction, installed packaging, and configuration selection preserved? |
| Identity, units, venue/calendar | Is instrument identity stable through source mappings and lifecycle changes? Are price, quantity, currency, multiplier, rounding, and session rules explicit? Preserve material venue semantics at canonical boundaries. |
| Temporal/PIT | Could the exact value be known at decision time? Check event/capture/receipt/ingestion/knowledge clocks, half-open validity, late revisions, as-of joins, and ties. Use causal counterexamples. |
| Ingestion and books | Check snapshot/delta admission, venue-specific sequence/checksum rules, duplicates, gaps, stale state, reconnect, invalidation, and resynchronization. Invalid state must not appear tradable. |
| Research and features | Check historical membership, fitted-state boundaries, label horizons, training/validation separation, trial history, and untouched holdouts. Reproducibility includes code, inputs, configuration, libraries, and relevant execution conditions. |
| Simulation | Check decision/fill ordering, observable liquidity, costs, fees, slippage, financing/lifecycle assumptions, and independent numerical oracles. Bar data cannot establish unavailable intrabar order or queue fidelity. |
| Orders, portfolios, and controls | Trace applicable submission/acknowledgment/partial fill/cancel/replace/rejection transitions, pending exposure, account isolation, and ambiguous outcomes. Reconcile unknown outcomes before retrying economic intent. |
| Accounting | Reconcile cash, positions, and PnL using applicable economic events and valuation inputs, including fees, marks, transfers, funding, FX, or lifecycle events. Fills alone do not define all PnL. |
| Recovery and risk | Verify restart parity, durable transitions, duplicate handling, independent risk enforcement, and stop/cancel/reconciliation behavior. Define safe failure behavior without accidentally disabling necessary risk-reducing actions. |
| Performance and concurrency | Require a representative workload and correctness/recovery evidence. Inspect ownership, races, backpressure, resource bounds, and tail behavior when the change affects them. |
| Formats and artifacts | Follow replacement-in-place rules, explicit unsupported-format refusal, derived-artifact rebuild, coordinated consumer/docs updates, and applicable state/reversal constraints. |
| Testing and security | Check discovery, independent expectations, meaningful failure assertions, untrusted inputs, secret handling, and actual boundary coverage. Passing tooling is supporting evidence, not universal correctness proof. |

Apply the rows relevant to the actual change. Do not require every asset, venue,
failure combination, or test technique for every PR. Synthetic fixtures establish
software properties; they do not establish empirical alpha or live venue fidelity.

## 9. Daily checklist

1. Select Opus 5.5 and the appropriate effort; reuse the installed skill and reviewer.
2. Establish scope, current contracts, acceptance, and consequential risks.
3. Design or challenge only decisions that need it.
4. Implement a coherent change with meaningful tests and affected consumers.
5. Run affected checks and retain actual results and limits.
6. Give the existing reviewer the exact state and evidence; follow the installed skill.
7. Resolve findings by their stable F IDs in the implementation session and refresh evidence.
8. Use the existing PR template and required CI on the actual merge candidate.

Completion means the delivered state satisfies the accepted task, the required
checks pass, and no unresolved blocking correctness question remains for the
affected use. Do not add another review merely because no defects were found.
