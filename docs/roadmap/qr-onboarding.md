# MR17 QR onboarding acceptance

Owner: quant development. Status: **open; gap inventory and acceptance design approved
2026-10-04 ([decisions](#owner-decisions-approved-2026-10-04)). Nothing is signed or run
under MR17.**
The [roadmap](README.md#qr-onboarding-acceptance) owns the six acceptance items and the
G5 gate. This page is the MR17 acceptance record: it holds the gap inventory, the
integrated fresh-entry journey, its declarations and, later, its results.

Baseline: `main` at `addfad1` (MR16 merged 2026-10-04), branch
`eng/mr17-onboarding-acceptance`. MR01–MR14, MR07A/MR07B and MR16 are complete for their
stated scopes. MR15 is open (see [prerequisites](#mr15-prerequisites)). Live trading stays
KIV; nothing on this page grants live authority.

## Gap inventory

**Method.** Each acceptance item was mapped to the maintained consumers, discovered
workflow tests and acceptance records that prove it today. A boundary counts as
proven for MR17 only if an installed, fresh, integrated run on the current code proves
it. Evidence that exists only as a milestone fixture, an engineering consumer under
`tests/`, or a retained record of older code is listed as reusable but not sufficient.

**Cross-cutting findings.**

1. **No integrated fresh-entry journey exists.** Every item is proven piecewise, by a
   separate consumer with its own authored inputs. No run chains clean provisioning →
   discovered data → fresh extension → study → feature store → candidate → paper →
   monitoring → backup/restore → rollback on one release.
2. **The extensions are QD-authored and live under `tests/`.** `decision_study.py`,
   `decision_extensions.py`, `candidate_workflow.py` and `research_workflows/` author
   their components in the test tree. They are fresh relative to the runners, but they
   are not written from the published guides, and they are not installed artifacts. The
   QR guide points readers at them as examples.
3. **The supervised paper service cannot run a fresh strategy.**
   `PaperServiceInstance.policy` (`src/configuration/paper_services.py`) is the literal
   `fixed_clip | liquidity_clip | target_clip`. The MR14 supervised deployment, which is
   the only path with isolated and shared accounts together, selective stop/restart and
   the MR15 runtime measurements, therefore runs only built-in reference formulas. A
   fresh candidate reaches paper only through the finite `run_paper` /
   `run_live_shared_paper` paths (one account per invocation, 20 frames or ten seconds
   in live mode). The roadmap's fresh-extension scenario requires selected
   implementations to reach runtime without fallback to built-ins.
4. **There is no supported-import check for code outside the repository.** The
   ownership checker enforces supported imports over the repository's roots. A QR's
   extension package, written outside the checkout, has no tool to show it imports only
   supported names; installed-wheel execution alone cannot show it, because deep
   modules stay importable.
5. **Retained milestone evidence is absent from this workspace.** The records cite
   ignored `logs/mr10/`, `logs/mr11/`, `logs/mr12/`, `logs/paper-integration/`,
   `logs/paper-activation/`, `logs/multi-instance-paper/` and `logs/capacity-closure/`,
   and the R1 corpus under `data/okx/research-corpus-20260930/`. None of these exists in
   this checkout or under `~/AlphaResearchEvidence.noindex/`; only
   `logs/paper-monitoring/` and `logs/runtime-capacity/` remain.
6. **The code under the milestone records has changed.** MR15 (S1–S5: paper capture
   rollover, chain consumers, declared lifetimes, telemetry cadence, reconciler) and
   MR16 (every owner restructured) changed the components that the MR07–MR14 records
   qualified. The full suite passed unchanged in behaviour, but the roadmap's
   "reuse milestone proofs for unchanged components" no longer applies directly.

### Item 1 — clean workspace, discovery, admission and reopening

| Existing proof | Kind |
| --- | --- |
| `datasets/public_data.py` consumer; `unit/data/test_public_data.py` (both parsers, four scopes, PIT venue rules, configuration-only onboarding) | Installed consumer, authored and short actual captures |
| `datasets/versioned_storage.py` (lakeFS publish/reopen), `feature_workspace` reopen | Manual service checks |
| MR01 record; `test_ingestion_workflow.py` | Milestone record; discovered test |
| Universe separation (collection/research/strategy/trading) in `configuration` tests | Unit fixtures |

**Unproven.** No clean-workspace run starts from the published environment guide,
provisions local services, captures fresh public inputs for both venues, publishes,
discovers and reopens them with quality, specification versions and limits visible in
one sequence. That a collection or research selection cannot authorize trading is
proven by unit fixtures, not at the installed grant boundary.

### Item 2 — fresh extensions, rule-only and learned paths, target and order/quote

| Existing proof | Kind |
| --- | --- |
| `research/decision_study.py` (fresh feature, estimator, strategy, metric, chart; walk-forward; losing/no-trade; search recovery; holdout refusal; fresh-process reopen) | Installed consumer, synthetic inputs |
| `research/decision_extensions.py`, `test_decision_workflow.py` (fresh feature/label/estimator/quote; non-book input) | Installed consumer, synthetic |
| `research/captured_study.py` (retained OKX/Bitfinex books and trades) | Installed consumer, short retained captures |
| `research/candidate_workflow.py` (rule-order and learned-target candidates through `run_paper`) | Installed consumer, synthetic study |
| Unsupported `XNYS` calendar and unsupported product refused (`unit/research/test_decision_contracts.py`) | Unit fixture |

**Unproven.** Extensions written from the guides, outside `tests/`, on discovered
inputs from item 1. The architectural extension scenario on that path: a supported-family
instrument added by configuration, a non-book input carried through study and candidate,
and the non-24/7 calendar or different-economics fixture. Today the calendar case is
refusal only, in a unit test. A fresh candidate in the supervised paper service (finding 3).

### Item 3 — custom metric and chart

| Existing proof | Kind |
| --- | --- |
| `decision_study.py` registers a custom metric and chart across retained studies and paper telemetry, with delayed-label diagnostics | Installed consumer |
| MR12 record and `logs/paper-monitoring/reverification` (renewed 2026-10-02): both venues, both account modes, receiver loss/restoration | Retained installed evidence (present) |

**Unproven.** The same QR-authored metric and chart, defined once, shown over the
journey's own historical studies and its paper and shadow runs, with an alert firing
and its missing/late semantics, on one release.

### Item 4 — feature store offline, online, parity and recovery

| Existing proof | Kind |
| --- | --- |
| `research/feature_workspace.py` (real Feast worker: restart, retries, PIT corrections, expiry, service loss, rollback, restored serving bytes) | Manual service consumer, authored inputs |
| `research/offline_features.py` (real SDK retrieval, delayed corrections, missing entities, TTL) | Manual service consumer |
| `candidate_workflow.py --feast` (online store through the paper OMS, service-loss and version-change pauses) | Installed consumer |
| MR15 [counted feature cohort](runtime-capacity.md#counted-feature-cohort-result-2026-10-03) and stage 2a feature serving | Capacity evidence, reference features |

**Unproven.** A QR-defined feature (from item 2) taken offline → materialized → served
online to the journey's candidate, with matched-cutoff parity, and missing, stale and
revised inputs, retry and version rollback, on the journey's inputs.

### Item 5 — candidates, two strategies, shared and isolated accounts, both venues

| Existing proof | Kind |
| --- | --- |
| `runtime/public_paper.py` + `test_public_paper_workflow.py` (both venues, two policies, losing/no-trade/adverse, exact replay, cost/P&L, gas inapplicability) | Installed consumer and discovered tests; short live runs in the MR11 record |
| `runtime/shared_account.py`, `portfolio_account.py`, `account_operations.py` (8,000 + 8,000 / 10,000 race, netting, uncertainty, selective stop, restart) | Installed consumers, authored facts |
| MR13 activation and MR14 multi-instance records | Retained records of older code (evidence absent, finding 5) |
| MR15 stage 1 and stage 2a counted runs (four signed owners, eight instances, owner death and recovery) | Present, reference policies only |

**Unproven.** Two QR-authored strategies, packaged as candidates, active together on a
shared account and on isolated accounts in both venues under signed activation, with
the decisive scenarios (shared-budget race, netting, order uncertainty, selective stop,
recovery, adverse cost) on the journey's release. Blocked by finding 3.

### Item 6 — capacity, restore, installation, deployment, guide

| Existing proof | Kind |
| --- | --- |
| MR15 runtime stage 1 and stage 2a | Present, counted |
| MR15 research profile R1 | **Not accepted**: the [research capacity record](research-capacity.md#armed-acquisition-and-continuation) last shows the corpus acquisition armed for 2026-09-29 23:00 to 2026-10-03 00:00 UTC, with no recorded outcome |
| `deployment/trusted_installation.py`, `test_release_installation.py` | Installed consumer and engineering tests |
| MR04 workspace/job restore, MR10 account backup/restore, MR13 signed rollback | Records of older code; MR10/MR13 evidence absent |
| [Operations runbook](../governance/operations.md) | Guide, reference policies only |

**Unproven.** MR15 R1 and stage 2b. A single restore of data, features, artifacts and
account state from one backup set, followed by reconciliation and resumption. Signed
upgrade/rollback of the journey's paper deployment. The runbook followed verbatim for
a QR candidate.

### G5

G5 needs all six items through the installed integrated stack plus both MR15 profiles.
Every item above has at least one unproven boundary, so G5 is open.

## Documentation gaps

| Guide | Gap |
| --- | --- |
| [QR guide](../../examples/README.md) | No runnable path from a clean machine. "Implementing a study" names the APIs and points at QD consumers under `tests/`; it does not show how to lay out an extension package outside the checkout, retain it as `StudyArtifact` bytes with `DecisionStudy.extensions` fingerprints, package a candidate, register a custom metric/chart for paper dashboards, define a versioned feature for the store, or take a candidate to paper |
| [Development environment](../README.md#development-environment) | `uv sync --frozen` gives an editable install, while the tests guide and recorded runs use `--no-editable`; installing the research wheel outside the checkout and provisioning the Feast worker are not in the onboarding path |
| [Notebook operations](../../examples/notebook-operations.md) | Dated 2026-09-24; does not say how a worksheet consumes a retained study result from the installed readers |
| [Operations runbook](../governance/operations.md) and [paper guide](../../src/applications/paper/README.md#supervised-local-deployments) | Supervised deployment covers the three reference formulas only; there is no ordered "take a packaged candidate to signed paper" path, and the steps are spread over the runbook, execute guide and paper guide |
| [Research program](research-program.md) | Not yet checked against the final journey; reviewed with the guides in milestone M1 |

## Platform defects and prerequisites

| ID | Defect | Proposed fix |
| --- | --- | --- |
| P1 | Supervised paper services admit only built-in reference policies (finding 3) | Add an optional candidate binding to `PaperServiceInstance`: candidate bundle identity and extension artifact digests, loaded through `CandidateLoader` in the policy worker. Omitted when unset, as `telemetry_seconds` was, so stage-1/2a selections stay byte-identical. **This changes a signed configuration schema, so it needs owner approval.** |
| P2 | No supported-import check for external extension code (finding 4) | A governance command that applies the ownership checker's import rule to a given directory against the installed owners' `__all__` |
| P3 | Non-24/7 calendar and different economics are refusal-only, in unit fixtures | Carry the refusal through the journey's study and candidate admission; positive support stays later scope (see decision 8) |
| P4 | No timed 4× replay of a 24-hour corpus; the sustained workload is sized for 2a (10 periods, 4-segment chain) | Stage 2b harness work, under the 2b declaration |
| P5 | Host has 497 GiB free; the runtime profile requires at least 512 GiB at trial start | Free space, or a dated redeclaration (decision 10) |
| P6 | Account service startup owner check still reads full history (open note from stage 2a) | Measure in 2b rehearsal; fix only if it misses a budget |

## Integrated fresh-entry journey

**Principle.** One frozen commit, one set of installed artifacts, the published guides
only. I act as a fresh QR. Any step that needs knowledge outside the published guides,
an edit to shared code, a deep import or a built-in fallback is a failure, recorded
with the guide gap, never worked around inside the attempt.

**Environment.**
- A clean git worktree at the frozen commit, outside iCloud, e.g.
  `~/AlphaResearchEvidence.noindex/mr17/<attempt>/checkout`, used only to build.
- Fresh environments: `UV_PROJECT_ENVIRONMENT=/private/tmp/mr17-build uv sync --frozen
  --no-editable` for building; the research wheel installed into
  `/private/tmp/mr17-research`; the Feast worker from its own lock; signed execution
  targets installed by `alpha-governance-artifacts`.
- Local lakeFS and ClearML from `make local-services-up` with existing private keys.
- Evidence under `~/AlphaResearchEvidence.noindex/mr17/<attempt>/`, linked from
  `logs/mr17/`.

**Fresh extension package `mr17_extensions`.** Authored in the evidence workspace from
the guides, never under `tests/` or `src/`, retained as `StudyArtifact` bytes and
passed through P2. It contains:
- a book feature (depth imbalance) and a non-book feature (signed public-trade flow),
  in one named multi-feature schema;
- a fitted transform (train-only standardization) and a forward mid-return label;
- a non-built-in estimator (exact least squares) and a rule policy emitting order/quote
  intents, plus a learned policy emitting targets;
- a custom metric (net return per unit turnover) and a custom chart.

**Steps, commands and pass criteria.** Exact commands are fixed in the journey
declaration (milestone M4) once the guides they come from exist; the shape is:

| Step | What runs (installed commands and APIs) | Pass criteria |
| --- | --- | --- |
| J1 Provision | Build and verify the research wheel and signed `contracts`/`collector`/`execution` releases; install outside the checkout; local services up; Feast worker | Installs from the guides alone; installed identities recorded; execution target lacks research, notebook, training and reporting modules |
| J2 Data | `alpha-collect` fixed window of public OKX BTC-USDT/ETH-USDT and Bitfinex BTC/USD/ETH/USD books and trades; `alpha-dataset` publish; catalog discovery; quality/coverage inspection; lakeFS publish and reopen | Every source retained with original clocks, gaps explicit; reopened bytes equal; specification versions and limits visible; a research selection presented as a grant is refused |
| J3 Research | `evaluate_study` rule-only and learned studies (walk-forward, costed, both decision kinds); `compare_studies` small grid; deferred ClearML publication then `publish_experiments`; fresh-process reopen; architectural extension (instrument by configuration, non-book input, refused calendar/economics) | No built-in substitution; holdout consumption recorded; exact reports with the custom metric/chart; refusals before work |
| J4 Features | Offline PIT retrieval, materialization and online serving of the QR feature through the Feast worker; injected late revision, TTL expiry, missing entity, materialization retry, version rollback | Matched-cutoff parity exact; no future leakage; each fault explicit and recovered |
| J5 Candidates | Package rule and learned candidates; replay through the candidate loader | Replay decisions equal the study's at matched inputs |
| J6 Paper | Signed installation and activation per account; supervised deployment (after P1) of both QR candidates on shared and isolated accounts in both venues, paper and shadow, within the qualified 2a envelope (at most 50-minute life, one-hour grants); shared-budget race, injected order uncertainty, selective stop/restart, adverse-cost scenario | Exact independent reconciliation; cost/P&L with gas inapplicability; no duplicate effect; custom metric on paper dashboards; alert observed by the local receiver; shadow zero fills |
| J7 Operations | Quiesced backup of data/features/artifacts/account state; restore into a fresh root; reconcile; resume; signed release upgrade and rollback | Restored identities equal; resumption without manual repair; rollback keeps current facts |
| J8 Capacity | No new measurement; links the accepted MR15 R1 and 2b records | Both accepted |

**Retained evidence.** Frozen commit, wheel and release digests, environment
inventories, guide revisions used, every command with exit status, the extension
package bytes and its import audit, inputs and their source identities, study and
candidate identities, signed configurations and grants, account journals,
reconciliations, dashboards, alerts, backup set, restore and rollback outputs, and
a summary JSON with per-step pass/fail.

**Pass/fail.** The journey passes only if every step passes in one counted attempt on
one frozen commit. It stops at the first failure. A failed step is fixed in code or
guides, then the journey is redeclared and rerun from J1; a counted attempt is never
patched mid-run.

## MR15 prerequisites

- **R1 research capacity** is still pending (item 6 above). Its outcome must be
  recorded, or the profile rerun under its own declaration, before MR17.
- **Stage 2b** follows the [stage-2 design](runtime-capacity.md#stage-2-design-2026-10-02)
  and the [owner decision of 2026-10-04](runtime-capacity.md#owner-decision-stage-2b-sequencing-2026-10-04):
  declaration with every target, schedule and authority change (26-hour grants as new
  signed artifacts); short expiry and revocation denial trials; uncounted rehearsals;
  the counted 24-hour attempt under the quiet-host gate; 72-hour retention; the 4×
  replay; checkpoint percentiles. Each gate stops for owner approval and at the first
  failure.
- **Ordering.** Every code change MR17 needs, including P1, lands before 2b, so that 2b
  qualifies the code the journey runs. After the 2b counted pass, code is frozen; the
  journey runs on that commit with only guide and record changes allowed. A later code
  fix needs an impact analysis and owner decision on whether 2b must rerun.

## M1 design note: candidates in supervised paper (2026-10-04)

Reading the code shows P1 is a capability gap, not only a configuration field. Nothing is
implemented yet.

**What exists.**
- `PaperServices.policy` builds one of three reference formulas by name
  (`src/applications/execute/services.py`). Each source/account observer has one
  `ServiceBookInputs` adapter that gives every instance the same touch vector (ask, bid,
  ask size) with no prediction. Preflight requires `model_identity == "rule-only"`.
- Candidate machinery exists only for dedicated accounts: `CandidateLoader` verifies a
  bundle and rebuilds its components from caller-supplied `CandidateComponents`
  factories; `CandidateSession` owns feature state, warm-up count and policy state
  together in a `CandidateCheckpoint` on a fixed cadence grid.
- Shared accounts (`SharedDecisionRuntime`, used by both the supervisor and
  `run_live_shared_paper`) keep only policy state, in the account journal. Their
  `SharedBookInputs` adapters must be pure. **No shared-account path runs a learned or
  stateful candidate today**, signed or not.
- No code is ever imported from configuration. The supervisor's CLI therefore cannot
  obtain a QR's factories, and its spawned policy workers re-import the policy class by
  module name.

**Superseded proposal.** A first proposal added a stateless candidate input adapter
beside the reference formulas, a launch script calling `run_paper_services`, and proof of
item 4 on the dedicated path only. On 2026-10-04 the owner asked for the option that is
most sustainable for long-term development and scaling, disregarding migration risk, and
approved the direction below. The earlier option is kept here only as the alternative
considered.

**Approved direction (2026-10-04).**
1. **One candidate execution model.** Shared accounts run every instance through the
   candidate session that dedicated accounts use. The account journal stores a typed
   candidate checkpoint per instance (feature state, warm-up count, policy state) in
   place of opaque policy bytes. Features, prediction and decision keep the same
   lineage on every path. Stateful features and warm-up work on shared accounts.
2. **Built-in formulas become candidates.** `fixed_clip`, `liquidity_clip` and
   `target_clip` are packaged as built-in candidates. The `policy` name literal is removed
   from `PaperServiceInstance`; every instance binds a candidate.
3. **Signed extension packages.** A QR extension package is a signed, admitted artifact
   that registers its component factories by name and version. A signed deployment binds
   the package's wheel digest and component identities. The supervisor loads components
   only from admitted installed distributions by registered identity, and operators use
   the one `alpha-execute deployment` command. The rule "no code is imported from
   configuration" becomes "code is loaded only from signed, admitted installed
   distributions by registered identity".
4. **Declared input resolution.** Inputs are source kinds resolved through the
   capability registry: native book, public trades, non-book and feature-store-served
   values. A candidate declares its inputs and the supervisor provisions and checks them
   at preflight, including online Feast serving with its service-loss and version pauses.

**Approved consequences.**
- The account journal schema changes. Under the replace-in-place rule, current code will
  refuse stage-1/2a journals. That evidence stays valid at its frozen commits and is
  never rewritten; it is no longer replayable on current code.
- Signed configuration schemas and the reference workloads' configuration identities
  change going forward.
- The platform design, study guide and engineering guide change their code-loading rule.
- 2b qualifies the new runtime. Stage-2a results remain evidence for the earlier runtime
  only. A 2a-shaped one-hour rehearsal precedes the 2b declaration.
- Each part gets its own design note on this page before its code.

## M1a design note: one candidate engine on shared accounts (approved 2026-10-04)

The owner approved this note and the recommended choice for C1–C4 on 2026-10-04.

**What the code shows.**
- The account journal (`execution.account_state`) stores each instance's continuation as
  opaque bytes. It never decodes them, which keeps the independently installed execution
  distribution free of research code. The runtime writes a `SharedDecisionCheckpoint`
  (`shared-decision`: policy state, last decision, retry identities) into those bytes.
- `SharedDecisionRuntime` runs a bare `DecisionPolicy` over a context that an input
  adapter has already built. `CandidateSession` (dedicated path) runs feature, transform,
  estimator and policy together, with warm-up, gap and restart rules, on a fixed UTC grid.
- The supervisor selects the first eligible book and then books at least
  `market_interval_us` apart; every instance on a source and account decides on that book.
- `LiveBookDecisionSource` projects only the book `imbalance` field. The reference
  formulas read ask, bid and ask size from the paper market instead.
- Every account decision carries an intent. A step that only advances state (warm-up)
  has no way to commit today.

**Design.**
1. **One engine.** `SharedStrategyBinding` binds a `LoadedCandidate`. Each due instance
   runs one `CandidateSession` step in its isolated worker process (feature, transform,
   estimator and policy together, within the existing 1–2 s reply budget). The parent
   keeps economic admission, as today.
2. **Typed continuation.** The runtime's continuation record is replaced in place by a
   `shared-candidate-decision` record: the full `CandidateCheckpoint` (feature state,
   warm-up count, policy state), the retry identities, and the step lineage (feature
   vector, prediction, decision). The journal still stores it as opaque bytes, so its
   tables do not change. Current code refuses the old record.
3. **Raw inputs, not contexts.** `SharedStrategyInput` carries the instance's causal
   `DecisionInputs` (M1c adds served feature vectors). The delivery log
   (`shared-book-delivery`) retains those inputs and is replaced in place; current code
   refuses stage-1/2a delivery logs.
4. **Built-in candidates.** The live book source also projects touch fields (ask, bid,
   ask size, bid size). A built-in touch-feature kernel and the three reference formulas
   become packaged candidates with full manifests. Service preparation writes their
   bundles. `PaperServiceInstance` binds a candidate (bundle identity and deployment);
   the `policy` literal and `ServiceBookInputs` are removed. Preflight checks policy,
   feature and model identities from the loaded candidate against the signed deployment.
5. **Scope.** Both shared paths change: the supervisor and `run_live_shared_paper`. The
   dedicated `run_paper` path already uses `CandidateSession` and keeps its own journal.

**Choices for the owner.**
- **C1 — decision schedule.** *Recommended: grid.* Each candidate decides at its own UTC
  grid instants (`starts_at + k·cadence`), as research studies and dedicated paper do,
  using the latest causal inputs at that cutoff. Matching still runs on arriving books
  before decisions. This gives exact research-to-runtime parity at matched cutoffs. It
  replaces the book-interval selection and `market_interval_us` in the signed input
  identity. *Alternative: event-driven.* Decide on selected books and relax the
  candidate's grid rule to a minimum spacing. That is closer to today's service, but
  research and runtime cutoffs differ, and the dedicated path would need the same change.
- **C2 — warm-up commits.** *Recommended: a continuation request.* The execution owner
  gains an explicit checkpoint-only account request: it commits a continuation with no
  intent and no risk reservation, under the same fencing and ordering. This changes the
  execution wire format and the signed execution release. *Alternative:* refuse warm-up
  on shared accounts (fail closed), which keeps execution unchanged.
- **C3 — dedicated path.** *Recommended: leave it for after MR17.* Retiring
  `PaperOrderJournal`/`PaperCandidateRuntime` in favour of a one-instance shared account
  would finish the convergence, but neither the journey nor 2b needs it, and the
  portable `alpha-execute paper` OMS depends on it.
- **C4 — commit shape.** *Recommended: one commit.* Items 1–5 cannot land separately
  without a temporary second path, which the format rules forbid. M1 therefore becomes
  three parts: M1a (this note), M1b (signed extension packages), M1c (declared input
  resolution).

**Findings while preparing implementation (approved 2026-10-04, F2 as recommended).**
- **F1 — grid decisions and the account clock.** Admission refuses a decision timed
  before the account's latest knowledge (`decision_precedes_account_state`). Matching a
  market and creating net orders both advance that knowledge, and net orders take the
  batch's coordination time. As implemented:
  - the market used for instant `t` is the latest eligible book at or before `t`; its
    quote is observed, and the due candidates decide at `t` from it;
  - the batch coordinates at the logical instant `t + 1 µs`, not the wall clock, so
    account knowledge stays before the book that crossed `t`;
  - that crossing book then matches orders, so new orders first meet the next book.
  Matching still runs once per instant; books between instants update monitoring only.
  Instants crossed without a fresh market or complete inputs are skipped, and the
  candidate's `on_gap` rule governs them. Replay recomputes the grid and refuses a
  retained delivery whose matching or decisions differ.
- **F2 — built-in candidates need research provenance.** `CandidateBundle` admits a
  candidate only with a completed experiment attempt, its specification and its report,
  even for `engineering` qualification. The reference formulas have no study behind them,
  and every shared-runtime test would have to run a study to build one.
  *Recommended:* split the runtime contract from provenance. A `CandidateDefinition`
  holds what execution needs (components, inputs, capability requirements, state
  contract, cadence, output). `CandidateManifest` becomes that definition plus research
  provenance, and its format is replaced in place. The loader admits a definition. A QR
  candidate is admitted from a verified bundle, so its provenance is checked as today. A
  built-in candidate is admitted from a definition whose components are registered as
  built-in in the installed distribution. *Alternative:* run a small engineering study
  to package each built-in formula during service preparation. That keeps the bundle
  contract but couples paper preparation to the research stack and makes every runtime
  test run a study.
- **Size.** M1a touches about 20 source files across `runtime`, `research`,
  `configuration`, `execution` (C2) and both paper applications, about 10 test files,
  and the capacity harness. It remains one commit (C4).

**Tests.** Shared candidate steps with warm-up, gap pause and reset, restart restore and
exact retry; grid scheduling with late, missing and burst books; built-in candidates
reproducing the reference formulas' decisions on authored inputs; refusal of the old
continuation and delivery records; preflight identity mismatches; worker timeout and
death. The full suite, the integration lane and the Linux strict mypy run pass; the
capacity harness and its stage-1/2a fixtures are updated to the new formats, and their
recorded evidence is not rerun or rewritten.

## M1a result (2026-10-04)

Implemented as approved, with F1 and F2. One commit; nothing signed or run.

**What changed.**
- **Candidate records.** `CandidateDefinition` holds what execution needs;
  `CandidateManifest` wraps it with research provenance. `CandidateObjects` holds a
  definition without provenance. The loader admits any `CandidateSource`, and
  placements bind the definition identity. The state contract adds the gap rule
  `continue`.
- **One engine on shared accounts.** `SharedStrategyBinding` binds a `LoadedCandidate`;
  each step runs in `LocalCandidateExecutor` or the isolated
  `ProcessCandidateExecutor`, which replaces the policy worker. The journal stores the
  `shared-candidate-decision` continuation as opaque bytes, so its tables are
  unchanged.
- **Warm-up (C2).** `OrderDecision.intent` may be absent: the account commits the
  continuation, reserves nothing and reports `no_intent`.
- **Grid decisions (C1, F1).** The observer decides each candidate at its UTC grid
  instants from the latest eligible market at or before the instant, coordinates at
  the instant plus 1 µs, then matches the crossing book. Deliveries are
  `shared-candidate-delivery` records; replay recomputes the grid.
- **Source fields.** `LiveBookDecisionSource` projects `imbalance`, `ask`, `bid`,
  `ask_size` and `bid_size` from one book.
- **Built-in candidates.** `ReferenceCandidates` and `AuthoredCandidates` load
  formulas or supplied components as provenance-free candidates.
  `PaperServiceInstance` binds a `ReferenceCandidate` (formula, cadence, grid
  origin); `PaperServiceSource.market_interval_us`, `ServiceBookInputs` and the
  `policy` literal are removed. The supervisor checks candidate, policy, model and
  feature identities against the signed deployment.
- **No compatibility kept.** Per the owner's instruction, superseded formats and
  fields were replaced, not deprecated: `chain` and `telemetry_seconds` are plain
  fields, and current code refuses stage-1/2a journals' continuations and delivery
  logs.

**Harness changes 2b inherits.**
- The capacity fixtures start one second after a three-second grid instant (under
  3 s after opening), so the first-touch oracle holds for any wall-clock start: the
  opening decision sees ask 100 at 2 s and the next matching book (5.04 s) follows the
  4.6 s reprice. A test proves the alignment for five wall-clock phases.
- A retained fixture anchor may now lie up to one grid period after its clock
  reading.
- Parity replay uses the observer's own replay validation instead of a duplicate
  selection model.
- "Selected book to checkpoint" now measures from the book that crosses an instant.

**Validation (as run).**

| Check | Result |
| --- | --- |
| Baseline before changes (`main` at `addfad1`, default lane) | 2,398 passed, 1 failed, 61 deselected. The failure is environmental: a setgid directory test under a `/private/tmp` base owned by group `wheel` |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (666 files), native stubs (1,559 modules), engineering, dependency, link and secret checks; 2,434 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 36 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 666 files |

## Milestones

1. **M1 — one candidate execution model (P1).** Three commits, each with its design
   note first and the full suite passing:
   - **M1a:** one candidate engine on shared accounts, built-in candidates and candidate
     binding in `PaperServiceInstance`.
   - **M1b:** signed extension packages and component registration.
   - **M1c:** declared input resolution, including feature-store serving in the
     supervisor.
2. **M2 — external import audit (P2) and guides.** The governance command; QR guide
   quickstart and extension walkthrough, development environment correction, operator
   path for a packaged candidate.
3. **M3 — journey consumer and declaration.** The journey driver and its summary;
   architectural extension through the journey (P3); the exact commands; uncounted
   rehearsals to find remaining guide gaps.
4. **M4 — MR15 R1 closure.**
5. **M5 — MR15 stage 2b** (P4–P6), under its own declaration and gates.
6. **M6 — counted journey**, recorded here, and roadmap update.

Each milestone (each M1 part) is one commit and passes the full suite, the integration lane and the
Linux strict mypy run, reported as run.

## Owner decisions (approved 2026-10-04)

The owner approved the recommended option for every decision on 2026-10-04:

1. **Record.** This page is the MR17 acceptance record.
2. **R1.** R1 closure is an MR17 prerequisite and runs before 2b. If the
   2026-09-29 to 2026-10-03 corpus survives complete, it is assessed; otherwise a fresh
   72-hour acquisition is redeclared. The corpus location is still to be confirmed.
3. **Evidence reuse.** The journey re-exercises every item-5/6 boundary on the frozen
   release; the MR07–MR14 records are scope references only.
4. **P1.** Approved, then superseded the same day by the
   [approved direction](#m1-design-note-candidates-in-supervised-paper-2026-10-04): one
   candidate execution model, built-in candidates, signed extension packages and declared
   input resolution, with the journal, signed configuration and code-loading rule
   changes that follow.
5. **P2.** The external import audit is a governance command, not part of the runtime
   wheel.
6. **J2 data.** A fresh fixed 6-hour simultaneous public capture of both venues and both
   instruments, independent of R1.
7. **J6 envelope.** Paper runs stay inside the qualified 2a envelope (at most 50 minutes,
   one-hour grants).
8. **Calendar/economics.** Explicit refusal carried through the journey.
9. **Rehearsals.** Uncounted journey rehearsals are allowed early, during M1–M3; the
   counted attempt needs separate approval.
10. **Disk.** Free space to at least 512 GiB before 2b; the prerequisite is not
    redeclared. Moving the repository out of iCloud-synced Documents is recommended.
11. **Long runs.** 2b uses a detached `nohup` driver with its own `caffeinate`, monitored
    by status files. The iCloud waiver is renewed only if syncing cannot be paused.
12. **Ordering.** P1 and P2, then guides, then the journey with rehearsals, then R1, then
    2b, then the counted journey. Code freezes at the 2b counted pass.
