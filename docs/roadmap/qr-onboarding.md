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
| P7 | No library API packages a completed study into a signed candidate bundle; M1b tests author the bundle by hand (found in M1b) | A research owner method that publishes a study's selected components as a `CandidateManifest`, in M2 with the QR guide |

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

**Steps, commands and pass criteria.** Exact commands are fixed in the
[journey declaration](#journey-declaration-approved-2026-10-04) (milestone M3); the
shape is:

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

## M1b design note: signed extension packages (approved 2026-10-04)

The owner chose S-A on 2026-10-04.

**What exists.**
- The governance builder signs and installs the `collector` and `execution` operating
  releases. Their targets contain no research code.
- The paper supervisor (`alpha-execute deployment`) runs from the full research
  distribution, which is installed without a signed release. Only the account owners
  it calls are signed targets.
- `alpha-governance-artifacts release-check` no longer fails on wheel-only
  dependencies (removed 2026-10-01); it now fails only because no operating build
  profile exists for the research distribution.
- After M1a, the signed account deployment pins each instance's candidate definition
  identity, which pins its components' `implementation_sha256`. Nothing yet ties those
  digests to installed extension code, and the supervisor can load only the built-in
  reference candidates.

**Design.**
1. **Registration.** An extension package declares its component factories under the
   entry-point group `alpha_research.candidate_components`. Each entry names a provider
   class that returns the package's `CandidateComponents`. A runtime
   `InstalledExtensions` owner loads providers only from named installed distributions
   and computes each distribution's identity from its installed `RECORD` file hashes.
   A component's `implementation_sha256` must equal that identity, so the signed
   deployment pins the exact extension code.
2. **Packaged candidates.** `PaperServiceInstance` gains a `PackagedCandidate` variant
   beside `ReferenceCandidate`: candidate bundle path, definition identity, extension
   distribution name and the UTC grid origin. The supervisor admits it only from a
   `CandidateBundle` whose research provenance verifies, with components resolved from
   the named installed extension. Code is never imported by path or module name from
   configuration.
3. **Signing.** See the choice below.

**Choice for the owner — what is signed.**
- **S-A (recommended): a signed supervisor release that includes extensions.** Add an
  operating build profile, `paper-services`, for the research distribution plus the
  selected extension wheels. The builder builds extension wheels from their source,
  admits their dependency closures and signs one release. The supervisor then runs
  through `alpha-governance-artifacts run` like the account owners, and its
  environment, platform code and extensions are all authenticated. This closes an
  existing gap (the supervisor runs unsigned today) and gives 2b and forward paper a
  fully signed runtime. Cost: a larger signed closure (the research dependencies), a
  new profile and its installation tests, and M1b becomes the largest M1 part.
- **S-B: signed extension wheels only.** The builder signs each extension wheel; a new
  governance command installs it, hash-checked and offline, into the existing unsigned
  research environment. The supervisor checks installed files against the signed
  digest. Cheaper, but the platform code around the extension stays unsigned.

**Implementation decisions under S-A (2026-10-04).**
- **Distribution.** `alpha-research-paper-services` (`packages/paper-services`) depends on
  the exact `contracts` and `execution` versions and ships the rest of what the
  supervisor imports: `runtime`, `market_data`, the research owners candidates need
  (`experiments`, `features`, `labels`, `models`, `observations`, `results`) and the
  remaining `strategies` modules. It has its own lock and no notebook, tracking or
  backtest dependencies. The supervisor's measured import closure is msgspec, pydantic
  and websockets; `research.models` exports its pandas-based study helpers lazily so
  estimator adapters load without pandas.
- **Extensions.** An extension lives in `extensions/<name>/` with its own
  `pyproject.toml`. A release selects it by listing it as a path dependency of
  `packages/paper-services`; its dependency closure then passes the same admission
  and audit as the platform.
- **Candidates in the release.** The builder signs candidate bundles into the release
  under `candidates/<definition identity>/`. A `PackagedCandidate` names the definition
  identity and the extension distribution, and the supervisor reads bundles only from
  its installed release.
- **Installer.** `paper-services` binds two commands to the signed configuration:
  `deployment` and `deployment-control`. The outer bound is the supervisor's duration
  plus 60 s. Installation runs `deployment-check`, which loads every configured
  candidate before the release is selected.

**Out of scope for M1b.** Research studies keep importing a QR's own package directly;
config-driven loading is needed only where a CLI or service must find code. Online
feature-store inputs and non-book sources are M1c.

## M1b result (2026-10-04)

Implemented as approved under S-A. One commit; nothing signed or run.

**What changed.**
- **Paper services distribution.** `alpha-research-paper-services`
  (`packages/paper-services`, its own lock) ships the supervisor, the candidate runtime
  and the research owners candidates need, without notebook, tracking or backtest
  dependencies. `research.models` exports its pandas-based study helpers lazily.
- **Operating profile.** The governance builder accepts a third operating
  application, `paper-services` (paper or shadow, configuration schema
  `paper-services`, state schema `none`). It builds the extensions listed as path
  dependencies from source, admits their closures (extensions may declare only
  external requirements), and signs candidate bundles given by `--candidates` into
  the release under `candidates/`. Provenance maps each extension wheel to its
  `extensions/<name>/src` sources. The installed launcher binds the signed
  configuration and candidates to `deployment`, `deployment-check` and
  `deployment-control`, bounds a run by its duration plus 60 s, and installation runs
  `deployment-check` before selecting the release.
- **Extension loading.** `InstalledExtensions` loads the single provider an installed
  distribution registers under `alpha_research.candidate_components`, verifies every
  installed file against `RECORD`, and stamps the `RECORD` digest on every factory as
  its implementation identity. Platform distributions cannot be named.
- **Packaged candidates.** `PaperServiceInstance.candidate` is a `ReferenceCandidate` or
  a `PackagedCandidate` (definition identity, extension, grid origin).
  `PaperServiceCandidates` resolves both against `PaperCapabilities`, the environment's
  declared paper profiles, and reads packaged bundles only from the signed candidates
  directory after their provenance verifies. `alpha-execute deployment-check` prints
  every instance's identities.
- **Reference extension.** `extensions/engineering-candidates` registers a smoothed
  imbalance feature, an imbalance target policy, a fold metric and a chart, and is
  part of the default development environment.
- **Rule change.** Platform design now states that code is loaded only from signed,
  admitted installed distributions by registered identity; guides for runtime,
  paper, execute, workflow, operations, locks, standards and tests are updated.
- **Workspace.** 14 iCloud duplicate monitor files and 5 duplicate `current 2` links
  under `logs/paper-monitoring/` were deleted.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (675 files), native stubs (1,559 modules), engineering standards (now including `extensions`), dependency admission (188 packages), link and secret checks; 2,447 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 36 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 675 files |

The first `make check` failed strict mypy in the two new test files (literal role and
capability keyword types); they were corrected before the run above.

## M1c design note: declared input resolution (approved 2026-10-04)

The owner approved T-A and F-A on 2026-10-04.

**What exists.**
- The supervisor resolves only one family of input: every candidate on a source reads
  fields projected from that source's native book (`LiveBookDecisionSource`). Live capture
  (`CaptureConfig` schema `1`) subscribes to books only, on OKX `books` and Bitfinex `R0`.
- Research studies already declare `trade` and `non-book` inputs (for example
  `captured_study.py` reads `trade_size` from retained public trades). A candidate
  packaged from such a study loads, but the supervisor has no source for those inputs and
  refuses it at preflight.
- Feature-store serving exists only for dedicated accounts (`CandidateFeatureFeed`). A
  candidate is either `source` or feature-served (`offline_features`/`online_features`),
  never both. A feature version names **exactly one** materialization at one instant.
  The online path therefore serves a frozen snapshot: during a live run it pauses as
  `stale` once the snapshot ages out, or `feature-version-changed` when a newer version
  is activated. A feature that updates during a paper run cannot be served today.
- Shared accounts (`SharedStrategyInput`, `ProcessCandidateExecutor`) carry only
  `DecisionInputs`, and the observer only builds them from book rows.

**What the journey needs.** J3–J6 use a book feature and a signed public-trade-flow
feature in one schema (a fast, intraday feature). J4 serves a QR feature online to a
candidate, with missing, stale, revised, retry and rollback faults. J6 runs both QR
candidates in the supervisor.

**Design.**
1. **One resolver.** A runtime `PaperInputs` owner maps each declared input family to a
   source the environment provisions, through `PaperCapabilities` profiles (book,
   trades, feature store). Preflight refuses any input with no provisioned source or a
   freshness, clock or unit mismatch. `PaperServiceCandidates` uses it instead of
   assuming book fields.
2. **Typed step input on shared accounts.** `SharedStrategyInput` becomes a tagged union
   of source `DecisionInputs` and a served `FeatureVector` with its lineage (definition,
   version, snapshot identity, served-at). Both executors carry it. The journal's
   continuation stays opaque bytes. Each `shared-candidate-delivery` group records the
   served lineage, so replay verifies it against the store instead of trusting it.

**Choices for the owner.**

*T — how trade inputs reach live candidates.*
- **T-A (recommended): live public trades beside books.** Capture subscribes to the
  venue's public trades channel in the same session (OKX `trades`, Bitfinex `trades`),
  retaining trades with their own venue and receipt clocks. A live trade source projects
  the same trade fields and window semantics research uses at matched cutoffs, so a
  study's trade feature runs unchanged in paper. Cost: `CaptureConfig` schema `2`
  (channel list), two new parsers and recovery rules, a new collector release, and 2b
  qualifies the extra stream.
- **T-B: trades only through the feature store.** No capture change. Trade-derived
  features reach paper only as materialized values. Their latency is the
  materialization cadence, and they need F-A to update during a run.

*F — what a feature-served deployment pins.*
- **F-A (recommended): a served stream per version.** A version pins the feature
  definition and its fitted transform; the store keeps an append-only sequence of
  materializations of that version, keyed by instant. A scheduled job extends the
  sequence. At each grid instant the supervisor reads the latest materialization at or
  before it within the declared age, checks it through the isolated Feast generation as
  today, and pauses without committing on missing, stale, future or rolled-back values.
  Activation still moves between versions explicitly, and rollback is a version change.
  Cost: the store's materialization table and its backup/restore change (replace in
  place, per the owner's no-compatibility instruction).
- **F-B: keep one snapshot per version.** The supervisor serves a pinned snapshot only.
  This suits slowly changing features (hourly or daily). The journey's online feature
  in J4 would then be a slow feature, separate from the fast features computed from
  live sources.

*Mixed inputs.* A candidate stays either source-fed or feature-served in M1c. Allowing
both in one candidate means splitting the session state model, which no journey step
needs. Defer it.

*Non-book inputs* (`valid` or `authored` clocks) reach live candidates only through the
feature store. M1c adds no live non-book feed.

**Recommended plan (T-A, F-A).** Two commits, each with the full suite:
- **M1c-1:** the resolver, the typed step input and live public trades;
- **M1c-2:** served streams in the store and feature-served candidates on shared
  accounts, with the J4 fault cases in unit and integration tests.

**Consequences.** The `CaptureConfig`, feature-store and delivery record formats change
going forward; stage-1/2a captures stay valid at their frozen commits. The 2b
declaration must name whether its workload includes trades and served features. If it
does not, the journey's use of them is unqualified for capacity.

## M1c-1 result (2026-10-04)

Implemented under T-A. One commit; nothing signed or run.

**Implementation decisions.** Two points differ from the note's wording; both narrow
the change:
- **Separate connection, not the same session.** A trades feed is its own capture
  (`CaptureConfig` channel `trades`, `depth` 0) in its own source process. The common
  runner already journals, replays, retries and quality-checks any native stream, so
  the new feed reuses it unchanged. `CaptureConfig` keeps schema `1` and book capture
  identities are unchanged. A source process now carries one feed, and a trades feed
  counts toward the eight-process envelope.
- **Trade fields.** Live and retained trades expose the same four fields: the latest
  trade's `price`, `quantity` and aggressor-signed `signed_quantity`, and `signed_flow`
  over `(at - age, at]`. Units are the feed's currencies, as research already used.
  The capability channel is `trade`, matching the input family, as the loader requires.

**What changed.**
- **Trade tapes.** `TradeTape` (`market_data.books`) with `OKXTrades` and
  `BitfinexTrades`. OKX is ready at its acknowledgement; Bitfinex starts from its
  snapshot, checks connection sequence numbers and treats the later of `te` and `tu`
  as a duplicate.
- **Live trade source.** `LiveTradeDecisionSource` replays each record through the
  same tape and requires the collector's outcome and state identity. A flow window
  must lie inside one synchronized coverage interval, and the stream must have
  delivered a boundary within its idle time. `SavedDecisionSource` gains
  `signed_quantity` and `signed_flow`, and a unit test shows live and retained trades
  give equal fields.
- **Resolution.** `PaperInputs` maps book and trade fields to their feeds and refuses
  every other family before any process starts. `PaperServiceSource.trades` adds the
  trades capture; `PaperCapabilities` adds its `trade` profile; source identity
  includes it.
- **Supervisor.** A source whose candidates read trades starts a `<source>.trades`
  child sharing the book child's observers. Book and trade deliveries for one source
  never run concurrently. A trades fault faults the source's accounts.
  `SharedPaperCaptureObserver` retains each trade delivery in a sibling
  `.trades.jsonl` log before applying it. Replay interleaves both logs by delivery
  time (`deliver_trades`, `deliver`).
- **Defect fixed (from M1a).** With two grids on one observer, an instant crossed by
  the same book could be read after a later one, which the live source refuses as a
  backwards cutoff. The live path also re-read inputs after deciding. Crossed bindings
  now read in ascending instants, and only a replay re-reads retained inputs.
- **Reference extension.** `SmoothedImbalance` takes an optional `signed_flow` input
  that confirms the signal (zero when the flow disagrees).

**Not covered by unit tests.** The supervisor's construction of a trade source
inside real observers needs a running account owner. It is exercised first by the
M3 journey rehearsals.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (684 files), native stubs, engineering standards, dependency admission (188 packages), link and secret checks; 2,473 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 36 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 684 files |

## M1c-2 result (2026-10-04)

Implemented under F-A. One commit; nothing signed or run. M1 is complete.

**What changed.**
- **Store streams.** A feature version is an append-only sequence of snapshots at
  strictly increasing cutoffs (`versions` and `(definition, version, at)` tables).
  `get_materialization(definition, version, at)` returns the latest snapshot by a
  cutoff; `retrieve_online` serves the active version's latest snapshot by the
  cutoff and reports `future` before its first one. `stream_identity` names what a
  deployment pins, replacing a single snapshot identity.
- **Publication order.** `prepare` computes a snapshot without writing it. The
  publisher (`materialize_features`) publishes and reads back its Feast generation,
  then appends it with `expected_identity`. A reader never finds a snapshot whose
  generation is absent, and a revision that arrives after preparation refuses the
  append. Calling it again with the same version and later decisions extends the
  stream.
- **Serving.** `ServedFeatures` serves a candidate's pinned stream and returns a
  `ServedFeature` (vector, stream, version, snapshot cutoff and identity) or a pause
  reason: future, stale, expired, missing, version changed or service unavailable.
  `verify` reopens a retained snapshot. `CandidateFeatureFeed` uses it for dedicated
  sessions.
- **Shared accounts.** `SharedStrategyInput` carries source `inputs` or a `served`
  feature; both executors take either. The observer serves feature-fed candidates
  at their instants and keeps pause reasons. The delivery log retains the served
  snapshot, and replay refuses a different value.
- **Supervisor.** `PackagedCandidate.feature_version` selects a bundle's packaged
  store definition; `PaperServiceConfiguration.features` (`PaperFeatureServing`)
  binds the store, Feast root and worker; preflight refuses a feature-served
  candidate without it. `PaperCapabilities(features=...)` derives the served
  inputs' profiles from the registered store definition. `deployment-check` prints
  each pinned stream. `AuthoredCandidates.load(served=..., feature_version=...)`
  builds authored feature-served candidates.

**Faults covered by unit tests.** Future, stale, expired, version rollback and
re-activation, lost Feast service and recovery, a late revision reaching only later
snapshots, a forged retained value refused on replay, a changed prepared snapshot,
and a stream regressing or naming different bytes. Matched-cutoff parity with
retained trades is in M1c-1; offline PIT parity is unchanged.

**Open for M3 and the 2b declaration.**
- **Live row production.** The store serves rows someone appends. A live paper
  candidate fed from the store therefore needs a publisher process running
  `materialize_features` on a live `DecisionSource` alongside the supervisor. The
  journey (M3) must declare that process; nothing in the supervisor starts it.
- **Serving cost.** Each served instant calls the Feast worker as a subprocess, as
  dedicated online serving already did. If 2b includes served features, its
  declaration must size this.
- **Not unit-tested.** The supervisor's construction of `ServedFeatures` and its
  preflight refusal need a running account owner; M3 rehearsals exercise them first.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (685 files), native stubs, engineering standards, dependency admission (188 packages), pip-audit, link and secret checks; 2,480 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 36 passed, 0 skipped (run on this code before the final guide edits) |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 685 files |

## M2 design note: import audit, packaging API and guides (approved 2026-10-04)

The owner approved E-A on 2026-10-04.

**What exists.**
- The ownership checker enforces private, deep and unexported imports over the
  repository's roots only (finding 4).
- No library call turns a completed study into a candidate bundle (P7). The
  maintained consumers use a 150-line test-side builder that sets factory keys,
  parameters, requirements and provenance by hand.
- A packaged candidate reaches supervised paper only if its extension is listed as a
  path dependency of `packages/paper-services`, that is, committed inside the
  repository under `extensions/`. The journey authors its extension outside the
  checkout.
- The guide gaps are listed under [documentation gaps](#documentation-gaps).

**Design.**
1. **Import audit (P2), a governance command** as decided:
   `alpha-governance-engineering-standards import-audit PATH`. It applies the
   checker's private, deep and unexported import rules and the `sys.path` mutation
   rule to every Python file under `PATH`. Each owner's `__all__` comes from the
   installed distributions: `__init__.py` source is located and parsed, never
   imported. It reports every finding and exits non-zero on any. Ownership style
   rules (module functions, lambdas) stay the repository's own and are not imposed
   on QR code.
2. **Packaging API (P7).** `research.experiments.CandidatePackager` publishes a
   `CandidateBundle` from:
   - a completed attempt (store and attempt ID);
   - its `DecisionStudy`;
   - the installed extension's name;
   - one `(factory_key, parameters)` selection per role;
   - the cadence, state contract, metric and chart contracts;
   - an optional feature-store definition.

   It builds each selected component through `InstalledExtensions` and refuses any
   whose identity differs from the one the study recorded, so a bundle cannot
   package code other than what was studied. Requirements are derived from the
   study's inputs, output and order types by one shared owner, which
   `AuthoredCandidates` then also uses. Provenance (dataset, experiment, attempt,
   report) is copied from the attempt store.
3. **Guides.**
   - **QR guide:** a runnable path from a clean machine: install the wheel; lay out
     an extension from the `engineering-candidates` template; run the import audit;
     run a study with `StudyArtifact` and `DecisionStudy.extensions` fingerprints;
     package with `CandidatePackager`; define and stream a stored feature; add a
     custom metric and chart for paper dashboards; take the candidate to paper.
   - **Development environment:** `--no-editable` everywhere, a separate
     environment for installed runs, Feast worker provisioning.
   - **Operations runbook:** one ordered path for a packaged candidate: build with
     `--candidates` (and the extension, per E below), `deployment-check`, signed
     deployment, activation, run, stop.
   - **Notebook guide:** reading a retained study result through the installed
     readers.
   - **Research program:** reviewed against the journey.

**Choice for the owner — E: how an external extension enters a signed release.**
- **E-A (recommended): the builder takes `--extension PATH`.** The paper-services
  build accepts one or more extension source directories outside the repository.
  Each must declare only requirements already in the paper-services lock, otherwise
  it is refused with guidance to add the dependency through a reviewed lock change.
  Each must also pass the import audit. The release records each extension's
  source digest and wheel, as it does for repository extensions. QRs keep their own
  repositories; the platform repository changes only when a new third-party
  dependency is admitted. This scales to many QRs without repository churn.
- **E-B: extensions are committed under `extensions/`.** A QR's extension enters a
  release by a reviewed change to this repository, which adds the path dependency
  and relocks, as M1b does. Review is explicit, but every QR change becomes a
  platform change, and the journey's "no shared-code edit" rule needs an exception
  for that step.

**Plan.** One commit: the audit command, the packager and requirements owner, E, and
the guides, with the full suite.

## M2 result (2026-10-04)

Implemented as approved under E-A. One commit; nothing signed or run.

**What changed.**
- **Import audit (P2).** `alpha-governance-engineering-standards import-audit PATH`
  applies the private, deep and unexported import rules and the `sys.path` rule to
  code outside the repository. It reads the installed owners' `__all__` without
  importing them, and the reference extension passes.
- **External extensions (E-A).** `alpha-governance-artifacts build --extensions DIR`
  audits each project, refuses platform names, scripts, uv sources and more than
  one provider, and builds its wheel. Closure admission treats it as a pure-Python
  extra root whose every requirement is already in the locked closure; the signed
  facts list it. Its source is signed under `source/external/<name>/`, and
  provenance compares every wheel member to that source.
- **Packaging API (P7).** `runtime.CandidatePackager` with `ComponentSelection`.
  It is in `runtime`, not `research.experiments` as the note proposed, because it
  builds components through installed extensions and research may not depend on
  runtime. `CandidateRequirements` is the shared requirement rule that
  `AuthoredCandidates` now uses. `InstalledExtensions.artifact` gives a study the
  installed `RECORD` to retain, whose fingerprint is the identity the packager
  requires.
- **Defect fixed (from M1c-1).** `runtime/paper_inputs.py` was missing from the
  paper-services wheel, so an installed supervisor would have failed to import it.
  An engineering test now requires every runtime module that shipped code imports
  to be shipped.
- **Guides.**
  - New [QR quickstart](../../examples/qr-quickstart.md).
  - QR guide and development environment (`--no-editable`, separate installed
    environments, Feast worker).
  - Runbook: ordered packaged-candidate path; supervised steps now start the
    supervisor from the signed paper-services target.
  - Notebook guide: reading retained study results.
  - Research program (QR code in QR extension packages; MR17 coverage).
  - Admission, workflow, coding standards and runtime guides.

**Tests added.** Import audit and CLI; external extension metadata and import
refusals; external closure edges and the collector refusal; external source
provenance; shipped runtime modules. An integration consumer runs a real study with
the reference extension, packages it, loads it and steps it from warming to decided.
It also checks the three refusals: changed parameters, a missing chart selection,
and a study that did not retain the extension.

**Not covered by tests.** No test runs `ReleaseBuilder.build` (signed builds run
only in trials), so the `--extensions` build path is first exercised by the M3
signed paper-services rehearsal.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (691 files), native stubs, engineering standards, dependency admission (188 packages), pip-audit, link and secret checks; 2,492 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed. The first attempt failed `format-check` on the new Markdown code blocks, which were then formatted |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 691 files |

## M3 design note: journey consumer and declaration (approved 2026-10-04)

The owner approved this note, T-1, P-A (with its signed schema change), M-1, R-1,
the declaration and the rehearsal scope on 2026-10-04. Legacy code that the changes
supersede is removed, not kept beside them.

**Sequencing as implemented.** J6 and J7 depend on P-A and M-1, and rehearsal 1
stops at J5. The driver therefore lands in two parts:
- M3a: the driver with J1–J5 and J8;
- after M3b: rehearsal 1;
- after M3c and M3d: M3e, the driver's J6–J7, then rehearsal 2.

Every known gap is still fixed before any rehearsal reaches it.

**What reading the code shows.** Three journey steps cannot pass on `e8dec10` as
written. Each needs an owner choice (below) before rehearsals reach it:
- **G-T — research cannot read live trades captures.** `alpha-collect` captures a
  websocket `trades` feed (M1c-1), but only the supervisor's `LiveTradeDecisionSource`
  consumes it. `DatasetPublication.publish_books` admits book captures only, and
  `SavedDecisionSource` reads trades only from the REST acquisition path
  (`alpha-acquire public`): polled, with unknown completeness and poll-time
  availability. A J3 study of signed trade flow would therefore read different trades,
  under a different availability clock, than the J6 candidate. J5's "replay decisions
  equal the study's" would fail.
- **G-P — no supported live feature publisher.** `materialize_features` extends a
  stream, but no installed command runs it on live inputs. The 2a feature processes
  are harness code under `tests/`. A QR following the quickstart (step 6) would have
  to write a long-running process from internals.
- **G-M — custom metrics never reach supervised dashboards.**
  `CandidateMonitoringExporter` takes the dedicated path's `PaperConfiguration` and
  `PaperCheckpoint`. Only `candidate_workflow.py` calls it; the supervisor's
  diagnostic process never does. J6's "custom metric on paper dashboards" and its
  alert therefore have no path for a packaged candidate on a shared account.
- **J7 account restore.** `AccountWorkspace.restore` quarantines a restored journal
  from managed activation by contract. `alpha-governance-artifacts install --state`
  binds an explicitly quiesced snapshot to a new signed target, so the journey resumes
  through that path (R-1 below). Whether the installer accepts a restored account
  journal is first exercised in a rehearsal.
- **J2 collection runs outside the signed collector.** The installed launcher bounds
  every non-account run to 180 s, so a six-hour `capture-run` cannot run through the
  signed collector target. R1 used a `--no-editable` environment's `alpha-collect`; J2
  does the same and records that as a stated limitation, not a pass of signed
  collection.
- **Disk.** 483 GiB free on 2026-10-04 (497 GiB when the record opened); M5 needs at
  least 512 GiB.

**Choices for the owner.**

*G-T — trades in research.*
- **T-1 (recommended): one capture publication path and one trade schema.**
  `DatasetPublication.publish_books` is replaced in place by one capture publication
  path. It selects the reconstruction from each capture's declared capability, so
  books and trades are published the same way, and a future stream type plugs in
  without a parallel method. Trades captures publish into the same public-trade
  partition schema that REST acquisitions use:
  - venue trade IDs, exact price and size, aggressor side and event time are kept;
  - availability is the durable receipt clock, rounded up to microseconds as for books.

  Research therefore has one trade schema with two acquisition sources: websocket
  capture for live windows, and REST for historical backfill, which websocket
  capture cannot provide. The schema is changed in place where trades captures need
  it, with no compatibility reader. `SavedDecisionSource` reads both with the same
  field and window rules, so J3, J5 and J6 read the same trades.
- **T-2: REST trades for research.** No code change. J3 reads polled REST trades;
  J5 compares only book-fed decisions exactly and reports trade-fed differences.
  The journey then cannot claim research-to-paper parity for its trade feature.

*G-P — live feature publication.*
- **P-A (recommended): a signed `feature-publisher` command.** The paper-services
  release gains a fourth bound command. It reads the supervisor's retained book and
  trades captures read-only as they grow, rebuilds the live sources, computes the
  packaged candidate's feature and fitted transform through `InstalledExtensions`,
  and calls `materialize_features` at each grid instant for the version the signed
  configuration pins. It writes only the feature store and the Feast generation
  root. Its life is bounded like the supervisor's, and it holds no account or
  venue authority. Code still loads only from the signed release. Cost: a runtime
  owner, a launcher binding, and a `PaperFeatureServing.publisher` field (cadence and
  maximum lag). That field changes the signed paper-services configuration schema
  going forward. The publisher is a runtime owner that is not tied to paper, so a
  scheduled research job can reuse it, and one publisher can feed every deployment
  that pins the same version. The store stays the only coupling between producer
  and consumer.
- **P-B: an unsigned research-environment publisher with its own websocket
  captures.** No signed change, but it duplicates every source connection beyond
  the eight-process envelope, and it loads QR code from an unsigned environment,
  contrary to the code-loading rule.

*G-M — candidate metrics on supervised paper.*
- **M-1 (recommended): one exporter, exported from the supervisor's diagnostic
  process.** `CandidateMonitoringExporter` is replaced in place. It takes one
  candidate step record (feature vector, prediction, decision, instant and
  continuation) that both the dedicated and shared paths produce, so there is one
  export path, not two. The dedicated path's caller changes with it. At the telemetry
  cadence, the diagnostic process exports each packaged candidate's runtime metric
  contracts into `monitoring/telemetry.sqlite3`, with delayed labels revised as they
  mature. A threshold alert on a candidate metric goes to the configured
  `alert_socket`. No control path returns to accounts. Cost: exporter
  generalization, diagnostic wiring, tests. 2b inherits the extra telemetry.
- **M-2: offline export after a run** from the retained delivery logs. Cheaper, but
  dashboards are not live and no alert fires during the run, so J6 would fail its
  stated criterion.

*R — J7 account resumption.*
- **R-1 (recommended):** after a quiesced backup, restore into a fresh root, install
  a fresh signed account target with `--state` bound to the restored journal
  component, reconcile independently and `claim_paper`. The supervisor resumes from
  the restored candidate checkpoints. If the installer refuses that state, the
  rehearsal stops and records it for an owner decision. It is never worked around.

**Plan, if approved as recommended.** Backward compatibility is not kept (owner,
2026-10-04): superseded code, formats and readers are replaced in place. Evidence
recorded earlier stays valid at its frozen commits. The known gaps are fixed before
any rehearsal, because rehearsing into a known failure teaches nothing. There are
four commits, and each passes the full suite, the integration lane and the Linux
strict mypy run:
- **M3a — journey driver,** with tests of its gate logic and summary schema. Nothing
  runs yet.
- **M3b — one capture publication path and one trade schema (T-1).**
- **M3c — the signed feature publisher (P-A).** Its signed schema change needs this
  approval.
- **M3d — one candidate monitoring exporter (M-1).**
- Then the rehearsals below. Every fix a rehearsal exposes is its own reviewable
  commit before the next rehearsal; guide fixes go in the same commit as the code
  they describe.
- C3 stays as approved: the dedicated paper path is retired after MR17, not in M3.

### Journey driver

`tests/integration/consumers/journey/mr17_journey.py` is a QD consumer, like the 2a
cohort driver. It is copied out of the frozen worktree by hash and run with the
installed research interpreter (`-I`). One invocation owns one fresh attempt
directory and stops at its first failed criterion. It never edits QR code and never
retries a failed step.

- **Classes.** `JourneyDeclaration` (frozen numbers, paths and windows, read from
  `declaration.json`); `JourneyCommands` (runs each argv, retains stdout and stderr,
  and appends `commands.jsonl` before the next command starts); one class per step
  (`Provision`, `Data`, `Research`, `Features`, `Candidates`, `Paper`, `Operations`,
  `Capacity`), each returning typed `Gate` rows; `JourneySummary` (writes
  `summary.json`).
- **CLI.** `run --declaration PATH --output DIR --through J1..J8`. A rehearsal may
  stop after a named step. A counted attempt must declare `--through J8` and
  `counted: true`, and the driver refuses a dirty or editable checkout and any
  QR workspace whose commit differs from the declaration.
- **What runs where.** QR steps run the QR's own scripts from the attempt's copy of
  the QR workspace with the research interpreter. Operator steps run installed
  commands: `alpha-governance-artifacts`, the signed targets through `run`, and
  `alpha-dataset`. The driver composes only operator inputs (build requests, account
  deployments, grants, observations, controls) and reads results.
- **Summary JSON** (`summary.json`, schema `mr17-journey-summary`):

  ```json
  {
    "schema": "mr17-journey-summary",
    "attempt": "rehearsal-1",
    "counted": false,
    "commit": "<frozen commit>",
    "declaration_sha256": "...",
    "qr_workspace": {"commit": "...", "tree_sha256": "..."},
    "guides": {"examples/qr-quickstart.md": "<sha256>"},
    "installed": {"research": "<RECORD sha256>", "paper-services": "<release>"},
    "started_at": "...",
    "ended_at": "...",
    "result": "passed | failed | stopped",
    "first_failure": {"step": "J3", "criterion": "...", "observed": {}},
    "steps": [
      {
        "step": "J1",
        "status": "passed | failed | not_run | pending",
        "started_at": "...",
        "ended_at": "...",
        "criteria": [{"name": "...", "passed": true, "observed": {}}],
        "commands": ["<commands.jsonl ordinals>"],
        "findings": [{"kind": "guide | code", "detail": "..."}]
      }
    ]
  }
  ```

  `stopped` means a rehearsal ended at its declared `--through` step with every run
  step passed. `pending` applies only to J8 while its prerequisites are open.

### Fresh extension package and QR workspace

- **Where.** A git repository at `~/AlphaResearchEvidence.noindex/mr17/qr-workspace/`,
  outside iCloud and the checkout. It holds the `mr17-extensions` project
  (`src/mr17_extensions/`, entry point `mr17-extensions =
  "mr17_extensions:ComponentProvider"`) and the QR's scripts under `studies/`.
  Each attempt copies the declared commit into `<attempt>/qr/` and records its tree
  digest.
- **Authoring rule.** It is written from `examples/qr-quickstart.md` and only the
  guides and files it links. `qr/SOURCES.md` lists every file read, with its digest.
  A link that leads into `tests/` (the quickstart links the packaging consumer) is
  recorded as a guide finding.
- **Independence limitation.** The author of the rehearsals also wrote the platform
  code, so "fresh QR" knowledge cannot be proven by authorship. Two mechanical
  checks bound it:
  - the import audit (P2) over the whole workspace;
  - a **guide-coverage** check: every supported name the workspace imports must
    appear in a guide the quickstart links. An uncovered name is a guide finding
    and fails J1 in the counted attempt.
- **Components** (registered keys in parentheses):

  | Component | Role | Definition |
  | --- | --- | --- |
  | `mr17.depth-imbalance` | feature | Book `imbalance` over the top five levels, from `bid_size` and `ask_size` |
  | `mr17.trade-flow` | feature | Trade `signed_flow` over 30 s, divided by its 30 s absolute volume (zero when there is none) |
  | `mr17.signals` | feature schema | One named schema holding both features |
  | `mr17.standardize` | transform | Mean and standard deviation fitted on training rows only, retained as fitted state |
  | `mr17.forward-mid-return` | label | Mid return from the instant to `instant + 60 s`, available at its end |
  | `mr17.least-squares` | estimator | Exact least squares with intercept on `Fraction`; refuses a singular design |
  | `mr17.quote-rule` | policy (order/quote) | Rule only: a one-tick-inside quote on the predicted side when both features agree beyond a threshold, otherwise cancel. It requotes only on a side or threshold change |
  | `mr17.target` | policy (target) | Learned: target position equal to the clipped prediction times a size |
  | `mr17.net-per-turnover` | metric | Net return per unit turnover, with runtime and research `applies_to` |
  | `mr17.edge-chart` | chart | Cumulative net return against turnover |

- **Candidates.** `mr17-rule` (book and trade source inputs, order/quote output,
  rule only) and `mr17-learned` (feature-served from the stored `mr17.signals`
  version, target output). Both are venue-level and take the instrument from their
  source, so ETH is added by configuration.

### Journey declaration (approved 2026-10-04)

Abbreviations used in the commands:
- `A` is `~/AlphaResearchEvidence.noindex/mr17/<attempt>`, and `C` is `$A/checkout`.
- `T` is `/private/tmp/mr17/<attempt>`, which holds the environments and sockets (each
  socket path stays under 100 bytes).
- `GA` is `$T/build/bin/alpha-governance-artifacts`, and `PY` is
  `$T/research/bin/python -I`.

**J1 — Provision.**

```sh
git -C <repository> worktree add --detach $C <frozen commit>
cd $C
uv python install
UV_PROJECT_ENVIRONMENT=$T/build uv sync --frozen --no-editable
UV_PROJECT_ENVIRONMENT=$T/research uv sync --frozen --no-editable
uv pip install --python $T/research/bin/python --no-deps $A/qr/mr17-extensions
UV_CACHE_DIR=/private/tmp/uv-cache-research-worker \
  uv sync --frozen --project configs/development/research-worker
make local-services-up
make local-services-status
$T/build/bin/alpha-governance-engineering-standards import-audit $A/qr
$GA fetch --repository $C --request $A/j1/collector-request.json \
  --policy $A/j1/policy.json --dependencies $A/j1/wheels
$GA build ... --registry $A/j1/registry      # collector, as the runbook lists
$GA verify --release <collector release> --policy $A/j1/policy.json
$GA install --release <collector release> --policy $A/j1/policy.json \
  --target $A/j1/target-collector
```

Pass criteria:
- every command exits 0;
- the installed identities of research, extension, collector and worker are recorded;
- the import audit and guide-coverage checks are clean;
- an inventory of an execution target (built in J6) shows no `research`, notebook,
  training, tracking or reporting modules.

**J2 — Data.** One fixed window, the same for all eight feeds: books and trades for
OKX `BTC-USDT` and `ETH-USDT`, and Bitfinex `tBTCUSD` and `tETHUSD`. The window is six
hours in the counted attempt (owner decision 6).

```sh
$T/research/bin/alpha-collect capture-run --config $A/j2/config/<feed>.json \
  --window $A/j2/window.json --run-directory $A/j2/runs/<feed>   # x8, concurrent
$T/research/bin/alpha-collect capture-run-replay --run-directory $A/j2/runs/<feed> \
  --max-seconds 7200                                                   # x8
PY $A/qr/studies/j2_publish.py --runs $A/j2/runs --store $A/j2/raw \
  --snapshots $A/j2/snapshots --lakefs-repository mr17-<attempt>
$T/research/bin/alpha-dataset discover --snapshots $A/j2/snapshots \
  --max-entries 100 --max-bytes 64000000
PY $A/qr/studies/j2_reopen.py --snapshots $A/j2/snapshots --lakefs-reference <tag>
```

The grant-boundary refusal runs in J6, when the first account target is installed:
an `authorize_paper` request whose instruments come from the J2 research selection,
not that account's trading universe.

Pass criteria:
- every run's replay verification passes, with original receipt and venue clocks;
- every gap is explicit in the quality report;
- reopened lakeFS bytes equal the published snapshot;
- the catalog lists every partition with its specification version and limits;
- the grant refusal leaves the account state unchanged.

**J3 — Research.** The first five hours are walk-forward development (one-hour
train, 30-minute test, 30-minute step). The last hour is holdout, consumed once by
the selected learned study.

```sh
PY $A/qr/studies/j3_study.py rule --snapshots $A/j2/snapshots --attempts $A/j3/attempts
PY $A/qr/studies/j3_study.py learned --snapshots $A/j2/snapshots --attempts $A/j3/attempts
PY $A/qr/studies/j3_study.py grid --attempts $A/j3/attempts \
  --thresholds 0.2,0.4 --horizons 30,60
PY $A/qr/studies/j3_study.py holdout --attempts $A/j3/attempts
PY $A/qr/studies/j3_publish.py --attempts $A/j3/attempts   # publish_experiments to ClearML
PY $A/qr/studies/j3_reopen.py --attempts $A/j3/attempts    # a fresh process
PY $A/qr/studies/j3_extension.py --snapshots $A/j2/snapshots --attempts $A/j3/attempts
```

`j3_extension.py` covers P3:
- ETH studies selected by configuration only;
- the trade-flow input carried from study to candidate (packaged in J5, run in J6);
- a study configuration with calendar `XNYS`, and an instrument definition of
  product `perpetual` (different economics), each refused before any source
  access or fold.

Pass criteria:
- both decision kinds are studied with costs;
- every component identity is the extension's `RECORD` fingerprint, with no
  built-in substitution;
- holdout consumption is recorded once, and a second access is refused;
- reports include the custom metric and chart;
- ClearML lists the published experiments;
- reopened results equal the originals;
- both refusals are recorded, with no attempt data written.

**J4 — Features.**

```sh
PY $A/qr/studies/j4_features.py define  --store $A/j4/store --feast $A/j4/feast
PY $A/qr/studies/j4_features.py offline --snapshots $A/j2/snapshots --store $A/j4/store
PY $A/qr/studies/j4_features.py stream  --version v1 --snapshots $A/j2/snapshots
PY $A/qr/studies/j4_features.py faults  --store $A/j4/store --feast $A/j4/feast
```

The faults step injects, in order: a late revision, TTL expiry, a missing entity, a
materialization retry after a stopped Feast worker, and a rollback from `v2` to `v1`.

Pass criteria:
- offline and online values are equal at matched cutoffs;
- no value is served before its availability;
- each fault returns its declared pause reason, and serving recovers exactly.

**J5 — Candidates.**

```sh
PY $A/qr/studies/j5_package.py --attempts $A/j3/attempts --store $A/j4/store \
  --candidates $A/j5/candidates
PY $A/qr/studies/j5_replay.py --candidates $A/j5/candidates \
  --snapshots $A/j2/snapshots --attempts $A/j3/attempts
```

`j5_package.py` uses `CandidatePackager`. `j5_replay.py` loads each bundle through
`CandidateLoader` and replays it over the holdout inputs.

Pass criteria:
- the packager refuses a changed parameter;
- replayed features, predictions and decisions equal the study's at every
  matched instant.

**J6 — Paper.** Four accounts, eight source processes (book and trades for each
instrument), eight active instances and one provisioned inactive instance. This is
inside the supported envelope.

| Account | Instances |
| --- | --- |
| `okx-shared` | `mr17-rule`@okx-btc, `mr17-learned`@okx-btc (the shared-budget race pair); inactive `mr17-rule`@okx-btc with a second grid origin (for J7) |
| `okx-isolated` | `mr17-rule`@okx-eth, `mr17-learned`@okx-eth |
| `bitfinex-shared` | `mr17-rule`@bfx-btc, `mr17-learned`@bfx-btc |
| `bitfinex-isolated` | `mr17-rule`@bfx-eth, `mr17-learned`@bfx-eth |

Commands follow the runbook's
[packaged-candidate path](../governance/operations.md#take-a-packaged-candidate-to-signed-paper):

```sh
$T/build/bin/alpha-governance-engineering-standards import-audit $A/j6/extensions/mr17-extensions
$GA fetch --repository $C --request $A/j6/services-request.json \
  --policy $A/j6/policy.json --dependencies $A/j6/wheels
$GA build --repository $C --request $A/j6/services-request.json --policy $A/j6/policy.json \
  --configuration $A/j6/services.json --dependencies $A/j6/wheels --audit $A/j6/audit \
  --key <key> --registry $A/j6/registry \
  --candidates $A/j6/candidates --extensions $A/j6/extensions
$GA verify --release <services v1> --policy $A/j6/policy.json
$GA install --release <services v1> --policy $A/j6/policy.json --target $A/j6/services
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment-check
# for each account: build, verify, install an execution target from those identities, then
$GA run --target $A/j6/target-<account> --policy $A/j6/policy.json -- account \
  --request $A/j6/requests/<account>-<install|authorize|observe|claim|serve>.json
$GA run --target $A/j6/services --policy $A/j6/policy.json -- feature-publisher ...   # P-A
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment \
  --owners $A/j6/owners.json --root $A/j6/service-root --socket $T/s/supervisor.sock
$GA run --target $A/j6/services --policy $A/j6/policy.json -- deployment-control \
  --socket $T/s/supervisor.sock --request $A/j6/controls/<identity>.json
```

Phases, all within ordinary one-hour grants:

| Phase | Supervisor life | Shape |
| --- | --- | --- |
| P-A | 30 min | Paper; reconciliation every 60 s. Selective `stop_instance` and `restart_instance` (with an observation) of `mr17-learned`@okx-btc at 10 min. Ends with an injected death of the `okx-isolated` owner while a request is in flight |
| P-B | 10 min | Recovery as the runbook's step 5: stop, inspect, reconcile, resolve the uncertain order, fresh claims, relaunch |
| S | 10 min | Shadow, on two fresh shadow targets (`okx-shadow`, `bitfinex-shadow`) with the same candidates on BTC, under their own grants |

Scenarios:
- **Shared-budget race.** On `okx-shared`, the rule candidate's quote size plus the
  learned candidate's target exceeds the account's per-instrument limit, so the
  first decisions contend for it.
- **Adverse cost.** Every scenario declares a nonzero adverse cost.
- **Alert.** A threshold on `mr17.net-per-turnover` is set so that it fires (M-1).
  A local receiver bound to `alert_socket` retains it.

Each account's orders are projected per hour against the 80-order grant before
the run, as in 2a.

Pass criteria:
- exact independent reconciliation at every round;
- cost and P&L per strategy, with gas inapplicable;
- no duplicate economic effect, and the uncertain order is never retried;
- the race is admitted once and refused once, with the account inside its limit;
- served-feature lineage is retained and verified on replay, and trades deliveries are
  retained in `.trades.jsonl`;
- exact replay of every delivery log, with only the killed owner's tail unattributed;
- the custom metric is on each account's dashboard, and the alert reached the receiver;
- shadow made zero fills;
- the research-selection grant was refused (J2).

**J7 — Operations.**

```sh
PY $A/qr/studies/j7_backup.py --workspace $A --backup $A/j7/backup   # quiesced
PY $A/qr/studies/j7_restore.py --backup $A/j7/backup --root $A/j7/restored
$GA install --release <account release> --policy $A/j6/policy.json \
  --target $A/j7/target-<account> --state $A/j7/restored/<account>   # R-1
$GA build ... --configuration $A/j7/services-v2.json ...   # revision activates the inactive instance
$GA install --release <services v2> --policy $A/j6/policy.json --target $A/j6/services
$GA rollback --release <services v1> --policy $A/j6/policy.json --target $A/j6/services
```

The backup covers the research workspace (attempts, raw store, snapshots, jobs)
through `WorkspaceBackup`, the feature store through `VersionedFeatureStore.backup`,
and each stopped account through `AccountWorkspace.backup`. After the restore, the
journey reconciles, claims and runs the supervisor for 5 minutes on the restored
state. It then runs 5 minutes on services v2 and 5 minutes after the rollback to v1.

Pass criteria:
- restored manifests and identities equal the backup;
- studies reopen and the restored store serves equal values;
- resumption needs no manual repair;
- v2 activates the inactive instance;
- after the rollback, v1's code and configuration are selected and journals keep
  their current facts.

**J8 — Capacity.** No new measurement. The step links the accepted MR15 R1 and 2b
records. It is `pending` until M4 and M5 pass, and passes only when both are
accepted.

**Evidence layout.**

```text
~/AlphaResearchEvidence.noindex/mr17/<attempt>/
  declaration.json  summary.json  steps.jsonl  commands.jsonl
  checkout/         frozen worktree, used only to build
  consumers/        driver copy and digests
  environments/     inventories of build, research, worker and every target
  qr/               QR workspace copy, SOURCES.md, import audit, guide coverage
  j1/ ... j8/       each step's inputs, outputs, logs and gate assessments
logs/mr17/<attempt> -> that directory
```

Builder keys are created per attempt under `$T/keys` (mode 0700). Sockets live under
`$T/s`, and the driver removes `$T` after the cleanup audit.

**Rehearsal scope (owner decision 9).** All rehearsals are uncounted, and each is
recorded here as run.
- **Rehearsal 1:** J1–J5 on a 30-minute J2 window, with walk-forward and holdout
  scaled to 20 + 10 minutes.
- **Rehearsal 2 onward:** J1–J7 on a 60-minute window, with J6 phases shortened to
  10/5/5 minutes.

Each rehearsal stops at its first failure for owner review. The counted attempt (M6)
uses the declared six-hour window and full phases on the code frozen at the 2b counted
pass, and it needs separate approval.

## M3a result (2026-10-04)

The driver is implemented for J1–J5 and J8, in one commit. Nothing has been run.

**What changed.**
- **Driver.** `tests/integration/consumers/journey/mr17_journey.py`:
  - It needs only `msgspec` and imports no platform code, because J1 creates the
    installed environments. Run it with `run --declaration PATH`.
  - The declaration (`mr17-journey-declaration`) fixes every input up front: the
    commit, the QR workspace commit, the evidence and temporary roots, the feeds, the
    capture window, the holdout count, the guides and the capacity records. It refuses
    a counted attempt that stops before J8 or lacks both capacity records.
  - Before J1 runs, the freeze requires a clean checkout and QR workspace at their
    declared commits. It also requires the running driver to equal the frozen
    worktree's copy.
  - `Commands` appends each record to `commands.jsonl` before the next command
    starts, including the eight concurrent J2 captures.
  - `summary.json` is rewritten after each step.
  - A declaration through J6 or J7 is refused until M3e.
- **Independent checks.** `journey_checks.py` runs under the J1 research interpreter
  with supported imports only:
  - installed, non-editable research and extension identities;
  - completed studies that pin `extension:mr17-extensions`, and the declared holdout
    count;
  - bundles reopened and tied to a completed attempt and the installed extension.
- **Guide coverage.** It scans the QR workspace's platform imports against the
  declared guides and the Markdown files they link. A rehearsal records each uncovered
  name as a guide finding; a counted attempt fails J1.

**Declaration refinements found while implementing.**
- **QR results.** Each QR script also takes `--result PATH`. It writes its own
  criteria and findings there (`{"criteria": [...], "findings": [...]}`), and the
  driver retains them under the step, prefixed with the script label. The driver's
  independent checks run in addition; they never replace these.
- **Candidates bind one instrument.** `CandidatePackager` sets a definition's
  entities from the study's economics entity. "ETH by configuration" therefore means
  ETH studies and ETH bundles built from the same extension code with changed
  configuration only. The J6 instances on ETH sources bind those ETH bundles
  (`mr17-rule-eth`, `mr17-learned-eth`).
- **Collector release.** The J1 signed collector is built with configuration schema
  `1` and state schema `none`, using the first declared feed's capture configuration.
  The first rehearsal confirms whether the builder accepts these.

**Tests.** `test_mr17_journey.py` (17 cases) covers:
- declaration and window refusals;
- unique command ordinals and per-command exits, including concurrent ones;
- guide-coverage links and uncovered names;
- refusal of unimplemented steps before any work;
- a dirty checkout failing J1 first, with a retained summary.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (694 files), native stubs (1,559 modules), engineering standards, dependency admission (188 packages), link and secret checks; 2,509 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 694 files |

## M3b design note: one capture publication path and one trade schema (approved 2026-10-04)

The owner approved this note on 2026-10-04. It makes T-1 concrete.

**What the code shows.**
- The public-trade format is REST-shaped throughout:
  - `PublicTradeObservation.receipt` is a REST `PublicReceipt`;
  - `PublicTradePartition` pins a `PublicAcquisition`;
  - `PublicTradeManifest` admits exactly one partition, which is one REST job;
  - research orders trades by `receipt.request.ordinal` and builds flow lineage
    from `receipt.raw.sha256`.
- `BookInput` is generic capture provenance (capture request, raw object, segment
  chain), but it is named and admitted as a book.
- `DatasetPublication.publish_books` is a library call only. `alpha-dataset` has CLI
  publication for REST trades (`public-publish`) and none for captures.
- Research flow over REST trades is marked `complete_tape_unproven`. The live trade
  source refuses a flow window that crosses a coverage gap. Research never checks
  coverage.

**Design.** Each item replaces the code in place; no reader of an old format is kept.
1. **`CaptureInput` replaces `BookInput`.** It is the same provenance for any captured
   stream: request, raw object, bounded prefix and segment chain. Admission selects
   the reconstruction from the capture's declared capability (`native-book` or
   `native-trades`).
2. **One trade observation.**
   - `PublicTradeObservation.receipt` becomes `origin`: either a REST `PublicReceipt`
     or a `CaptureTradeOrigin` (recording request identity, segment ordinal, record
     index, raw digest and receipt nanoseconds).
   - `ts_knowledge` for a captured trade is its durable receipt, rounded up to
     microseconds, as for books.
   - Tie-break ordering and flow lineage use `origin`'s ordinal and digest, so both
     kinds sort and hash the same way.
   - Captured trades carry no reference data; `specification_identity` is `None`.
3. **Partitions and coverage.**
   - `PublicTradePartition` pins either a `PublicAcquisition` or a trades
     `CaptureInput`.
   - A capture partition also retains its **coverage intervals**: the synchronized
     periods between tape synchronization and each gap, invalid frame or session end.
     They are derived when the capture is published, by replaying it through the same
     `TradeTape` the live source uses.
   - `PublicTradeManifest` admits one or more partitions.
4. **Research applies the live rule.** For a captured partition, `signed_flow` is
   missing when its window is not inside one coverage interval, exactly as
   `LiveTradeDecisionSource` behaves. REST partitions keep `complete_tape_unproven`,
   since their coverage is unknown.
5. **One publication path.**
   - `DatasetPublication.publish_captures(directories, ...)` replaces `publish_books`.
     It publishes book captures into one `BookDatasetManifest` and trades captures into
     one `PublicTradeManifest`, returning both snapshot identities.
   - A new `alpha-dataset capture-publish --captures DIR... --store --snapshots
     --max-records --max-bytes` command gives QRs and operators the same CLI path as
     `public-publish`.
6. **Parity proof.** A unit test feeds the same retained OKX and Bitfinex trades
   captures to `LiveTradeDecisionSource` and to `SavedDecisionSource` over their
   published snapshot. It requires equal `price`, `quantity`, `signed_quantity` and
   `signed_flow` at every matched cutoff, including a window crossing a gap.

**Consequences.**
- The public-trade manifest, observation and partition formats change, so snapshots
  published before the change no longer reopen.
- Retained REST evidence (MR01 and the R1 records) stays valid at its frozen commits.
- If the R1 corpus is assessed in M4, it is republished on the new code; its raw
  captures are unchanged.
- Callers of `publish_books` and `BookInput` change with the rename: capacity
  consumers, `captured_study.py`, `source_acceptance.py` and the guides that name them.

**Tests.**
- Capture admission for both kinds, with segment chains.
- Coverage intervals across an injected gap and a reconnect.
- Mixed REST and capture partitions in one study.
- The live/saved parity test.
- The CLI publication and discovery path.
- Refusal of a trades capture whose replay differs from its retained outcome.

## M3b result (2026-10-04)

Implemented as approved, in one commit. Nothing has been signed or run.

**What changed.**
- **One capture input.** `CaptureInput` replaces `BookInput` everywhere, including
  callers and guides. `is_trades` names a public trades capture.
- **Captured trades.** `SourceAdapters.trades` replays a trades chain, predecessors
  first, through the venue `TradeTape`. Messages are numbered from zero across
  segments, as in the live source. New contracts: `CapturedTrades`,
  `TradeBoundary` and `CaptureTradeOrigin`.
- **One trade schema.**
  - `PublicTradeObservation` has exactly one origin: `receipt` (REST) or `capture`.
    Readers use origin-neutral `instrument`, `ordinal`, `source_sha256` and
    `ts_knowledge`.
  - `PublicTradeHistory` keeps captured message `boundaries`.
  - `PublicTradePartition` pins an `acquisition` or a trades `capture`. A captured
    partition needs declared universes.
  - Reopening replays the raw capture and refuses any difference.
- **Shared coverage rule.** `TradeTapeCoverage` (in `market_data.books`) is the one
  rule that both `LiveTradeDecisionSource` and publication use.
- **Research rules.**
  - `PublicTradeReader` returns a captured source's boundaries and idle time.
  - `SavedDecisionSource` refuses every field before the first boundary, while
    unsynchronized, and when the stream is stale.
  - It refuses `signed_flow` unless the whole window lies in one covered interval.
- **Latest-trade order.** Both paths order the latest trade by venue time, then
  knowledge, then message position and index. The live source previously
  tie-broke on trade ID.
- **One publication path.**
  - `DatasetPublication.publish_captures` replaces `publish_books`. It returns a
    `CapturePublication` holding the book snapshot, if any, and one trades snapshot
    per trades chain.
  - The new `alpha-dataset capture-publish` command runs it.
  - `alpha-collect capture --snapshot-directory` uses it.
- **Journey driver.** J2 passes the QR workspace's `data/universes.json` to every
  capture run, because captured trades need declared universes.

**Implementation decisions.**
- **One partition per trades manifest.** Each trades capture chain is its own
  single-partition `public-trades` snapshot, rather than one manifest holding many
  partitions. The reader and the manifest's one-partition rule stay unchanged,
  and a study selects one trades snapshot per instrument.
- **Parity scope.** At matched cutoffs, saved and live trade fields have equal
  values and equal missing fields. Missing *reasons* can differ in wording, because
  research reports unavailable rows through `ObservationHistory`'s generic reasons.
- **Bounded live retention.** Parity assumes the live source's trade capacity is
  not exceeded. Above it, the live source moves coverage forward, so it can only
  report more missing flow windows, never different values.

**Tests.** `test_captured_trades.py`:
- live/saved parity at 144 cutoffs for OKX and Bitfinex, across synchronization, a
  gap, a reconnect and a Bitfinex reconnect snapshot that repeats an earlier trade.
  A mutation check showed it fails when research drops the stream rules;
- coverage boundaries across the gap and reconnect;
- the `capture-publish` CLI, with discovery;
- refusal when the replay differs from the retained history;
- refusal of a trades capture without declared universes.

`test_public_data.py` adds one research selection that reads a REST snapshot and a
captured snapshot together.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (696 files), native stubs (1,559 modules), engineering standards, dependency admission (188 packages), link and secret checks; 2,516 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 696 files |

## Rehearsal 1 preparation (2026-10-04)

**Driver change.** The declaration gains `lakefs_credentials`, the path of the
private lakeFS keys. The driver passes only that path to QR scripts, as
`ALPHA_LAKEFS_CREDENTIALS`; it never reads the file.

**Findings while authoring the QR workspace.** These were found before any run and
are recorded in the workspace's `SOURCES.md`.
1. **Study authoring has no guide.** The study guide shows no complete
   `DecisionStudy`, transform, estimator, label or order/quote policy; it links
   test consumers instead (finding 2 of the gap inventory).
2. **No supported lakeFS publication.** `LakeFSStorage` only resolves, reads and
   materializes. The guide's only upload example is a test consumer that calls
   lakeFS's REST API directly.
3. **`DatasetVersion` requires derived `features/` bytes**, so J2's "lakeFS publish
   and reopen" of a dataset with no features cannot pass as declared.
4. **No guide for new instrument identities.** Nothing says how to assign an
   instrument identity to a new listing, such as Bitfinex `tETHUSD`.
5. **`CapturedStudyMarket` reads a capture through `CaptureInput.admit`**, which is
   capped at 10,000 records. A 30-minute OKX book capture exceeds that.
6. **`SavedDecisionSource` re-reads its whole selection at every decision**, so
   study cost grows with decisions × records. That is workable for 30 minutes and
   not for the counted six-hour window.

Findings 3, 5 and 6 block J2's last command and J3. Rehearsal 1 therefore runs
through J2 only. It still exercises everything before them: the first signed
collector build, eight concurrent live captures with trades and universes,
`capture-publish`, discovery and reopening. The lakeFS step is expected to fail on
finding 3, and that failure is recorded as run.

**Validation of the driver change (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,516 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; strict mypy (696 files), standards, admission, link and secret checks; wheel smoke passed |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 696 files |

## Rehearsal 1 (uncounted, 2026-10-04)

**Setup.**
- Declared through J2 at commit `d9374e1`, with QR workspace `316802c`.
- The capture window was 30 minutes.
- Evidence is in `logs/mr17/rehearsal-1/`, stored outside iCloud.

**Result: failed in J1** at 07:46 UTC, 15 seconds after the start.

| Step | Commands | Outcome |
| --- | --- | --- |
| Freeze | Repository and QR workspace status, worktree, QR archive | Passed: both were clean at their declared commits, and the running driver equalled the frozen copy |
| J1 | `uv python install`, build and research environments, extension install, Feast worker, `make local-services-up`/`status`, import audit | Passed, including the import audit of the QR workspace |
| J1 | `check-environment` | **Failed** (exit 1) |
| J1 | Guide coverage, signed collector release | Not run |
| J2 | All | Not run |

**Cause: a defect in the journey's own check, not in the platform.**
`journey_checks.py` looked up the research distribution by the assumed name
`alpha-research`. The research wheel's distribution is `alpha-research-lab`, so the
lookup raised `PackageNotFoundError`. The unit tests could not catch this, because
the check runs only inside an installed environment.

**Fix (commit below).** The check now finds the distribution that installed the
`research` package through `importlib.metadata.packages_distributions()`, instead
of naming it. A run under the current non-editable environment passed all three
environment criteria.

**Validation of the fix (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,516 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 696 files |

## Rehearsal 2 (uncounted, 2026-10-04)

**Setup.** Declared through J2 at commit `c146192`, with QR workspace `316802c` and
a 30-minute capture window. Evidence is in `logs/mr17/rehearsal-2/`.

**Result: failed in J1** at `collector-build`. Everything before it passed: the
freeze, the environments, the extension install, the Feast worker, the local
services, the import audit, the environment check and the collector fetch.

**Cause: a driver defect.** The collector release policy pinned the build
environment's interpreter after resolving its symlink. That resolves to uv's base
CPython, which has no `hatchling`, so the builder's admitted-hatchling check
failed. The 2a driver deliberately pins the environment's own `bin/python`.

**Fix (commit below).** The policy pins `<build environment>/bin/python` without
resolving it.

**Probes after the fix, to avoid a long rehearsal stopping on another small defect.**
These are uncounted engineering checks, not rehearsals, run in
`/private/tmp/m17` with rehearsal 2's environments.
- **Signed collector release.** Built, verified and installed with the corrected
  policy (release `302e1124…`).
- **Live captures.** A two-minute `capture-run` with universes for OKX BTC-USDT
  books, OKX BTC-USDT trades and Bitfinex tBTCUSD trades. All three replay
  verifications passed.
- **Publication.** `capture-publish` produced one book snapshot and one trades
  snapshot per venue.
- **Reopening.** OKX had 90 trades over 95 boundaries; Bitfinex had 77 trades
  over 109 boundaries. Uncovered boundaries (4 and 6) are each feed's session
  start before synchronization and the capture end. The probe deliberately
  selected no lakeFS keys.

**QR workspace fix.** `j2_publish.py` now creates its result directory before
writing `published.json` beside the result. It is at workspace commit `e653872`.

**Validation of the fix (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,516 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 37 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 696 files |

## M3c design note: lakeFS publication, study scale and authoring guides (approved 2026-10-04)

The owner approved this note and I-A on 2026-10-04. M3c was planned as the feature
publisher (P-A). The gaps below block J2 and J3, which come first, so this note
takes M3c, and the planned parts move down one letter: P-A becomes M3d, M-1 becomes
M3e and the driver's J6–J7 become M3f.

**What the rehearsals and authoring showed.**
1. **lakeFS.**
   - `LakeFSStorage` only resolves, reads and materializes; nothing publishes.
   - `DatasetVersion` requires `raw/`, `snapshots/` *and* `features/`, a rule
     inherited from the MR04 backtest consumer, so raw published captures cannot be
     versioned.
2. **Study market.** `CapturedStudyMarket` admits the whole capture in memory
   through `CaptureInput.admit`, capped at 10,000 records. A 30-minute OKX book
   capture has about 18,000.
3. **Saved decision source.** `SavedDecisionSource.read` re-reads and re-verifies
   its whole selection at every decision, so cost grows as decisions × records.
4. **Guides.**
   - No maintained example shows a transform, estimator, label or order/quote
     policy. The study guide links test consumers instead.
   - No guide says how a new listing gets an instrument identity.

**Design.** Each item replaces code in place, and no old path is kept.
1. **lakeFS publication.**
   - `LakeFSStorage.publish(repository, branch, root, components, message)` uploads
     the named component directories through the SDK adapter, commits, and returns
     the resolved `DatasetVersion`. `LakeFSStorage.create(repository, namespace)`
     creates a repository.
   - `DatasetVersion` requires `raw/` and `snapshots/`; `features/` becomes
     optional.
   - The configured backtest, which needs derived features, keeps that requirement
     in its own admission.
   - J2 then publishes raw and snapshots, and J4 publishes a second version with
     the feature bytes.
2. **Streamed study market.** `CapturedStudyMarket` reads a published book snapshot
   (snapshot identity and request identity) through the existing streamed book
   reader. It verifies the snapshot once and yields only markets inside the
   requested window, so memory is bounded by one window, not the capture.
3. **Indexed saved decisions.** `SavedDecisionSource` reads its selection once, at
   the selection's cutoff, and builds a per-requirement timeline of projected
   values only (never full books).
   - Book fields are indexed by knowledge time.
   - Trades are indexed by event time, with every observed version. A read keeps,
     per trade, the latest version known by the cutoff, as `PublicTradeReader`
     does.
   - Captured boundaries are indexed by receipt.
   - Reference history resolves as today.
   - `read(entity, at)` is a binary search plus a scan of the flow window, so folds
     can read in any order. Results must equal today's at every cutoff; the
     existing tests and a new randomized equality test over REST revisions,
     captured gaps and books prove it.
4. **Guides and template.**
   - **Template.** The maintained template extension (`engineering-candidates`)
     gains a fitted transform, an exact estimator, a forward label and an
     order/quote policy, so every component role has a maintained example outside
     `tests/`.
   - **QR quickstart.** It gains a "Write a study" section: a complete `DecisionStudy`
     with folds, holdout, economics, metric and chart, built from those components.
     The study guide links it instead of the test consumers.
   - **Instrument identity.** The study guide and QR guide state the rule: a new
     listing gets one new canonical `InstrumentId` (a random UUID), authored once in
     the QR's configuration and never derived from a symbol.

**Choice for the owner — I: instrument identities.**
- **I-A (recommended): authored and documented.** No code change. Existing
  identities are authored UUIDs, so a derivation rule would introduce a second
  convention.
- **I-B: derived.** `InstrumentId.for_listing(venue, product, symbol)` returns a
  UUIDv5. That needs a namespace decision, and existing identities would differ
  from derived ones.

**Journey declaration changes.**
- J2's lakeFS step publishes raw and snapshots only.
- J4 adds a lakeFS version with the feature bytes.
- The driver passes the published book snapshot, not the capture directory, to the
  study.

**Plan.** One commit (M3c) with the full suite, then rehearsal 3, J1–J5 on a
30-minute window. The QR workspace gains the J3–J5 scripts, written from the new
guide.

**Consequences.**
- `DatasetVersion` admits versions without features. Retained MR04 versions still
  contain features and stay valid.
- `CapturedStudyMarket` callers and `captured_study.py` change to snapshot inputs.
- Study results are unchanged; the equality tests prove it.

## M3c result (2026-10-04)

Implemented as approved, with I-A, in one commit. Nothing has been signed or run.

**What changed.**
- **lakeFS.**
  - `LakeFSStorage.create` and `LakeFSStorage.publish` (upload, commit, resolve) go
    through the SDK adapter, with new stub declarations.
  - `DatasetVersion` requires `raw/` and `snapshots/`; `features/` is optional.
  - Objects up to 2 GiB are verified and materialized in 64 MiB ranges, so a
    capture segment never sits in memory. `read` returns only objects up to
    64 MiB.
  - The configured backtest now requires feature bytes itself.
- **Streamed study market.** `CapturedStudyMarket` takes a published book snapshot
  and request identity. It verifies the snapshot once, streams only each requested
  window, and takes an optional `max_levels` depth bound, which is part of its
  identity. `captured_study.py` is updated.
- **Indexed saved decisions.** `SavedDecisionSource` reads its selection once, at
  the selection cutoff, and answers every decision from indexes:
  - **books:** the last row known by receipt;
  - **trades:** each trade's change points in knowledge order, indexed per
    instrument by event time;
  - **captured trades:** boundaries by receipt.

  Lineage is recomputed from each cutoff's query identity, through the new
  `BookQueryReader.identity` and `ResearchReader.public_trade_versions`.
- **Template and example.**
  - **Template.** `engineering-candidates` gains `NamedProjection` (the
    registered `projection` feature), `CenterScale` (a fitted transform),
    `LeastSquares` (an exact estimator), `ForwardMidReturn` (a label),
    `TouchQuote` (a rule order/quote policy) and `PredictionTarget` (a learned
    target policy).
  - **Example.** The new maintained [study example](../../examples/qr_study.py)
    runs the rule study, the learned study and the frozen holdout over published
    captures.
  - **Guides.** The QR quickstart's step 4 is rewritten around them: capture,
    publish, instrument identity (I-A), lakeFS, and the study rules.
  - **Other guides.** The QR, study, observations, market-data and lakeFS guides
    are updated.

**Additions beyond the note, flagged for the owner.**
- **Saved touch fields.** `SavedDecisionSource` also projects `ask`, `bid`,
  `ask_size` and `bid_size`, with the live book source's units and aggregation. A
  quoting study needs a price, and research previously offered only imbalance, so
  no research quote could match paper. This is additive, with no format change.
- **`BookSnapshot.request_identities`.** The example selects a book by instrument;
  a request identity is a computed hash that discovery does not print.
- **Defect fixed (from M2).** `CandidatePackager` read the fitted transform and
  model of fold `len(folds)` instead of the last fold, `len(folds) - 1`. M2's
  packaging test had no fitted state, so it never read them. The example's
  integration test now packages a fitted two-fold study.

**Open question for the owner — A: policy abstention.**
- **The gap.** `DecisionTransition.intent` is required, and no intent means "do
  nothing". A target policy can go flat, but a quote or order policy facing a
  missing input can only invent a price or fail. The template's `TouchQuote`
  fails with a clear error.
- **Live consequence.** On live paper, a source gap would therefore fault the rule
  candidate's step.
- **Proposed (A-1).** An explicit abstain result: `DecisionTransition` with no
  intent, using the "commit continuation, no order" path M1a added for warm-up.
  It would need its own design note.
- **Alternative (A-2).** Keep failing, and require a book freshness that makes
  gaps rare. J6 would then risk an instance fault at a live gap.

**Tests.**
- `test_lakefs_versions.py`: the inventory rule; publication with ranged
  verification, including a corrupted range and a staged file that is never linked;
  and the size bounds.
- `test_captured_market.py`:
  - a capture of more than 10,000 records streamed one window at a time;
  - the depth bound and its identity;
  - live/saved equality of imbalance and touch fields at 89 cutoffs.
- `test_public_data.py`: one selection mixing REST trades with a later revision,
  captured trades with a gap and reconnect, and a captured book. The indexed source
  must equal a fresh source pinned at each of 61 cutoffs, for two entities, lineage
  included. A mutation check showed it fails when the effective-version rule is
  removed.
- `tests/integration/test_qr_study_example.py`: runs `examples/qr_study.py` as a
  script for the rule study, the learned study and the learned holdout over
  authored captures, then packages the learned study.
- `test_engineering_candidates.py`: the template registry, a train-only
  `CenterScale` fit, exact `LeastSquares` with a singular-design refusal,
  `TouchQuote` stepping back and refusing a missing touch, and `PredictionTarget`
  going flat without a prediction.

**Journey driver.** QR scripts also receive `ALPHA_CLEARML_LOCAL_ENV`, the path of the
private local-services file, for J3's ClearML publication. As with lakeFS, the driver
never reads the file.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: ruff, strict mypy (702 files), native stubs (1,559 modules), engineering standards, dependency admission (188 packages), link and secret checks; 2,527 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 38 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 702 files |

Two runs before this one failed and were fixed:
- the first, on strict mypy in `test_captured_market.py` and then on the import
  standard in `test_lakefs_versions.py`;
- the second, on one unit test that pinned the template's old registry keys.

## Rehearsal 3 (uncounted, 2026-10-04)

**Setup.**
- Declared through J3 at commit `8df9561`, with QR workspace `0f4ba88` and a
  30-minute capture window.
- It ran 09:55–10:27 UTC. Evidence is in `logs/mr17/rehearsal-3/`.

**Result: failed in J2.**
- **J1:** all 29 criteria passed, including the signed collector build, verify
  and install that stopped rehearsal 2.
- **J2:** six of the eight captures completed: every book feed and both Bitfinex
  trades feeds. Both OKX trades captures exited 2 with stop reason
  `readiness_deadline`. They had received 50 trades each, but the run never marked
  itself ready.
- **J3:** not run.

**Cause: a platform defect from M1c-1.**
- `capture-run`'s segment runner (`market_data.collection.rollover`) marked a feed
  ready only on a `snapshot` outcome.
- OKX trades have no snapshot; that tape synchronizes at its subscription
  acknowledgement, as M1c-1 designed. Bitfinex trades start from a snapshot, so
  they passed.
- The supervisor's paper capture does not use this rule.

**My error, recorded.** The two-minute probe after rehearsal 2 had already shown
this failure: its OKX trades run ended with `readiness_deadline`. I checked only its
stderr, which was empty, and not its exit code or stop reason.

**Fix (commit below).**
- The runner marks a feed ready on a `snapshot` *or* `acknowledgement` outcome
  once its tape or book is ready. An OKX book is still ready only after its
  snapshot.
- A regression test runs `capture-run` on an OKX trades feed with the real
  acknowledgement shape (including `connId`) and publishes the run as trades. It
  fails without the fix.

**J3–J5 dry runs while rehearsal 3 ran.** These are uncounted. They used a scratch
environment from `8df9561` and 25 minutes of authored OKX books and trades, laid out
as J2 leaves them.
- **J3:** passed.
  - The rule and learned studies, the two-variant grid, the holdout, and the
    refusal of a changed second holdout.
  - The fresh-process reopen, with the custom metric and chart.
  - ETH studies selected by configuration, and the `XNYS` and perpetual-product
    refusals.
  - ClearML publication was not exercised, so as not to route the private key
    path through my own commands.
- **J4:** passed, except the lakeFS version, which was not exercised.
  - Offline equals recomputation at 51 cutoffs, with no future leakage.
  - The stream extends, and online matches offline.
  - Expiry and missing entities are explicit.
  - Publication fails closed with the Feast worker down, and the retry succeeds.
  - Rollback serves the previous version, and a late revision reaches only later
    cutoffs.
- **J5:** passed. Both candidates package, a changed parameter is refused, and
  replay through `CandidateLoader` equals the studies' decisions (18 learned, 10
  rule).

**Declaration corrections.**
- **J3 refusal criterion.** A capability refusal (calendar `XNYS`) is retained as a
  failed attempt holding only its publication policy. The criterion becomes
  "refused before any input is read", not "no attempt data written".
- **Learned feature.** The learned study's feature is declared `batch` with a
  30-second expiry, so that one schema serves the study, the store and the
  candidate.
- **Learned candidate.** It is packaged source-fed until served learned features
  exist (below).

**New gaps for the owner.** Both belong to the M3d (feature publisher) design note.
1. **Served learned candidates have no path.** The loader requires a served
   candidate's stored definition to carry the fitted transform identity and the
   transformed output fields. `materialize_features` refuses any definition with a
   transform.
2. **`CandidatePackager` accepts a mismatched feature-store definition.** It
   accepted a stored definition whose schema differs from the study's; only the
   loader refused it later.

**Guide findings.** These are recorded in the QR workspace's `SOURCES.md`.
- **Stateless features:** a stateless feature must be `batch` to be fitted.
- **Feast worker command:** the guide never shows how to build it.
- **ClearML keys:** the private file's key variable names are not documented.
- **Order types:** `CandidatePackager`'s `order_types` (post-only quotes must
  declare them) is not mentioned.
- **Replay loading:** nothing shows how to load a bundle for replay.

**Validation of the fix (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,528 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 38 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 702 files |

## Rehearsal 4 (uncounted, 2026-10-04)

**Setup.**
- Declared through J5 at commit `5b6cace`, with QR workspace `39920d6` and a
  30-minute capture window.
- Before it, a two-minute live probe with the fix showed all four trades feeds
  ready, with stop reason `stop_deadline` and 146, 41, 62 and 48 trades. This time
  exit codes and stop reasons were checked.
- Evidence is in `logs/mr17/rehearsal-4/`.

**Result: failed in J2 at 11:21 UTC,** at the driver's own `discover` criterion.
- **J1:** passed.
- **J2:** all eight captures and replays passed, and `capture-publish` published
  one book snapshot (four books) and four trades snapshots.
- **Cause: a driver defect.** The driver decoded `alpha-dataset discover`'s output
  as a bare list. The command prints a `{status, result}` envelope.

**Fix (commit below).**
- The driver reads the envelope.
- It requires status `complete` and exactly one book snapshot plus one per trades
  feed.
- A unit test covers the envelope, and decoding rehearsal 4's real output gives
  five snapshots.

**Continuation by hand.** This is uncounted and recorded here as run. The remaining
QR steps ran on a scratch copy of rehearsal 4's J2 data, with rehearsal 4's frozen
research environment and Feast worker.
- **J2 reopen:** the book snapshot reopened with four partitions, and the four
  trades snapshots reopened (Bitfinex BTC: 826 trades over 1,719 boundaries, 6
  uncovered).
- **J3:** passed, as were the driver's independent research checks.
  - The rule study (111 s) and the learned study (159 s).
  - The two-variant grid, the holdout and the refused changed holdout.
  - The reopen with the custom metric and chart.
  - The ETH rule and learned studies.
  - The `XNYS` refusal (one failed attempt holding only its publication policy) and
    the perpetual refusal.
- **J4:** passed.
  - Offline equals recomputation at 56 cutoffs, with no leakage.
  - The stream extends, and online matches offline.
  - Expiry and missing entities are explicit.
  - Publication fails closed with the worker down, and the retry succeeds.
  - Rollback works, and a late revision reaches only later cutoffs.
- **J5:** the first run failed to package the rule candidate. My QR script took
  "the first rule validation study", but the grid's variants share that family, so
  it could pick a 0.4-threshold variant while declaring 0.2 parameters. QR
  workspace `ab34f0d` selects the study whose recorded policy identity the
  declared parameters rebuild. After that:
  - both candidates packaged, and a changed parameter was refused;
  - replay equals the studies (18 learned, 10 rule);
  - the independent bundle checks passed.
- **Not exercised by hand:** the lakeFS versions and the ClearML publication, which
  need the private key paths only the driver passes.

**Validation of the driver fix (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,529 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 38 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 702 files |

This commit also carries the M3d design note as a draft, not yet approved.

## Rehearsal 5 (uncounted, 2026-10-04)

**Setup.** Declared through J5 at commit `5aa3903`, with QR workspace `ab34f0d` and
a 30-minute capture window. Evidence is in `logs/mr17/rehearsal-5/`.

**Result: failed in J2 at 12:35 UTC,** at `reopen:lakefs_published`.
- **J1:** passed.
- **J2:** the eight captures, their replays, `capture-publish`, `discover` and the
  snapshot reopen all passed.
- **Cause: a defect from M3c, in `LakeFSStorage.publish`.** It passed each file's
  bytes as the SDK's `upload_object(content=...)`. The generated SDK opens
  `content` as a local file path, so the upload failed with "File name too long".
  The unit test's fake API accepted bytes and could not show this.

**Fix (commit below).**
- `publish` passes the file path.
- It takes each object's digest from a streamed read and its size from the file
  system, and refuses an empty file, which a version cannot hold.
- The stub declares `content: str` (a path).
- The fake now reads the path, as the SDK does.

The live upload path is exercised first by the next rehearsal, through the driver,
which alone passes the private key path.

**Validation of the fix (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,529 passed, 2 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 38 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 702 files |

## Rehearsal 6 (uncounted, 2026-10-04): J1–J5 passed

**Setup.**
- Declared through J5 at commit `cc1a2e6`, with QR workspace `ab34f0d` and a
  30-minute capture window.
- It ran 12:51–13:51 UTC. Evidence is in `logs/mr17/rehearsal-6/`.

**Result: `stopped` at its declared step J5, with every run criterion passed.**

| Step | Criteria | Highlights |
| --- | --- | --- |
| J1 | 29 passed | Fresh environments; extension install; import audit; non-editable research and extension identities; signed collector built, verified and installed |
| J2 | 27 passed | Eight live captures and replays. `capture-publish`: one book snapshot (four books) and four trades snapshots. Discovery lists five. Reopen: Bitfinex BTC 742 trades over 1,551 boundaries. lakeFS: 21 objects committed and reopened byte-equal |
| J3 | 26 passed | Rule and learned studies; the two-variant grid; the holdout and the refused changed holdout; ClearML publication (2 receipts); fresh-process reopen with the custom metric and chart; ETH studies by configuration; `XNYS` and perpetual refusals; independent checks |
| J4 | 15 passed | Offline equals recomputation, with no leakage; the stream, with online matching offline; a lakeFS version with features; expiry, missing entity, fail-closed publication and retry, rollback, late revision |
| J5 | 9 passed | Both candidates packaged; a changed parameter refused; replay through `CandidateLoader` equals the studies (18 learned, 10 rule decisions); independent bundle checks |

**Guide findings to close before the counted attempt.** In a counted attempt guide
coverage fails J1; this rehearsal recorded 31 uncovered names as findings. The QR
workspace imports them, but no guide reachable from the quickstart names them:

`AttemptHistory`, `BookQuery`, `CandidateBundle`, `CandidateDeployment`,
`CandidateLoader`, `CandidateStateContract`, `CapabilityProfile`,
`CapabilityRegistry`, `CapabilitySelection`, `DecimalGrid`, `DecisionContext`,
`DecisionInputs`, `DecisionSource`, `DecisionTransition`, `Dimension`,
`EstimatorLifecycle`, `FeastOfflineWorker`, `FeatureTransition`, `Fingerprint`,
`FoldSummary`, `InputRequirement`, `IntentSimulationSpec`, `LimitExecutionConfig`,
`LocalCandidateExecutor`, `Money`, `NumericField`, `OrderIntent`, `Quantity`,
`QuoteIntent`, `TargetIntent`, `WireRecord`.

Several are documented in owner guides that the quickstart does not link. Others,
such as the replay registry and deployment, are documented nowhere a QR would look.
The ClearML key names and the replay recipe are also open. These are guide work,
done with M3f.

**Not covered by this rehearsal:** J6–J8. J6 and J7 need M3d, M3e and M3f; J8 needs
M4 and M5.

## M3d design note: served learned features and the live feature publisher (approved 2026-10-04)

The owner approved this note on 2026-10-04, including the signed
`PaperFeatureServing.publisher` field. Nothing is implemented yet. This is the approved P-A
publisher, extended by the two gaps rehearsal 3's dry runs found.

**What the code shows.**
- **Served vectors must be transformed.** `CandidateLoader` admits a served
  candidate only if its stored definition carries the fitted transform identity and
  the transformed output fields. The runtime then uses the served vector as the
  transformed features. `materialize_features` refuses any definition with a
  transform, and no supported path appends transformed vectors with their Feast
  generation.
- **The packager checks too little.** `CandidatePackager` accepts a stored
  definition whose schema, transform or fields differ from the study's. Only the
  loader catches the mismatch, at deployment.
- **No live publisher exists.** No supported process extends a stream from live
  inputs (gap G-P).
- **Trades capture follows only source-fed candidates.** The supervisor starts a
  source's trades capture only when a *source-fed* candidate reads trades.
- **Where captures live.** Each feed's capture is retained under
  `<root>/runs/<run>/<source>.<feed>/<recording>/`, as fsynced journals.

**Design.** Each item replaces code in place, and no old path is kept.
1. **Fitted materialization.**
   - `materialize_features` accepts an optional fitted transform: the study's
     `FittedTransform` and its retained `TransformVersion`.
   - It computes each raw vector with the kernel and applies the retained state
     (apply only, never fit).
   - It appends the transformed vector under a definition whose
     `transform_identity` and `output_fields` equal the version's, then publishes
     and verifies the Feast generation as today.
   - A definition with a transform but no matching version, or the reverse, is
     refused.
2. **The packager checks the stored definition.** `CandidatePackager.publish(...,
   feature_store=...)` applies the loader's rule at packaging time: same schema,
   the study's transform identity and output fields. For a fitted study, the
   packager builds that definition itself from the last fold's `TransformVersion`,
   so the QR passes only a name and entity type.
3. **The live publisher (P-A).**
   - **Owner.** A `runtime.FeaturePublisher` owner and an
     `alpha-execute feature-publisher` command, bound by the signed paper-services
     launcher like `deployment`.
   - **Inputs.** For each feature-served `PackagedCandidate`, it loads the bundle's
     kernel, transform state and stored definition from the signed release through
     `InstalledExtensions`. It then follows the supervisor's retained book and
     trades journals read-only, replaying each record through `CaptureReplay` into
     `LiveBookDecisionSource`/`LiveTradeDecisionSource`.
   - **Publication.** At each candidate grid instant it materializes one snapshot
     of the pinned version through fitted materialization.
   - **Bounds.** Its life is bounded like the supervisor's. It writes only the
     feature store and the Feast generation root, and holds no account or venue
     authority.
   - **Configuration.** `PaperFeatureServing.publisher` (cadence equal to the
     candidates' and a maximum lag) is a signed configuration field, as approved
     for P-A.
   - **Trades capture.** `PaperInputs` counts the publisher's inputs, so a source
     whose served candidate needs trades still starts its trades capture.
4. **Research parity.**
   - J4 materializes the learned candidate's *transformed* vectors offline from the
     J2 captures, with the study's last `TransformVersion`.
   - J5 packages the learned candidate as served and replays it in
     `offline_features` input mode. Its decisions must equal the study's.
   - Paper (J6) reads the same stream through `online_features`.

**Tests.**
- Fitted materialization: transformed values, refusal of mismatched pairs, and
  Feast parity.
- Packager refusal of a mismatched definition, and a built definition matching the
  loader's rule.
- The publisher against authored growing journals: snapshots at grid instants,
  lag, a missing input producing no snapshot, restart, and a bounded life.
- A served replay equal to the study.
- Wiring the supervisor to a running account owner stays a rehearsal check (J6).

**Open for the owner alongside M3d.**
- **A — policy abstention**, still open from M3c. A quote policy cannot abstain on
  a missing touch, so a live data gap would fault the rule candidate.
- **M3e and M3f** (the candidate monitoring exporter, and the driver's J6–J7) follow
  M3d as planned.

## M3d-1 result (2026-10-04)

The first of two M3d commits: fitted materialization and the packager check. The
live publisher (design item 3) is M3d-2. Nothing has been signed or run.

**What changed.**
- **Fitted materialization.**
  - `materialize_features` takes an optional `transform` (`FittedTransform`) and
    `transform_version` (`TransformVersion`).
  - It applies the retained state to each raw vector and never refits. It stores
    the result under a definition whose `transform_identity` and `output_fields`
    equal the version's, then publishes Feast as before.
  - A definition and transform that do not match, or one given without the other,
    are refused before any read.
- **Packager.**
  - `CandidatePackager.feature_store(store, attempt_id, name=...)` builds the served
    definition from the study: its feature schema and, for a fitted study, the last
    fold's transform identity and output fields.
  - `publish(..., feature_store=...)` refuses any other definition.

**Tests.** `tests/integration/test_qr_study_example.py` gains a served test that
runs with the real Feast worker and skips without one:
- the packager builds the definition from the example's learned holdout study;
- materializing that definition without the transform is refused;
- materializing it with the transform stores vectors carrying the study's transform
  identity;
- the raw definition is refused at packaging, and the fitted definition packages as
  a served candidate.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` with a `staff`-group base directory | Passed: 2,529 passed, 3 skipped (optional Feast cases with no worker selected, now including the new served test), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 39 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 702 files |

## A-1 design note: explicit policy abstention (approved 2026-10-04)

The owner approved A-1 and then AB-1 on 2026-10-04. Nothing is implemented yet.

**What the code shows.**
- **Policies cannot abstain.** `strategies.DecisionTransition.intent` and
  `DecisionRecord.intent` are required, so a policy must emit an order, quote,
  target or exposure at every decision.
- **Paper already has a "do nothing" path.** Since M1a (C2), an account decision may
  carry no intent. The account then commits the continuation, reserves nothing and
  reports `no_intent`. The instance's working orders are untouched.
- **Research has no such path.** The research simulator (`LimitOrderExecution`)
  plans one order set per decision. A later decision cancels the earlier plan after
  `cancel_delay_us`, and every order expires after `lifetime_us`. A decision with no
  plan does not exist today.

**Design.**
1. **Abstention.** `DecisionTransition.intent` becomes `DecisionIntent | None`, and
   so does `DecisionRecord.intent`. A policy returns `None` to abstain; its state
   still advances.
2. **Admission.** A policy's declared output still bounds what it may emit;
   abstention is allowed for every output.
3. **Research and paper treat abstention identically,** per the choice below.
4. **Template.** `TouchQuote` abstains on a missing touch instead of failing.
   `PredictionTarget` keeps going flat, which is an intent, not an abstention.
5. **Records.** Studies, candidate steps and delivery logs record an abstention as a
   decision with no intent, so replay compares it exactly.

**Choice for the owner — AB: what abstention does to working orders.**
- **AB-1 (recommended): abstention cancels the instance's working orders.** It makes
  one rule hold in research and paper: every decision fully specifies the instance's
  desired working orders, and an abstention means none. Research already replaces
  an earlier plan at each decision, so parity holds by construction, and a new venue
  or order type implements only "replace this instance's working set". A missing
  input means the policy cannot price, so resting quotes from an earlier decision
  should not stay live.
  - **Research:** the simulator treats an abstaining decision like a new decision
    with no orders: it cancels the earlier plan after `cancel_delay_us`.
  - **Paper:** the account cancels the instance's non-terminal orders, under the same
    fencing as its `stop_instance` cancellation, and commits the continuation.
  - **Target policies:** for a held target this cancels only working orders; the
    position is unchanged.
  - **Cost:** a change in the execution owner, so a new execution release, which 2b
    qualifies anyway.
- **AB-2: abstention leaves working orders to their own lifetime.** This is the
  smallest change, because paper already behaves this way. But a research order then
  expires after `lifetime_us`, while a paper order has no matching lifetime, so the
  two would differ until both declare one.

**Tests.**
- Abstention in a study, with exact replay.
- Candidate steps that abstain.
- AB-1 cancellation in the simulator and in the account (with fencing and retry).
- The template quote abstaining on a missing touch.
- Delivery-log replay of an abstention.

## Milestones

1. **M1 — one candidate execution model (P1).** Three commits, each with its design
   note first and the full suite passing:
   - **M1a:** one candidate engine on shared accounts, built-in candidates and candidate
     binding in `PaperServiceInstance` (done 2026-10-04).
   - **M1b:** signed extension packages and component registration (done 2026-10-04).
   - **M1c:** declared input resolution, including feature-store serving in the
     supervisor: M1c-1 (resolver and live trades) and M1c-2 (served feature
     streams), both done 2026-10-04.
2. **M2 — external import audit (P2) and guides.** The governance command; QR guide
   quickstart and extension walkthrough, development environment correction, operator
   path for a packaged candidate, and the study-to-bundle API (P7). Done 2026-10-04.
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
