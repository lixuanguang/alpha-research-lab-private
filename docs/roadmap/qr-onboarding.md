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
| J7 Operations | Quiesced backup of data/features/artifacts/account state; restore into fresh roots, opened from them alone; resume from the retained journals; signed release upgrade and rollback | Restored identities equal; restored account copies quarantined; resumption from retained state without manual repair; rollback keeps current facts; decision delays within the studies' modelled delay; refusals only for paper-only account rules |
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

**J7 — Operations.** Corrected on 2026-10-05 to the approved R-2 and E-3 (the
[M3f-3 note](#m3f-3-design-note-the-journeys-j7-approved-2026-10-05)). `$B` is the
backup set `<evidence root>/<attempt>.j7-backup`, outside `$A` because a backup
cannot sit inside its source; `$A/j7/backup` links to it.

```sh
JP="PY $A/consumers/journey_paper.py"; P=$A/j6/paper
SIGNED="--launcher $GA --targets $P/targets --policy $A/j6/policy.json"
$JP quiesce --plan $P $SIGNED                     # no fence held; stop running accounts
PY $A/qr/studies/j7_backup.py --workspace $A --backup $B/research \
  --record $A/j7/research-backup.json --worker <feast worker>
$JP backup --plan $P $SIGNED --backup $B --record $A/j7/paper-backup.json
#   paper components candidates, features, service-p-a, service-p-b; then each
#   account's installed `account` command with a `backup` request
PY $A/qr/studies/j7_restore.py --backup $B/research --root $A/j7/restored/research \
  --record $A/j7/research-backup.json --worker <feast worker>   # $A/j2-j5 moved aside
$JP restore --plan $P $SIGNED --backup $B --restored $A/j7/restored \
  --record $A/j7/paper-backup.json   # each account: `restore` with its manifest digest
$JP reclaim ... ; $JP owners --plan $P            # R: from the retained journals
$GA build ... --configuration $P/services-upgraded.json ...   # revision 2 activates rule-okx-btc-late
$GA install --release <services v2> --policy $A/j6/policy.json --target $P/services
$JP reclaim ... ; $JP late ...                    # U
$JP facts ... --output $A/j7/facts-before.json
$GA rollback --release <services v1> --policy $A/j6/policy.json --target $P/services
$JP reclaim ... ; $JP facts ... ; $JP rollback-check ...   # B
$JP delays --plan $P --attempts $A/j3/attempts --roots <every paper service root> ...
$JP refusals --plan $P $SIGNED --output $A/j7/refusals.json
```

Phases R, U and B run the supervisor and publisher for 5 minutes each (rehearsals
shorten them), each ended by a `shutdown` control. U stops the late instance with
`stop_instance` 30 s before its end.

Pass criteria:
- every restored manifest equals its backup's, and studies reopen with equal reports;
- the restored QR store and the restored paper store serve equal values: the paper
  store by replaying every J6 delivery log against it exactly;
- each restored account receipt equals its backup receipt, its facts equal the
  retained journal's, and it is quarantined while the retained journal is not;
- resumption from the retained journals needs no manual repair: every command is a
  runbook step that exits 0, with J6's per-phase checks in R, U and B;
- the upgrade receipt names v1 as previous, and the late instance decides (its fills
  are retained);
- after the rollback, the receipt selects v1 with v2 as previous and the deployment
  check equals v1's; fills, costs and controls are extended unchanged, terminal orders
  are unchanged, the late instance places nothing, and U's delivery logs still replay
  exactly against the store;
- every paper decision delay is at most its study's modelled entry delay, read from
  the study's retained orders;
- every paper refusal and dropped leg carries a declared paper-only reason
  (`self_trade_conflict`, `holding_limit`, `instance_limit`, `account_limit`,
  `firm_limit`, `insufficient_cash`, `insufficient_owned_inventory`,
  `order_notional_limit`).

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

## M3d-2 result (2026-10-04)

The second M3d commit: the live feature publisher (design item 3) and the move of
materialization into `research.features`. Nothing has been signed or run live.

**What changed.**
- **One materialization path.** `applications.explore.materialize_features` is
  removed and replaced by `research.features.FeatureMaterializer.materialize`,
  with the same contract. The paper-services wheel ships `research.features` but
  not `applications.explore`, so the publisher could not use the old function.
  Research workflows, tests and guides now call the new class.
- **Following a live recording.** `market_data.storage.RecordingFollower` reads a
  recording's journal incrementally and never writes.
  - It reads only up to `cursor.json`'s offset, so a partial line is never decoded.
  - It verifies the running SHA-256 against the cursor at that offset.
  - It moves to a chain's next segment only once the current one is sealed and
    fully read. It checks that segment against the run and its predecessor's name,
    request identity and verified digest, as `CaptureRecording` does.
- **Live inputs (`runtime.live_inputs`).**
  - `LiveInputs` joins several sources into one ordered `DecisionSource`, for
    example a book source and its instrument's trade source.
  - The supervisor's observer now uses it in place of its own inline join.
  - `FollowedFeed` replays a followed recording through the collector's native
    reconstruction into a `LiveBookDecisionSource` or `LiveTradeDecisionSource`.
- **The publisher.** `applications.execute.feature_publisher.FeaturePublisher`, run
  as `alpha-execute feature-publisher --config --candidates --root`. The signed
  launcher now admits this command and binds `--config` and `--candidates` as it does
  for `deployment`.
  - It binds the supervisor's run through a `status.json` naming the same
    configuration identity and written after the publisher started, so an earlier
    run's status in the same root is never adopted.
  - It groups served instances by pinned stream and entity; instances sharing a
    stream must share source and grid.
  - It loads each bundle's kernel, transform state and stored definition through
    `PaperServiceCandidates`.
  - It follows the run's book recording, and its trades recording when the kernel
    reads trades.
  - At each grid instant it publishes once every followed feed holds a durable
    record after the instant. It materializes the pinned version with
    `FeatureMaterializer` and the fitted transform, Feast-verified before the
    snapshot is appended.
  - Its life ends when every followed recording is complete and accepted, or at
    the supervisor's own end (duration plus drain reserve). It prints a per-stream
    report: published, skipped, failures, last instant, last error.
- **Configuration.** `PaperFeatureServing.publisher` is a `PaperFeaturePublisher`
  carrying `max_lag_seconds` (1 to 300).
  - `PaperServiceCandidates.published_inputs` counts a served stream's fields when
    the publisher is declared, so a source starts its trades capture when a served
    stream reads trades.
  - Those fields now enter the source's projected requirements, so they also
    change that source's identity.
- **Packaging.** `runtime/live_inputs.py` is added to the paper-services wheel, and
  `FeaturePublisher` is exported lazily from `applications.execute`.

**Departures from the approved note.**
1. **Where the owner lives.** The note named `runtime.FeaturePublisher`. The
   publisher composes `PaperServiceCandidates` and the supervisor's layout, and
   `runtime` may not depend on `applications`. So the owner lives in
   `applications.execute`, and its reusable parts (`LiveInputs`, `FollowedFeed`) live
   in `runtime`.
2. **Clocks.** Each record is accepted on its receipt clock, the deterministic saved
   reconstruction both live sources support, not on the publisher's own read time.
   The published stream therefore equals what an offline reader of the same journals
   computes, and a restart reproduces it.
3. **Configuration.** The note listed "cadence equal to the candidates' and a
   maximum lag". The signed field carries only the lag. The cadence comes from the
   candidates' signed definitions, so it cannot disagree with them.
4. **Lag rule.** An instant not published within the lag is skipped, whether its
   feeds were late or the publisher was behind. A failed publication is retried
   until then.
5. **Limits, each failing closed.**
   - Only batch feature definitions are served. An incremental definition binds one
     checkpoint instance, which would clash with its offline history.
   - One recording per feed: a restarted source stops the publisher with an error.
   - Rows carry the live projection as their source and the supervisor run as their
     dataset, and checkpoints are scoped to that run.

**Open point for J6/J7 (owner decision before M3f).**
- **What paper decides on.** At a grid instant the supervisor's observer serves the
  latest snapshot published *by then*. The publisher can publish instant t only
  after a record later than t exists on every feed, plus a Feast call. So a live
  decision at t will usually read the snapshot of t − cadence, still within the
  candidate's maximum age.
- **What replay compares.** The delivery log retains the exact snapshot served, and
  replay verifies it. An `offline_features` replay at t reads the snapshot at t.
- **Consequence.** Paper-to-research parity in J7 must compare each paper decision
  with the snapshot it actually served, not expect the value at t.
- **Resolved.** The owner chose exact-instant serving; see the S-1 note.

**Tests.**
- **Follower** (`tests/unit/data/test_capture_recording.py`):
  - incremental bounded polls;
  - bytes past the cursor are never read;
  - a changed durable byte is refused;
  - a chain is followed across segments while it grows.
- **Publisher** (`tests/unit/applications/test_feature_publisher.py`, authored
  growing OKX journals):
  - joined inputs keep declared order, and undeclared or repeated requirements are
    refused;
  - a followed feed reads exactly what the saved receipt reconstruction reads;
  - instants publish only after both feeds pass them, with inputs equal to both
    journals' saved reconstruction;
  - a quiet feed holds publication, then instants beyond the lag are skipped;
  - a failed publication is retried;
  - a restart resumes after the stream's latest snapshot;
  - the schedule ends with its recordings.
- **Configuration and binding** (`tests/unit/applications/test_service_candidates.py`):
  - publisher inputs start the trades feed only when declared;
  - the lag bounds;
  - status binding refuses a stale or foreign status;
  - a run with no recording ends at the deadline;
  - an incremental stream is refused;
  - a configuration without a publisher is refused.
- **Launcher** (`tests/engineering/test_paper_services_release.py`): the binding for
  `feature-publisher`, and refusal of a `--config` override.
- **End to end** (`tests/integration/test_qr_study_example.py`, with the real Feast
  worker, skipped without one):
  - the example's learned holdout study packages as a served candidate;
  - its authored captures are placed as a supervisor run's recordings, and the
    publisher runs to completion;
  - at every published instant the served vector equals the one `FeatureMaterializer`
    computes from the published captures through `SavedDecisionSource` with the
    same transform.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` | Passed: 2,543 passed, 4 skipped (optional Feast cases with no worker selected, now including the publisher test), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 40 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 706 files |

A first run failed the engineering-standards check: five cross-owner imports in the
publisher bypassed public APIs, and three test helpers were module functions. Both
were fixed (`FollowedFeed` and `LiveInputs` are now exported lazily from `runtime`)
and the run above is the rerun.

## S-1 design note: exact-instant feature serving (approved 2026-10-04)

The owner chose on 2026-10-04 that a served candidate decides instant t only with
the snapshot at exactly t. This replaces "the latest snapshot available". The owner
approved this note on 2026-10-04, including the recorded-schema change in item 3
with the schema name kept. Nothing is implemented yet.

**What the code shows.**
- **Online serving is "latest available".**
  - At each crossed instant t, `SharedPaperCaptureObserver` serves an
    `online_features` candidate through `ServedFeatures.serve`. That reads the
    active version's latest snapshot by t, within the candidate's maximum age.
  - The publisher (M3d-2) can publish t only after a record later than t exists on
    every feed, plus a Feast call. So a live decision at t usually reads t − cadence.
- **Offline replay is "exactly t".** `offline_features` replay requires a snapshot
  exactly at t, which is what studies and J5 assume.
- **One pending instant per candidate.** The observer decides each crossed instant
  on the book that crosses it, from the latest eligible market at or before t. It
  remembers only the latest crossed instant per candidate.
- **Coordination is fixed in the log.** `SharedDecisionGroup` requires
  `coordinated_at == at + 1µs`. `SharedBookDelivery` requires a delivery that decides
  to also match (`matched`).

**Design.**
1. **One serving rule.** `ServedFeatures.serve` serves the snapshot exactly at t in
   both input modes, with Feast parity for `online_features` as today. "No snapshot
   at t yet" is a distinct result, `feature-pending`.
2. **Deferred decisions.**
   - When a served candidate's snapshot at t is pending, the observer keeps the
     instant open. It retains that instant's market (the latest eligible market at or
     before t, as today) and retries on each later book delivery.
   - It decides t once the snapshot exists. It skips t with the pause reason
     `feature-not-published` once the candidate's next instant is crossed, so the wait
     is bounded by one cadence and needs no new setting.
   - Source-fed candidates are unchanged and decide on the crossing book.
3. **Recorded schema change (needs approval).**
   - **Coordination.** A deferred group is coordinated when it is decided:
     `coordinated_at` is one microsecond after the delivery that preceded the
     deciding delivery, and at least `at + 1µs`. The invariant becomes
     `at + 1µs ≤ coordinated_at < delivery.available_at`. Account knowledge therefore
     never precedes a book already matched, and the decision's quote stays the
     instant's market.
   - **Matching.** `matched` may now accompany a deferred decision: a delivery that
     decides also matches its own book, as today.
   - **Unchanged.** Existing logs satisfy the new invariant, so no record is
     reinterpreted. The schema name stays `shared-candidate-delivery`, because the
     change only widens what it accepts. If you prefer a version bump, it would be
     `shared-candidate-delivery-2`; I do not recommend one, since no consumer reads
     the field differently.
4. **Replay.** Replay accepts a retained group only for an instant crossed earlier
   and not yet decided, with its coordination inside the widened bounds. It then
   verifies the exact served snapshot as today. Replay never consults whether the
   snapshot existed at the time; the log is the evidence.
5. **Latency is measured.**
   - The decision delay (`coordinated_at − at`) is already retained.
   - Monitoring reports its distribution per candidate. J7 checks that the study's
     simulated entry delay is at least the observed decision delay.
   - Research gets no new feature now.
6. **Release.** This changes the paper-services release, which stage 2b qualifies
   anyway, as with AB-1.

**Tests.**
- A served instant decides once its snapshot appears, from the instant's market,
  with coordination inside the bounds.
- A snapshot that never appears skips the instant at the next crossing with
  `feature-not-published`.
- A late snapshot never serves a later instant's value.
- Exact replay of deferred decisions, and refusal of a retained group coordinated
  outside the bounds or for an undecided-later instant.
- `ServedFeatures` refuses "latest" and returns `feature-pending`.
- The integration publisher test, extended with the supervisor's observer in
  process: paper decisions read exactly the research values at t.

**Sequencing.** One commit, after M3d-2 and before the AB-1 abstention commit. Both
touch `SharedPaperCaptureObserver`, and doing this first keeps AB-1's cancellation
rule unaffected by deferral.

**Addendum B (approved 2026-10-04): the quote of a deferred decision.** Item 2's
"retains that instant's market" cannot be admitted. By the time a deferred decision
is made, the account has observed and matched later markets, and its valuation clock
never moves back. The account also requires a decision's quote to be its latest
observed quote. The owner approved option B:
- **Quote.** A group's quote is the latest eligible market known at coordination.
  For a decision on the crossing book this is the instant's market, unchanged; for a
  deferred one it is a later market.
- **Bounds.** The supervisor log's quote bound moves from `SharedStrategyInput`
  (quote no later than the instant) to the group and the runtime (quote strictly
  before coordination).
- **Account decision time.** It is the later of the feature instant and the quote's
  time, when both were known. Every existing decision keeps its time. Account
  admission is unchanged, so no execution-owner change is needed.

## S-1 result (2026-10-04)

Exact-instant serving with addendum B. Nothing has been signed or run live.

**What changed.**
- **Serving.** `ServedFeatures.serve` serves only the pinned version's snapshot
  exactly at the cutoff in both modes, through the new
  `VersionedFeatureStore.exact_materialization`. Online, a missing snapshot is
  `feature-pending`, and the pinned version must be active. Offline, a missing
  snapshot is an error, as before. `verify` also requires the retained snapshot to
  be the cutoff's own. The "latest by the cutoff within the maximum age" path and
  `ServedFeatures.maximum_age_us` are removed.
- **Observer.**
  - Each crossed instant opens if an eligible market at or before it exists.
  - On every eligible delivery, open instants are tried in ascending order. A
    decided group is quoted at the latest market known before that delivery and
    coordinated at the later of instant + 1 µs and the preceding delivery + 1 µs.
  - A source-fed instant decides or closes on its crossing delivery, as before.
  - A served instant stays open while `feature-pending`. It is skipped as
    `feature-not-published` when the delivery that opens its candidate's next
    instant still cannot decide it. That same delivery decides it first if its
    snapshot has just appeared.
  - Replay recomputes the open instants, the quote and each coordination clock,
    and refuses any difference.
- **Schema (approved items 3 and B).**
  - `SharedDecisionGroup` requires `at + 1µs ≤ coordinated_at` and a quote
    strictly before coordination.
  - `SharedBookDelivery` requires coordination no later than the delivery.
  - A delivery that decides still matches its book.
  - `SharedDecisionRuntime.evaluate` refuses inputs or quotes at or after
    coordination, and dates each account decision at the later of the instant and
    the quote time.
- **Docs.** The runtime and feature-store guides describe the rule. The feature
  guide's stale claims (an incremental instance always required, unfitted kernels
  only) are corrected.

**Departures from the note.**
- **Monitoring.** Reporting the distribution of decision delay is moved to M3e,
  the candidate monitoring exporter. The delay itself is retained in every group
  (`coordinated_at − at`).
- **Integration test.** The note's integration test with the observer in process
  is not added. Exactness is covered by composition: the publisher integration
  test proves the published values equal research's at t, and the observer unit
  tests prove paper decides only on the snapshot at t. J6 checks the composition
  live.

**Tests.**
- **Serving:**
  - an instant reads its own snapshot or `feature-pending`;
  - a retained feature from another cutoff is refused;
  - pending, rollback and unavailable reasons;
  - an offline cutoff without its snapshot is refused;
  - online pending and expired pause before any Feast call.
- **Deferral** (`test_served_decisions_wait_for_their_snapshot_and_replay_exactly`):
  - an instant without a snapshot is skipped as `feature-not-published` once the
    next instant decides;
  - an instant whose snapshot is published after it opened decides on the next
    delivery, coordinated after the preceding delivery and quoted at the market
    known then;
  - exact replay into a fresh journal, and an exact no-op retry into the live
    journal;
  - a forged served value or coordination is refused.
- **Schema:** coordination before the instant or after the delivery is refused, and
  a quote at or after coordination is refused by the runtime.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` | Passed: 2,543 passed, 4 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 40 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 706 files |

A first run failed 8 public-paper workflow cases (the same 8 in the unit and
integration lanes) with "shared decision names an instant that is not open". Opening
an instant skipped instants the account had already committed, so replaying a
retained log into the same journal, an exact retry, could not reopen them. Opening
now depends only on the delivery stream, and the committed-instant check moved to
live decision-making. The new no-op retry case fails on the old code and passes now.
The run above is the rerun.

## Extension identity defect (found 2026-10-04)

**Found while dry-running the updated J4 and J5.** M1b defined an extension's
identity as the SHA-256 of its whole installed `RECORD`. That file also lists what an
installer writes: `direct_url.json` (the source path), `INSTALLER`, `REQUESTED` and
uv's cache files. So the same extension code installed from another path got
another identity:
- rehearsal 4's environment, installed from `<attempt>/qr/mr17-extensions`;
- the scratch environment, installed from the QR workspace.

Packaging then refused a study made in the other environment.

**Why it matters for J6.** A QR's studies pin the research environment's identity,
while the signed paper-services release installs the extension from its own wheel.
Every packaged candidate would have been refused by the supervisor.

**Fix (commit below).** This keeps M1b's approved `RECORD`-based identity and its
intent, that the signed deployment pins the exact extension code.
- Every recorded file is still verified against `RECORD`.
- The identity is now the SHA-256 of the **code inventory**: the sorted `RECORD`
  entries of the package files, plus `METADATA` and `entry_points.txt`.
- Installer-written files and bytecode caches are excluded.
- `InstalledExtensions.artifact` retains that inventory as the study artifact.

**Tests.**
- Two installs differing only in installer files and bytecode get one identity, and
  changed code changes it.
- The two real `mr17-extensions` installs that disagreed now agree
  (`5a8be3f9…`).
- The existing identity test now checks the inventory.

**Consequences.** Extension identities change once, so studies and bundles made
before this commit no longer package or load with the current code. Recorded
rehearsals stay valid at their own commits.

**Validation.** This ran on a tree that also held uncommitted M3d-2 work, which is
not in this commit.

| Check | Result |
|---|---|
| `make check` | Passed: 2530 passed, 3 skipped, 25 performance deselected; wheel smoke passed |
| Integration lane | 39 passed |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 703 files |

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

**Widened AB-1 (approved 2026-10-05): every decision replaces the instance's
working orders.**
- **Why AB-1 had to widen.**
  - AB-1 assumed paper replaces an instance's working orders at each decision, as
    research does. It does not.
  - Account admission only adds a decision's orders, and paper matching cancels an
    order only after an explicit request, from an instance stop or an operator.
  - So for order and quote candidates, paper accumulated orders at every decision
    while research replaced its plan. Reserved exposure grew until the budget
    rejected new decisions.
- **Rule.**
  - When the account admits a decision for an instance, with or without an intent,
    it first requests cancellation of that instance's live orders at the decision
    time, under the fencing `stop_instance` uses (shared physical parents included).
    It then admits the new orders.
  - Paper matching already applies `cancel_delay_us` to a cancel request, so the
    timing matches research's replaced plans. An abstention is the same rule with no
    new orders. The research simulator treats a decision without an intent as a plan
    with no orders.
- **Warm-up.** A warming step carries no intent either, so it also cancels the
  instance's live orders. This matters only after a restart, when old orders would
  otherwise rest with no policy managing them.
- **Rejections.**
  - A rejected decision (budget, risk) is rolled back whole, including its cancel
    requests, so its earlier orders keep working.
  - A replaced order keeps its reservation until its cancel completes, as at a
    venue. So a budget-bound candidate may be rejected where research, which models
    no budgets, is not. J7 declares and checks that difference.
- **Targets.** A target decision is no longer refused (`pending_target`) for live
  orders of its instance that already carry a cancel request; it is still refused
  for any other live order. A replaced order that fills before its cancel completes
  is reflected in the holding of the next decision.
- **Scope.**
  - The account owner, which serves the supervised paper services and the dedicated
    account path.
  - The older single-candidate `PaperOrderJournal` workflow, outside the journey,
    keeps explicit replacement only. Retiring it is proposed separately.
- **Release and records.** This is an execution-owner change and needs a new
  execution release, which stage 2b qualifies anyway. Paper journals gain cancel
  requests at each decision.
- **N1 (approved 2026-10-05): no netting across supervised instances.**
  - The account nets child orders that share a portfolio, side, price and
    time-in-force into one physical order. The supervisor gave every instance the
    portfolio `reference`.
  - So one instance's replacement would cancel a shared physical order and strand
    another instance's portion until an explicit reconcile and reissue.
  - The supervisor now binds each instance as its own portfolio
    (`portfolio_id` = instance id). A decision replaces only its own orders, and
    each candidate's fills stay its own, as research simulates them.
  - Account netting and self-trade protection are unchanged.

## AB-1 result (2026-10-05)

Explicit abstention, with every paper decision replacing its instance's working
orders and no netting across supervised instances (widened AB-1 and N1). Nothing
has been signed or run live.

**What changed.**
- **Contracts.** `DecisionTransition.intent` and `DecisionRecord.intent` accept
  `None`, which records an abstention. `PolicySession` admits an abstention for
  every declared output and still advances the policy state.
- **Research simulator.** A decision without an intent replaces the earlier plan
  like any decision, after `cancel_delay_us`, places nothing, and is recorded as
  `abstained`.
- **Paper account.**
  - `AccountAdmission.request_instance_cancels` is the cancellation `stop_instance`
    used, now shared by stopping and by replacement.
  - In paper mode, every non-protective admission first requests cancellation of
    the instance's live orders at the decision time, physical parents included.
    The event identity is `replace:<decision>:<order>`.
  - A target is held back (`pending_target`) only by live orders not already being
    replaced, directly or through their parent.
  - Venue modes and protective reductions are unchanged: replacement there needs
    the venue path to send its cancels, which is outside MR17.
- **Supervisor.** Each instance is bound as its own portfolio (`portfolio_id` =
  instance id).
- **Template.** `TouchQuote` abstains without a then-known touch. Its identity is
  now `touch-quote/2`, because its behaviour changed.
- **Docs.** The strategies, simulation, runtime and paper guides describe
  abstention and replacement.

**Consequences and open points.**
- **One existing test changed.** A new decision is no longer refused while another
  instance's stranded remainder awaits reconciliation, because it now replaces its
  own remainder. The reconciliation guard is unchanged and is exercised through the
  explicit reissue command instead.
- **The QR's own quote policy** in the workspace still refuses a missing touch.
  Abstention is now available to it through the strategies guide; adopting it is
  the QR's choice, observed in J6.
- **The older single-candidate `PaperOrderJournal` workflow** (`alpha-paper`)
  keeps explicit replacement only. It is outside the journey and superseded by the
  supervised services. Retiring it is proposed for the owner.

**Tests.**
- An abstention cancels the resting plan after cancel latency and places nothing.
- A candidate step abstains as a decided step with no intent, and the policy state
  advances.
- **Paper account:**
  - a rejected decision leaves the working order untouched (rollback);
  - an abstention requests cancellation of the instance's physical order and
    reports `no_intent`;
  - a target then proceeds past the order it replaces.
- The template quote abstains on a missing touch.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` | Passed: 2,546 passed, 4 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 40 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 706 files |

A first run failed on two counts:
- **Strict mypy.** One test list needed the now-optional intent type. That stopped
  `make check` before its unit tests.
- **Public-paper workflow (8 cases).** Its independent model did not know the
  replacement rule. The netted physical order, still partly unfilled when the next
  decision coordinated, now carries that decision's cancel request, while fills
  and economics are unchanged.

The consumer now derives replacement independently, from its retained delivery log
and the paper events: an order is replaced when a later decision of an owning
instance coordinates while it is still live.

A second run passed integration, performance and Linux strict mypy. It failed
`make check` on 2 dependency-closure tests unrelated to AB-1. Their fixture policy
had fixed dates whose review expired on 2026-10-04, so the governance check
correctly refused it from 2026-10-05. The fixture's dates now follow the calendar;
the production expiry rule is unchanged.

`make check` was then rerun alone, because only that test fixture had changed, and
passed as shown. The other three rows are from the second run. The repository's own
dependency policy review falls due on 2026-10-31.

## M3e design note: the candidate monitoring exporter (approved 2026-10-05)

M-1 (approved) chose one exporter, run from the supervisor's diagnostic process. It
writes each packaged candidate's runtime metrics to `monitoring/telemetry.sqlite3`
at the telemetry cadence, revises delayed labels as they mature, and sends threshold
alerts to `alert_socket`. S-1 added the decision-delay distribution. This note fixes
the specifics.

**What the code shows.**
- **The exporter is single-candidate only.** `runtime.CandidateMonitoringExporter`
  takes the older dedicated `PaperConfiguration` and continuation. It emits only a
  learned candidate's prediction and its outcome. Its only caller is a test consumer.
- **The diagnostics process already does most of the work.** It inspects each
  account read-only, builds per-instance P&L (`PaperScopeReport`) with attributed
  fills, and appends account events to the telemetry store. It neither loads
  candidates nor evaluates their metric components.
- **Metric components need fold evidence.** They read a `ReportContext` of
  `FoldSummary` rows: a ledger of `accounting.Fill`s, a terminal mark and a mark
  curve. Paper fills are the same `Fill` type.
- **Contracts already carry the declarations.** `CandidateMetricContract` declares
  `applies_to=("runtime", ...)`, units and `warning_below`/`warning_above`.
- **Alerts exist only for account controls.** `OperationalAlerts` journals alerts
  for those controls; `HealthAlert.deliver` is the generic local datagram.
- **Labels need data from after the decision.** A label adapter needs the base
  observation at the instant and a future one at the horizon.

**Design.** Everything replaces code in place.
1. **One exporter.** `CandidateMonitoringExporter` is rebuilt around a
   `CandidateEvidence` record: the loaded candidate, its instance and account, the
   instance's attributed paper fills, marks and decided steps. From that it emits:
   - **runtime metrics:** each runtime metric contract, evaluated by the bundle's
     own metric component over one paper fold;
   - **decision delay:** `runtime.decision-delay`, coordination − instant, per
     decided step;
   - **predictions:** `research.prediction` for learned candidates;
   - **labels:** `research.outcome`, revised as each matures.

   The old dedicated-path caller (a test consumer) moves to the new record.
2. **Paper fold — choice D1.**
   - The ledger is the instance's attributed fills, with the instance's budget limit
     as its initial cash.
   - Marks and the curve come from the supervisor's own book recording, at each of
     the candidate's grid instants. The diagnostics process follows it read-only
     with `RecordingFollower`/`FollowedFeed`, on receipt clocks as the publisher
     does.
   - So the curve is deterministic and survives a diagnostics restart.
   - The alternative is to keep marks in memory from each diagnostic sample. That is
     simpler, but a restart loses the curve.
3. **Labels — choice D2.**
   - For a learned candidate, the bundle's label adapter is evaluated from the same
     followed book source: the base at the instant, the future at instant + horizon.
   - An event is `pending` until the horizon has passed on that source, then
     revised with its value.
   - The alternative is to defer labels until after MR17: J6 does not require them,
     but M-1 did.
4. **Alerts — choice D3.**
   - A new `CandidateMetricAlerts` journal in `monitoring/` alerts once each time a
     metric crosses from inside its warning band to outside it, and records each
     attempt.
   - The alert identity is `candidate-metric:<instance>:<metric>:<sample>`. The
     message is bounded and sent through `HealthAlert.deliver` to the configured
     `alert_socket`.
   - The account-control `OperationAlert` schema is untouched. The alternative is to
     generalize it, which changes a retained schema.
5. **Wiring — choice D4.**
   - `PaperServiceDiagnostics` receives the release's candidates directory, so it
     loads candidates through `PaperServiceCandidates`, read-only and with no
     account authority.
   - It reads decided steps from the supervisor's fsynced delivery logs, tailed
     incrementally.
   - Candidate events go into the same telemetry store under each account's
     monitoring identity, so they appear on that account's dashboard.
   - The dashboard renders candidate metric events as their own panel.

**Tests.**
- **Exporter:**
  - metric values equal the component evaluated over a hand-built fold;
  - decision delays;
  - pending-then-revised labels;
  - band-crossing alerts sent exactly once and journaled;
  - an unwritable socket recorded as failed and never retried silently.
- **Diagnostics:** an integration test with authored recordings, a packaged
  candidate and an account, checking that the dashboard shows the metric and a
  local receiver gets the alert.
- **Migration:** the dedicated-path consumer migrated.

**Recommendation.** D1 (curve from recordings), D2 (labels now, as M-1 approved),
D3 (separate candidate alert journal) and D4 as written.

**R1 replaces D3 (approved 2026-10-05).**
- **Why.** A generic dashboard and alert path already exists. `MonitoringConfiguration`
  holds metric specs, dashboard panels and exact `AlertRule`s, and
  `DashboardBuilder` delivers through the existing `OperationalAlerts` journal to a
  local socket. A separate candidate alert journal would be a second alert path.
- **Rendering.** At a bounded cadence (60 s), the diagnostics process renders each
  account's dashboard with the existing builder.
- **Configuration.** The installed defaults, plus one panel per runtime metric
  contract, plus one `AlertRule` per declared warning band, addressed to
  `alert_socket`.
- **Alerts.** One alert path for all monitoring, live during the run, with no new
  schema. Existing alert semantics apply: a breach repeats once per dashboard
  cadence.

## M3e result (2026-10-05)

The candidate monitoring exporter (M-1), with D1, D2 and D4, and R1 in place of D3.
Nothing has been signed or run live.

**What changed.**
- **The exporter (rebuilt in place).** `runtime.CandidateMonitoringExporter` takes a
  loaded candidate, the account scope, mode and study, and no longer the older
  dedicated configuration. It emits:
  - **runtime metrics:** each runtime metric contract, evaluated by the bundle's own
    metric component over one paper fold (`CandidateEvidence`);
  - **decision delays:** `runtime.decision-delay`, in seconds;
  - **predictions:** `research.prediction`;
  - **outcomes:** `research.outcome` for labels the caller computes.

  `thresholds` turns each contract's warning band into a `MetricThreshold`.
- **Telemetry.** `MetricThreshold`, and `MonitoringConfiguration.paper(...,
  thresholds=...)` places an `AlertRule` for each declared band edge on the page
  that holds its series.
- **Diagnostics.** `CandidateTelemetry` runs inside the diagnostics process. The
  supervisor now passes it the run directory and the release's candidates.
  - **Each account sample:** it exports the account's instances' runtime metrics
    from the fills that sample already holds. It tails the account's fsynced
    delivery logs for newly decided instants' delays. For each learned instance it
    exports the newly committed prediction from that instance's latest continuation.
  - **Every 60 s:** it renders the account's paper pages under
    `monitoring/dashboards/<account>/<clock>-<page>/`, delivering breaches to
    `alert_socket` through `monitoring/alerts.sqlite3`.
  - **Failures** are counted in the diagnostics' failures and never reach an
    account.
- **Supporting changes.**
  - The read-only `InspectedPaperAccount` is now public.
  - The only consumer of the old exporter is migrated.
  - The quickstart and paper guide describe candidate metrics on supervised
    dashboards.

**Departures from the note.**
- **D1, simplified to research's own convention.** A study fold's curve is its
  opening mark and terminal mark. The paper fold is built the same way: the
  instance's attributed fills, its budget limit as capital, and a terminal mark at
  the latest bid in the account's sample. So the curve needs neither the recording
  nor any retained history, and it survives a restart.
- **D2, not implemented: an owner decision.** A candidate bundle has no label
  component: its roles are feature, transform, estimator, policy, metric and chart.
  Computing labels at runtime would first need the study's label component packaged
  as a new bundle role. The exporter keeps `outcome()` for labels computed
  elsewhere.
- **Predictions are sampled.** They come from each instance's latest continuation at
  each telemetry sample, so a step superseded between two samples is not exported.
  Decision delays come from the complete delivery logs.
- **Shadow accounts.** They export candidate events, but dashboards are rendered for
  paper accounts only: the paper view is paper-mode only.
- **Alert text.** Metric alerts use the existing alert journal, whose datagram text
  is `account-control:<digest>`.
- **Untested here.** Delivery-log tailing is not unit-tested; J6 exercises it.
- **Runtime labels after MR17 (owner decision, 2026-10-05).** A label component role
  in candidate bundles, and runtime label computation, are deferred until after MR17.

**Tests (`tests/unit/applications/test_service_candidates.py`).**
- **Exporter:**
  - the runtime metric equals the packaged `fold-net` component over the paper fold
    (−11/10 USDT);
  - the band threshold;
  - the decision delay and its refusal;
  - the band's rule triggers and is journaled through the existing builder.
- **Diagnostics sample:** an account sample exports the metric, renders a dashboard
  page, and delivers the alert to a bound local datagram receiver, journaled as
  `delivered`.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` | Passed: 2,548 passed, 4 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 40 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 707 files |

A first run failed strict mypy. The diagnostics test doubles in
`tests/unit/applications/test_paper_services.py` still overrode `_serve` with the old
signature, which also stopped `make check` before its unit tests. They now take the
run directory and candidates. The run above is the rerun.

## M3f-1 result (2026-10-05)

Guide coverage and shadow dashboards: the first of three M3f commits. M3f-2 adds the
driver's J6, and M3f-3 its J7.

**Guide coverage.**
- **Before.** Against the current QR workspace, 29 imported names were in none of
  the 18 documents reachable from the declared entry guides.
- **The QR API map.** `examples/qr-api.md`, linked from the quickstart's extension
  section, lists every supported name a component, study, replay or feature-store
  call needs, grouped by task, each with its import package and purpose.
  - It closes the rehearsal finding that no guide shows replaying a bundle, with a
    six-step replay recipe: capability profiles, deployment, loader and executor.
  - It states that each decision replaces working orders, and how a policy abstains.
- **ClearML keys.** The quickstart now links the ClearML local-services guide. That
  guide already named `CLEARML_LOCAL_ACCESS_KEY` and `CLEARML_LOCAL_SECRET_KEY` but
  was unreachable from the entry guides; this closes rehearsal 6's J3 finding.
- **Stale quickstart text corrected.**
  - The extension identity is the code inventory, not the whole `RECORD`.
  - A policy may abstain, which replaces the "a policy must decide at every
    decision" paragraph.
- **After.** The driver's own `GuideCoverage` finds 0 uncovered names.

**Shadow dashboards.**
- `MonitoringConfiguration.paper` is replaced by `account`, for paper or shadow
  accounts.
- Its metric specs take the query's mode, and its title names the mode.
- The diagnostics now render shadow accounts' pages too, so J6's "custom metric on
  each account's dashboard" covers the shadow phase.
- Its callers and the telemetry guide are updated.

**Tests.** A shadow-mode exporter's metric forms a shadow page with its band rule,
and a research-mode view is refused.

**Validation (as run).**

| Check | Result |
| --- | --- |
| `make check` | Passed: 2,549 passed, 4 skipped (optional Feast cases with no worker selected), 25 deselected; wheel smoke passed |
| Integration lane with the Feast worker | 40 passed, 0 skipped |
| Performance lane | 25 passed |
| Linux strict mypy | No issues in 707 files |

## M3f-2 design note: the journey's J6 (approved 2026-10-05)

The owner approved this note on 2026-10-05. It fixes the numbers the J6 declaration
left open, extends the QR's candidates to the declared instruments, and fixes how the
driver runs J6. Nothing is implemented yet.

**Frozen J6 numbers** (MR15's qualified 2a envelope, sized for live BTC and ETH).
- **Accounts.** `okx-shared` (BTC), `okx-isolated` (ETH), `bitfinex-shared` (BTC) and
  `bitfinex-isolated` (ETH), each opened with 100,000 in its quote currency.
- **Budgets.** 10,000 firm and per account, 5,000 per instance, and 1,000 maximum
  order notional.
- **Admission.** Fee rate 0.001, quote age 30 s, state age 120 s and price deviation
  500 bps.
- **Sizes and the race.**
  - BTC accounts have a position limit of 0.01. The rule candidate quotes 0.006 per
    side and the learned candidate targets 0.006, so on `okx-shared` the two contend
    for the limit: one is admitted and one refused.
  - ETH accounts have a position limit of 0.5, with 0.1 for each candidate.
- **Adverse cost.** 0.5 quote currency per base unit in every scenario.
- **Grants.** 80 orders per hour per account, each grant expiring after one hour.
- **Alert.** The QR's net-per-turnover contract declares a warning band that a short
  run cannot satisfy, so its alert fires during P-A and the receiver must hold it.

**Candidates for every declared instrument.** The QR workspace's J3 and J5 study and
package the rule and learned candidates for OKX BTC and ETH and Bitfinex BTC and ETH:
eight bundles. This roughly quadruples J3's runtime.

**How J6 runs.**
- **Platform side.** `journey_paper.py` is copied and run like `journey_checks.py`,
  with the research interpreter. It authors:
  - the services configuration, each account's configuration, deployment and
    authorization, the owners file, and the control and observation files;
  - install and claim through `InstalledPaperAccount`;
  - an independent reconciliation of every account every 60 s, from its settled
    ledger and open orders as MR15's reconciler does.
  - After each phase it checks: reconciliation, per-strategy costs and P&L, the
    race, exact replay of every delivery log, served-feature lineage, dashboards
    and the received alert, and zero shadow fills.
- **Driver side.** The driver builds, verifies and installs:
  - the services release, with the QR's candidates and extension;
  - an execution release and a target per account (and per shadow target).

  It then runs P-A, P-B and S as declared, including the owner's death and
  recovery, and records every command.
- **Rehearsals** use the declared 10/5/5-minute phases.

**Addendum Q1 (approved 2026-10-05): quote legs are admitted independently in
paper.**
- **Found while designing the race check.** A paper account admitted a quote decision
  whole or not at all. A flat instance's ask leg failed for want of owned inventory
  (`insufficient_owned_inventory`), so the whole quote was refused.
- **Why it matters.** The research simulator admits each leg on its own: it refuses
  the ask and rests the bid. The QR's rule candidate could never trade in paper, and
  J7 parity would fail.
- **The change.** Paper admission admits each leg of a quote independently.
  - A leg the instance cannot fund (inventory, cash, its budget or the position
    limit) is dropped and its reason retained in the step result
    (`StepCommit.dropped`, `DroppedLeg`).
  - A quote with no admissible leg is refused as before.
  - Single orders and targets keep all-or-nothing admission.
- **Release.** This is an execution-owner change, in the account release that stage
  2b qualifies.

**Two related findings.**
- **The race needs separate batches.** The rule and learned candidates on one account
  shared a grid origin, so they decided in one batch, which is admitted or refused
  whole. The plan now starts the learned candidates 5 s after the rule, so on
  `okx-shared` the rule's bid reserves first and the learned target then contends
  for the 0.01 limit.
- **The QR's price grid was wrong for ETH.** The authored grid used a 0.1 tick for
  every OKX instrument, but OKX ETH quotes in 0.01, so an ETH holdout holding a
  position could not value it. The grid is now per venue and asset:
  - OKX: BTC 0.1, ETH 0.01;
  - Bitfinex: BTC 1, ETH 0.1.

**Addendum CI-1 (approved 2026-10-05): candidates pin the runtime they deploy on.**
- **Found by the first J6 run.** The services release's install check refused every
  QR candidate. The loader required a bundle's `code_sha256` (every installed
  platform module) and `environment_sha256` (every installed distribution) to equal
  the running environment's.
  - The QR packages in the full research environment.
  - The signed paper-services release installs only its three wheels, with its own
    lock.
  - So no packaged candidate could ever load there. Packaging and loading had only
    been tested in one environment.
- **The change.**
  - `CandidateDefinition` gains `runtime_code_sha256` and
    `runtime_environment_sha256`, computed by `runtime.CandidateRuntime`, and the
    loader requires those.
  - The code identity hashes exactly the platform files the three operating wheels
    ship, by name and bytes. They are listed in `runtime/candidate_runtime.json`,
    which is shipped.
  - The environment identity hashes the interpreter, the platform and the versions
    of the paper-services lock's third-party distributions.
  - `code_sha256` and `environment_sha256` keep one meaning only: the link to the
    candidate's study, checked at packaging.
  - An engineering test keeps the JSON equal to the wheels' include tables and the
    lock, and those versions equal to the root lock's.
- **Effect.** Bundles made earlier must be repackaged; recorded rehearsals stay valid
  at their own commits.

**M3e defect: the signed supervisor could not import.**
- **Also found by that run.** M3e's runtime metrics import report contracts from
  `research.studies`, which no operating wheel ships. In the installed paper-services
  environment `applications.execute.services` failed to import, so the supervisor
  could not start.
- **Why no check caught it.**
  - Unit and integration tests run in the full environment.
  - The wheel smoke test installs the full wheel.
  - The shipped-imports check followed only `runtime.*` imports.
- **The fixes.**
  - The report contracts a candidate's metric and chart components use
    (`ReportObservation`, `LedgerPoint`, `FoldSummary`, `ReportContext`,
    `MetricValue`, `ChartSpec` and the metric and chart protocols) move into a new
    shipped package, `research.reports`. `research.studies` still exposes them.
  - The model's `EvaluationRecord` moves from `research.studies` into
    `research.models`, which ships, because `research.models.linear` imported it at
    load.
  - A new engineering test requires every module-level platform import of shipped
    code to resolve to a shipped file. Names are compared exactly, because macOS
    paths are case-insensitive.

**Build defect: external extension sources were signed out of order.**
- A paper-services release built with an external extension listed the extension's
  source files after the repository's in `source.json`. Verification reads them in
  sorted order, where `external/` falls before `packages/`, so every such release
  failed verification.
- The builder now sorts the complete source list (`ReleaseBuilder.release_sources`),
  with a regression test.

**Addendum F-1 (approved 2026-10-05): installed runs share their target.**
- **Found by the second J6 run.** The launcher's `run` held the target's exclusive
  installation fence for the whole child process. This note's layout runs the
  publisher, the supervisor and `deployment-control` through one services target at
  once, so whichever started first held the fence. The supervisor died one second
  after the publisher started with a bare `[Errno 35]`, and every control failed the
  same way.
- **The change.**
  - `run` takes the fence shared; `install` keeps it exclusive. Any number of runs
    may share a target, and an installation still cannot select a release under a
    running process, or start while one runs. This holds for every target, account
    targets included.
  - Single-instance ownership belongs to each application, which already fences
    itself: the account service's journal lock, the journal's writer lock, and the
    supervisor's endpoint and `supervisor.lock` fences.
  - The publisher was the one process without a fence of its own. It now holds an
    exclusive `publisher.lock` in its serving root, so two publishers cannot feed
    one store.
- **Tests.** Two runs share a target; a run and an installation still refuse each
  other in both orders; a second publisher on one serving root is refused.
- **The driver hung after the failure.** A failed J6 step left its background
  processes serving until their own lives ended, and the driver waited on them. A
  failed phase now stops every background process it started before it reports.

**Addendum SW-1 (approved 2026-10-05): a persistent Feast serving worker.**
- **Found by the third J6 run.** P-A ran end to end, but the OKX sources were faulted
  `heartbeat_stalled` about a minute in, and Bitfinex BTC soon after.
  - Each learned decision read its served features through `FeastServingBridge`,
    whose worker ran a fresh process of the separately locked Feast environment per
    request. Importing Feast alone takes 2.1 s on the development machine.
  - The supervisor does not drain a source's pipe while that source has an
    observation in flight. A source's capture child blocks on a full pipe by design,
    so its heartbeat stops, and the supervisor faults a source whose heartbeat is
    older than 2 s. OKX's 400-level books fill the pipe within that time.
  - Integration tests used small authored books, so no pipe filled.
- **The change.**
  - The worker program (`alpha-explore feast-worker` and `feast-serving-worker`)
    answers newline-delimited requests until its input ends. A one-shot caller sends
    one request and closes its input, as before. A failed request still ends the
    worker non-zero with its reason on stderr.
  - `research.features.FeastWorkerSession` keeps one worker process alive behind the
    existing `FeastWorker` protocol. Requests are serialized, and each reply is bounded
    by the configured timeout and byte budget. A worker that dies, times out or
    fails raises `FeatureAccessError` with its stderr, and the next request starts a
    fresh worker.
  - The supervisor and the publisher each own one session and close it when they end.
    The worker environment, its isolation and the configuration are unchanged.
  - Each starts its session's worker as it starts (`FeastWorkerSession.start`), and the
    serving worker loads the Feast SDK as it starts. Otherwise the first served reads
    still paid the two-second start at one instant: the fifth J6 run's four learned
    reads queued behind it, and every source stalled. Warm, a read takes about 3 ms
    and a materialization about 0.2 s on the development machine.
- **Tests.** The session reuses one process across requests, restarts after a
  failure and kills a worker that exceeds its timeout. The worker program answers
  several requests on one input.

**Serving defect: a stream not yet published faulted its accounts.**
- **Found by the fourth J6 run.** The paper services store starts empty, and the
  publisher registers a definition and activates its version only at its first
  publication. A learned decision before then raised "feature-store definition is not
  registered", which `ServedFeatures` did not turn into a pause, so the supervisor
  faulted every account.
  - A registered definition with no version active yet would have read as
    `feature-version-changed`.
- **The fix.**
  - `VersionedFeatureStore.published_version` returns `None` before a definition's
    first publication, and still refuses differing definition bytes.
  - `ServedFeatures` names that state `feature-pending`, as the runtime guide already
    defines it ("no snapshot at the cutoff yet"), so the instant waits and is retried.
  - A unit test serves before registration and before activation.

**Addendum GR-1 (approved 2026-10-05): the J6 grant follows what the plan deploys.**
- **Found by the sixth J6 run.** Each paper decision replaces its instance's working
  orders (AB-1), so an active instance places an order, or two for a quote, every 15 s.
  The plan granted 80 orders an hour and a lifetime buy quantity of 1 per instrument.
  Both ETH accounts reached the quantity within minutes (ten 0.1 bids) and were
  faulted. A 30-minute P-A would also pass 80 orders on every account.
- **The change.** The plan derives each account's grant:
  - `maximum_orders` is the account's instances × 2 legs × decisions in the grant's
    hour (3600 s / 15 s cadence); `okx-shared` with three instances gets 1,440.
  - Each instrument's quantity is `maximum_orders` × that instrument's order size, so
    the order count is the binding cap.
  - Exposure stays bounded by the position limits (BTC 0.01, ETH 0.5), the budgets
    and the 1,000 maximum order notional.

**Addendum EX-1 (approved 2026-10-05): extensions import only what the release ships.**
- **Also found by that run.** Every candidate dashboard was missing. The QR's metric
  component imported its report contracts from `research.studies`, as the QR API map
  directed. The paper-services release does not ship `research.studies`, so every live
  metric evaluation raised and no page was rendered. The failure was counted but
  never shown.
  - The release builder already audits external extension imports, but against the
    full build environment, where `research.studies` exists. M3e's import closure test
    covers only platform code at module level.
- **The change.**
  - The QR API map and quickstart name `research.reports` for the contracts components
    use (`FoldSummary`, `ReportContext`, `MetricValue`, `ChartSpec`,
    `ReportObservation`, and the metric and chart protocols). `research.studies` no
    longer re-exports them; studies import them from `research.reports` too.
  - `ImportAudit` takes the release's shipped files and reports an `unshipped-import`
    for any platform module the release does not ship, including imports inside
    functions. The builder audits every external extension against the files listed in
    `runtime/candidate_runtime.json`, so a paper-services build refuses such an
    extension with that finding.
  - The QR workspace's extension imports its contracts from `research.reports`, as a QR
    following the corrected guide would.
- **Tests.** The audit reports an unshipped import at module and function level and
  accepts a shipped one; the builder's extension read refuses an extension that
  imports `research.studies`.

**Addendum MS-1 (approved 2026-10-05): each candidate's telemetry has its own scope.**
- **Found by the seventh J6 run.** Candidate dashboards were still missing.
  - M3e's exporter scoped every candidate's facts to its account (`account:<id>`).
    J6 deploys two or three candidates per account, all exporting the QR's
    `mr17.net-per-turnover`. In one sample they produced events with the same key and
    different values, the store refused the whole append ("telemetry revision reused
    with different bytes"), and nothing was exported or rendered.
  - Even without the collision, an account page keeps one "last value" series per
    name, so it would have merged different candidates. M3e's tests deployed one
    candidate per account.
- **The change.**
  - Candidate telemetry scopes each instance's facts as
    `account:<id>:strategy:<instance>`, the convention paper monitoring already uses
    for per-instance facts. Metric names stay the QR's contract names.
  - Each account renders its account page and one page set per candidate scope. A
    candidate's page carries its metrics and their warning bands. Page directories are
    named by scope, so several pages at one instant do not collide.
- **Tests.** Two instances of one candidate on one account both export their metric
  and render their own pages without a telemetry failure, and the single-candidate
  test reads its facts and its alert from the candidate's scope.

**Account command defect: an inspection dropped the saved batch's outcome.**
- **Found by the eighth J6 run**, the first whose dashboards, alerts and delivery-log
  replay all passed. The race check read every `okx-shared` batch's outcome through the
  installed account command and got none.
  - The journal's `saved_batch` projection carries the outcome (`portfolio`), but the
  account application replaced the response's `portfolio` with the command's own
  commit, which an inspection does not have. The earlier fix had been tested only
  against the journal.
- **The fix.** A command's own commit stays its outcome; otherwise the response keeps
  what its projection read. The saved-batch test now reads each outcome both from the
  journal and through `AccountExecutionApplication`.
- **The race check.** Replayed against that run's journal, the race appears: the rule's
  bids were admitted (`reserved`), and the learned target was refused at the 0.01 limit
  (`holding_limit`). The check now reads groups in order until it has seen both,
  instead of only the first 24. It counts only a `holding_limit` refusal, so an
  operator stop (`instance_stopped`) is not taken for the race.

**Addendum RC-1 (approved 2026-10-05): a reference contender makes the race certain.**
- **Found by the first complete J6 run** (all of P-A, P-B and S ran). The race passed in
  one run and not in the next. It needs both QR candidates to want a long position at
  once: in rehearsal 99 the learned target was refused at the limit while the rule
  held 0.006; in rehearsal 101 the learned candidate stayed flat, so each of the rule's
  refusals was its own limit and no race happened.
- **The change.**
  - On `okx-shared` the plan adds `reference-okx-btc`, the platform's `fixed_clip`
    reference formula (opening clip marketable through the modeled adverse cost) at
    the BTC size, on the 15 s grid starting 2.5 s after the rule. It holds 0.006 from its
    first decision, so a long bid from either QR candidate meets the 0.01 limit because
    of the reference's holding. The QR candidates are unchanged; the grant and budgets
    count the fourth instance.
  - The race check is symmetric and attributed: it passes when one contender is
    refused for `holding_limit` while another contender holds a non-zero position at
    that instant, from the account's attributed fills. A refusal while every other
    contender is flat is a candidate's own limit, not the race.

**Supervisor defect: an account's report was marked twice per instrument.**
- **Also found by that run.** In P-B the isolated accounts never retained a report, so
  their dashboards were missing. A trades child shares its book child's observers, and
  the supervisor collected each account's marks from both children, so every report
  carried two marks for one instrument and an account holding a position was refused.
- **The fix.** `PaperServices.latest_markets` reads book children only, so each source
  marks its instrument once; the trades-child test requires one mark.

**Addendum KC-1 (approved 2026-10-05): accounts state their knowledge clock.**
- **Also found by that run.** J6's reconciler, like MR15's, stamped each observation
  at the account's last accepted market from the supervisor status.
  - An account matches only an observation at or after its knowledge clock. That
    clock includes every order's decision instant, which is later than the market
    the decision saw.
  - So every account holding a working order mismatched and was faulted
    (`bitfinex-isolated` in P-A). MR15's sustained run held no working orders at its
    reconciliations, so it never met this.
- **The change.**
  - A new account projection, `reconciliation`, answers one account's view, its open
    orders and its knowledge clock from one consistent snapshot. The clock is added to
    the account response as `AccountExecutionResult.known_at`, and it is the clock
    reconciliation compares against, computed by the same admission code.
  - An observation stamped at `known_at` is always safe: the account already refuses
    any market earlier than its own clock, so the stamp cannot refuse a market in
    flight.
  - J6's reconciler and restart observation read that projection in one call. The
    two separate reads they made before could also tear against a live account.
  - They stamp at the later of `known_at` and the account's last accepted market from
    the supervisor status. Both are safe: markets reach an account in order. The
    knowledge clock covers working decisions, and the market clock keeps a quiet
    account's reconciled state fresh against its state-age limit, which `known_at`
    alone would not advance.
  - MR15's capacity reconciler (`AccountReconciler`) moves to the same projection and
    stamp, at the owner's request. It no longer skips a round before the first
    market. MR15's recorded evidence stays valid at its own commit.
- **Tests.** The projection's clock covers a working order's decision instant, and an
  observation stamped at it reconciles while the order is open. One stamped at the
  last market does not. The capacity reconciler stamps at `known_at` without a market
  and at a later accepted market when there is one.

## M3f-2 result (2026-10-05)

The journey's J6 is implemented and passes, with every addendum above approved and
built. One commit.

**The passing development run (uncounted, not evidence).** `rehearsal-103` ran the
driver's own J6 under a development harness. The harness takes the J1–J5 outputs from
a dry run of the same tree and shortens the phases to 300, 180 and 180 s. All 81 J6
criteria passed:
- Signed builds, verification and installation of the services and four account
  releases; claims under one-hour grants; the research grant refused unchanged.
- **P-A.** Selective stop and restart of `learned-okx-btc`; the injected
  `okx-isolated` owner death with a request in flight. Every reconciliation round
  matched. Reports were retained, and the QR's custom metric reached every account's
  dashboards. Alerts reached the local receiver, and every delivery log replayed
  exactly. In the shared-budget race a contender was refused at the 0.01 limit while
  another held its position.
- **P-B.** All four accounts were settled, reconciled and reclaimed under fresh owners,
  relaunched, and ended by a shutdown control, with the same checks passing.
- **S.** Both shadow accounts served the BTC candidates with zero fills, and their
  checks passed.

**What the runs found.** Eleven development runs (90–103) each stopped at a different
defect, all recorded above:
- Fixes in shipped code:
  - F-1: installed runs share their target.
  - SW-1: a persistent, pre-started Feast serving worker.
  - KC-1: accounts state their knowledge clock.
  - A stream not yet published is pending, not a fault.
  - EX-1: extensions import only what the release ships.
  - MS-1: each candidate's telemetry has its own scope.
  - An inspection keeps its saved batch's outcome.
  - A report is marked once per instrument.
- Fixes in the journey: GR-1 sizes the grant from the plan, RC-1 adds the reference
  contender, the recovery observes a fresh quote, and deployments are authored from
  the installed release's deployment check. The last is needed because a reference
  candidate's identity names the code and environment that load it.
- From run 100 the harness recorded every criterion and continued, so one run showed
  all of a phase's remaining failures.

**Also in this commit.**
- The Linux CI failure on PR #105: the telemetry test bound its alert socket under
  `/private/tmp`, which Linux lacks. It now uses the repository's socket root.
- The QR workspace's extension imports its report contracts from `research.reports`.

**Not done here.** M3f-3 (J7), the next counted-style rehearsal, and M4–M6.

**Validation (as run, 2026-10-05).**

| Lane | Result |
| --- | --- |
| `make check` | Passed: 2,568 passed, 4 skipped, 25 deselected; wheel smoke passed |
| Integration (`-m integration`, Feast worker selected) | Passed: 40 passed |
| Performance (`-m performance`) | Passed: 25 passed |
| Linux strict mypy | Passed: no issues in 712 source files |

## M3f-3 design note: the journey's J7 (approved 2026-10-05)

The owner approved this note, with R-2 and E-3, on 2026-10-05. It fixes how the
driver runs J7 after J6. Its two choices were judged on scalability and
maintainability, with no backward compatibility kept. M3f-3 has two parts, which land
in one commit at the milestone (owner, 2026-10-05):
- **M3f-3a:** a durable receipt clock, with [its own note](#m3f-3a-design-note-a-durable-receipt-clock-approved-2026-10-05);
- **M3f-3b:** the driver's J7.

Both are implemented; see the [M3f-3a](#m3f-3a-result-2026-10-05) and
[M3f-3b](#m3f-3b-result-2026-10-06) results.

**What reading the code shows.**
- **The declared J7 commands cannot run as written.**
  - `alpha-governance-artifacts install` takes no `--state`. `--state` is a `build`
    option that signs a quiesced directory into a release as its initial state.
  - `WorkspaceBackup.create` refuses a backup inside its source root, so
    `$A/j7/backup` cannot hold a backup of `$A`'s components.
  - Component names must be lower case, so J6's `service-P-A` and `service-P-B`
    cannot be selected.
- **A restored account journal can never be activated.**
  - `AccountWorkspace.restore` marks the staged journal
    `paper_restore_quarantine` before publication, and nothing clears it.
    `install_paper`, `claim_paper`, `restart_paper`, `reduce_paper` and every owner
    check refuse it with `paper_restore_requires_current_retained_journal`.
  - This is the accepted MR13 contract: the roadmap says "historical snapshots
    cannot reactivate managed execution", and the runbook says managed paper resumes
    only from the latest retained journal. A copy cannot prove that no later fills
    happened.
  - So R-1 (install a fresh target from the restored journal, then claim) would be
    refused at the claim. The M3 note said a rehearsal would find this; reading the
    code finds it now.
- **J7 also inherited two criteria from earlier notes.**
  - S-1: "J7 checks that the study's simulated entry delay is at least the observed
    decision delay."
  - AB-1: paper can refuse a budget-bound decision that research admits; "J7 declares
    and checks that difference."
- **The entry-delay criterion would fail.** The QR's studies model a 1 ms entry
  delay. Measured on `rehearsal-103`'s J6 delivery logs (`coordinated_at − at`):

  | Feed | Rule (source-fed) p50 / max | Learned (served) p50 / p90 / max | Learned above 1 s |
  | --- | --- | --- | --- |
  | OKX BTC | 0.0 / 0.0 ms | 0.84 / 2.9 / 4.7 s | 36% |
  | OKX ETH | 0.0 / 0.0 ms | 0.96 / 4.9 / 15.0 s | 48% |
  | Bitfinex BTC | 0.0 / 0.0 ms | 1.26 / 8.7 / 13.6 s | 74% |
  | Bitfinex ETH | 0.0 / 0.0 ms | 1.78 / 9.5 / 9.5 s | 56% |

  Rule candidates decide on the crossing book well inside 1 ms. The learned delay has
  two causes, both waits on a quiet feed:
  - the publisher publishes t only after every feed, including the sparse trades
    feed, has a durable record later than t;
  - the supervisor retries a pending served instant only on the next book delivery
    after the snapshot appears.

  S-1 bounds the total wait at one cadence (15 s), and the logs reach that bound. The
  delay grows with every added feed and with quieter markets.

**Choices for the owner.**

*R — what "restore and resume" means for accounts.*
- **R-2 (recommended): one recovery path, the accepted boundary.** This replaces R-1.
  No platform change.
  - Backup and restore cover data, features, artifacts and account state. The
    restored copies are verified equal, and they are opened from the restored root
    alone.
  - Restored account copies are verified equal to their backup and to the retained
    journals: views, orders, fills, stops and candidate checkpoints. J7 also checks
    that they are quarantined.
  - Resumption follows the runbook from the latest retained journals: independent
    reconciliation, fresh grants and claims, and the supervisor and publisher
    relaunched. No step outside the runbook is allowed.
  - The quarantine is a safety rule, not compatibility: a copy cannot prove that no
    later fills happened. Keeping one resumption path is the more maintainable design.
  - The J7 row's criteria become: restored identities equal, restored account copies
    quarantined, resumption from retained state without manual repair, and rollback
    keeps current facts.
- **R-3: account succession.** The backup durably retires its source journal, and a
  restored copy carrying that retirement may be claimed once.
  - It adds a second resumption path, new journal state, and a services release that
    re-points the store paths, for a case MR17 does not have.
  - What it would really provide is moving an account to another host. That deserves
    its own design when multi-host operation is in scope. Not recommended.

*E — the inherited entry-delay criterion.*
- **E-3 (recommended): fix the served path's latency at its source, then keep S-1's
  strict criterion.**
  - Each capture durably records an idle receipt clock (M3f-3a). A quiet feed then
    passes t within the clock interval. The publisher publishes as soon as it has
    the inputs, and the supervisor retries the pending instant on the clock delivery.
    Readiness keeps exactly its current rule.
  - The served delay becomes about the clock interval plus one warm materialization,
    independent of how many feeds there are or how sparse they are.
  - The QR's learned studies model a declared served-path delay (1 s, to be confirmed
    from the M3f-3a development run), so J3–J5 rerun.
  - J7 then requires every observed decision delay to be at most the study's modelled
    delay, per candidate, over every J6 and J7 paper phase.
  - It changes shipped code, so it lands before 2b, which qualifies it.
- **E-2: a bounded, reported delay.** Learned delays are only bounded by one cadence
  and reported. No code change, but the gap grows with scale and is only documented.
- **E-1: the QR models today's measured delay.** This builds the quiet-feed wait into
  research, and a delay near one cadence collides with the 15 s order lifetime.

**How J7 runs** (as recommended).
1. **Quiesce.** J7 starts after J6's shadow phase, with no supervisor, publisher or
   owner running; the driver checks this. Each paper account must be explicitly
   stopped: J7 reads its phase through the installed `account` command and stops one
   that is not.
2. **Back up**, into one backup set at
   `~/AlphaResearchEvidence.noindex/mr17/<attempt>.j7-backup/` (outside `$A`, because
   a backup cannot sit inside its source), linked from `$A/j7/backup`.
   - `research/`: the QR's `j7_backup.py` runs `WorkspaceBackup.create($A, …,
     components=("j2", "j3", "j4", "j5"))`. This covers snapshots and raw captures,
     attempts and their artifacts, the QR feature store with its Feast generations,
     and the bundles.
   - `paper/`: `journey_paper.py backup` runs `WorkspaceBackup.create($A/j6/paper, …,
     components=("candidates", "features", "service-p-a", "service-p-b"))`. J6's
     service roots are renamed to lower case for this.
   - `accounts/<id>/`: each paper account's installed `account` command with a
     `backup` request (runbook step 5).
   - `backup-set.json` lists every manifest digest.
   - Not covered, as the runtime guide states: lakeFS and ClearML server state (J2 and
     J3 already reopen from them), the signed release registry (immutable, and verified
     again at installation), and the shadow accounts (their phase is over).
3. **Restore**, into absent roots under `$A/j7/restored/`.
   - Research through the QR's `j7_restore.py`, paper through `journey_paper.py
     restore`, and each account through its installed `account` command with a
     `restore` request and the retained manifest digest.
   - While the QR checks the restored research root, the driver moves `$A/j2`–`$A/j5`
     aside and moves them back afterwards. A hidden absolute path into the source then
     fails the check instead of passing it.
   - Criteria:
     - every restored manifest equals its backup's;
     - the QR's studies reopen with equal identities and reports;
     - the restored QR store and the restored paper store serve equal values at the
       same cutoffs;
     - each restored account receipt equals its backup receipt, its views, orders,
       fills, stops and checkpoints equal the retained journal's, and it is
       quarantined.
4. **Resume (phase R, 5 min).** From the retained journals, on services v1:
   independent reconciliation, fresh one-hour grants and claims as in P-B, then the
   publisher and supervisor. Criteria: J6's per-phase checks (every reconciliation
   round matches, exact delivery-log replay, dashboards, no duplicate effect), and
   every command is a runbook step that exits 0.
5. **Upgrade (phase U, 5 min).** Services v2 is the same request with configuration
   revision 2, adding `rule-okx-btc-late` to `active`. It is built, verified and
   installed over the services target, the accounts reclaim, and the services run.
   - Before U ends, a `stop_instance` control stops the late instance. This cancels
     its working orders and keeps its position, so v1 never inherits unmanaged orders.
   - Criteria: the installation receipt names v1 as previous; the late instance
     decides and trades; J6's per-phase checks.
6. **Roll back (phase B, 5 min).** `rollback --release <services v1>`, then reclaim
   and run.
   - Before the rollback, J7 retains each journal's orders, fills, controls, ledger
     and checkpoints.
   - Criteria:
     - the receipt selects v1 with v2 as previous, and the deployment check shows
       revision 1;
     - every retained fact is still present and unchanged after phase B;
     - the late instance keeps its position and places no order;
     - the paper store keeps every snapshot published under v2;
     - J6's per-phase checks.
7. **Inherited criteria.**
   - **Entry delay.** Per candidate, every decision delay in J6 and J7 is at most the
     study's modelled entry delay. The distributions are retained.
   - **Budget-bound refusals.** Every paper refusal and dropped leg in J6 and J7
     carries a reason from the declared paper-only set (`holding_limit`, instance and
     firm budget, cash, inventory, order notional). Any other reason fails, and the
     counts per candidate are retained.

**Where the code goes (M3f-3b).**
- The driver's `Operations` step, with J7 added to `IMPLEMENTED` and the J7 phase
  lengths in the declaration (5/5/5 minutes).
- `journey_paper.py` gains `backup`, `restore`, `facts` (journal facts before and
  after) and `delays`. It reuses J6's reclaim, owners and phase checks.
- In the QR workspace: `j7_backup.py` and `j7_restore.py`, written from the runtime
  guide, and the learned studies' modelled entry delay. If guide coverage finds a gap,
  the QR API map gains a backup-and-restore entry.
- The J7 section of the declaration and the J7 row are corrected to the chosen
  options. No further shipped code changes are expected; any that a run finds come
  back as addenda.

**Iteration.** M3f-3a changes shipped code, so J3–J5 rerun once after it. After that,
the development harness runs J6 with 180/90/90 s phases, then J7 with 120 s phases, in
continue-past-failures mode, reusing the packaged candidates.

**Addendum RF-1 (decided 2026-10-05): one read of every decision outcome.** The
owner delegated this choice on 2026-10-05, on scalability and maintainability, with no
backward compatibility kept.
- **Found while implementing.** The inherited budget-refusal criterion needs every paper
  decision's outcome and dropped legs. Both are retained: each decision's `StepCommit`,
  with its status, reason and `dropped` legs, is saved with the decision, including a
  rejected batch's decisions. But the `account` command reads one saved batch per call
  (about 1.5 s through the signed launcher), and it has no read for dropped legs at all.
  At counted lengths that would be about 3,500 calls, and still incomplete.
- **The change.** `inspect` gains a read-only `decisions` projection. It returns one
  compact `DecisionOutcome` per saved decision (account, instance, decision identity
  and time, status, reason and dropped legs) from one snapshot, in commit order. J7
  makes one signed call per account.
- **Rejected options.** Per-batch launcher reads (slow, and blind to dropped legs);
  opening the journals in the research environment (it bypasses the signed launcher
  the journey otherwise keeps).
- **Release.** An execution-owner read; stage 2b qualifies the execution release.

**Addendum P-1 (decided 2026-10-05): J3's studies run in a bounded pool.** The owner
proposed this and delegated the design on 2026-10-05, on the same criteria.
- **Why.** J3 runs twelve independent studies and a grid. On `rehearsal-105`'s
  30-minute window they took 52 minutes in sequence, about 4–6 minutes each. A counted
  six-hour window makes each study several times longer.
- **What blocked it.** `AttemptStore` admits one writer, held for a whole study's
  session, so concurrent studies on one store fail. One store per study would break
  the shared family and holdout history that refuses a second holdout.
- **The change.**
  - `AttemptStore` serializes each mutation instead of each session. A session holds a
    shared session lock; every mutation takes the exclusive writer lock only while it
    rechecks persisted state and appends, as it already does. A re-entrant
    `transaction()` holds the writer lock across a compound check-and-write, such as
    `evaluate_study`'s idempotency-key check and start.
  - Holdout consumption, family declarations and artifact deduplication stay atomic,
    because each is one mutation under the writer lock.
  - `WorkspaceBackup` takes the session lock exclusively, so it still refuses while any
    study session is open.
  - The driver runs J3's studies and grid through a bounded pool. The declaration's
    `research_workers` (default 4, at most 16) sizes it.
- **Not changed.** A study's records, identities and holdout rules.

**Addendum RP-1 (found 2026-10-05): a replaced order ends with its parent.** J7's
refusal criterion, dry-run on `rehearsal-107`, found a defect in widened AB-1.
- **What happened.**
  - When a decision replaces its instance's working orders, the account requests
    cancellation of the physical parent. The attached child was left in `intent`, with
    no cancel request.
  - When the parent's cancel completed, only a stopped instance's children were
    cancelled with it. The replaced child therefore became an unassigned residual
    awaiting reissue.
  - Every later batch on that account then needed a reconciliation newer than the
    parent's outcome. On each isolated account the learned ETH candidate was refused
    with `reissue_requires_current_reconciliation` for most of its decisions (15–16 of
    about 20 in `rehearsal-107`; 18–30 in `rehearsal-109`), so it barely traded.
  - Once a reconciliation was current, the replaced order would have been reissued,
    which AB-1 forbids.
- **The fix.**
  - Replacement also records a cancel request on the instance's attached children.
  - When a parent ends, any child with a cancel request ends with it, as a stopped
    instance's children already did.
  - A replaced order is therefore never reissued, and no other instance waits on it.
- **Release.** The changed execution modules are candidate-runtime modules, so packaged
  candidates pin the new runtime code; J3–J5 rerun.
- **A second form, found by `rehearsal-111`.** The learned target candidates send
  immediate-or-cancel orders. An unfilled IOC parent ends `cancelled`, and its child
  again became a residual. One was reissued to a second parent, and later batches
  waited for reconciliation (`rule-bitfinex-eth`: 11 refusals).
- **A third form, found by `rehearsal-113`.** Paper matching rejected a crossing
  post-only parent, which also ended without a cancel request. Its child waited until
  the rule's next decision, and one learned decision in between was refused.
- **The rule, stated once.** Only a parent cancelled on request leaves its other
  children's remainder to reissue: for example, a shared parent cancelled for another
  strategy's stop (the MR09 portfolio consumer). A child ends with its parent when:
  - its instance stopped;
  - its own cancel was requested as its instance replaced its orders;
  - or the parent ended on its own terms, through an immediate order's expiry or a
    post-only rejection. Reissuing it would repeat an order that has already ended.

**Addendum ST-1 (found 2026-10-05): a stale observation is refused, not a break.**
`rehearsal-114` found this.
- **What happened.** The journey's reconciler reads an account's reconciliation
  projection, then sends the observation back. On bitfinex-isolated a round read at
  23:12:59.7 reached the account just after the rule's 23:13:00 decision had placed
  orders. The observation now preceded the account's knowledge clock, so it did not
  match.
- **Why it mattered.** A mismatch records `account_break` and faults the account. J7
  then could not reclaim it ("paper account is faulted"). A reconciliation racing an
  admission is no evidence that the account diverged.
- **The change.**
  - An observation stamped before the account's knowledge clock, or before its last
    reconciliation, is refused with `observation_precedes_account_state`. It is
    unrecorded, and the account is not faulted. This mirrors the existing
    `decision_precedes_account_state` refusal.
  - A current observation that differs is still a break.
  - The journey's reconciler observes again, up to three times.
  - The same race reaches P-A's selective restart. Its control carries an
    observation made about a second earlier. On `rehearsal-115` a decision landed in
    between, the restart was refused as stale, and the instance stayed stopped. P-B's
    supervisor then refused to start ("selected instance requires explicit reconciled
    restart"). The driver now re-observes and resends the restart, up to three times.
  - `deployment-control` exits 0 even when the supervisor refuses. So the driver also
    requires every control to answer `ok`, and a refused control fails its criterion.
- **Release.** An execution-owner change in candidate-runtime modules; J3–J5 rerun.

**J7 criterion decisions (decided 2026-10-05, owner delegation).** The development
runs showed three criteria stricter than the behaviour they test. Each is now decided
on the same criteria as RF-1 and P-1.
- **Self-trade protection is a declared paper-only reason.** The account refuses an
  order that would trade against one of its own working orders: another instance's on
  the same instrument (a learned IOC buy against the rule's resting sell), or a leg a
  replacement is replacing, which stays working until its cancel completes (AB-1).
  Research models each candidate alone, with instant replacement. `self_trade_conflict`
  joins the declared set, like the budgets.
- **The race counts a reserved order.** On `rehearsal-111` the rule's first bid rested
  unfilled through P-A. It reserved 0.006 BTC of the shared 0.01 limit, and the
  reference and the learned candidate were refused at the limit: the race, admitted
  once and refused once. The check required the other contender to hold fills. It
  now also accepts a contender whose latest admitted decision reserved a working
  order. Under AB-1 that rule could not replace its resting bid either (0.006 + 0.006
  exceeds the limit until the cancel completes), which is the declared paper-only
  difference.
- **A decision overtaken by an operator control is attributed, not unexplained.**
  - On `rehearsal-116`, P-A's restart control ran from 00:35:16.36 to 00:35:17.67 and
    stamped the account clock. The reference's decision for instant 00:35:17.5 then
    arrived after it and was refused with `decision_precedes_account_state`.
  - That refusal is correct and safe: the decision was made on state from before the
    operator's change. Declaring the reason wholesale could hide real lag, though.
  - So a stale-decision refusal is accepted only when the decision's instant falls
    within a supervisor control command's run. The driver retains those windows from
    its own command records (`j7/controls.json`).
- **The late instance must decide; its fills are retained.** It runs on `okx-shared`,
  where the race exhausts the shared limit, so whether it trades within U depends on
  the market. Activation is shown by its decisions reaching the account. Its outcomes
  fall under the refusal criterion, and its fill count is retained.

## M3f-3a design note: a durable receipt clock (approved 2026-10-05)

The owner approved this note on 2026-10-05.

**Problem.** Live inputs advance only on received messages. A quiet feed therefore
holds back everything that waits for it to pass an instant:
- the publisher, which publishes t only once every feed has a durable record later
  than t (`FeaturePublication.advance`);
- the supervisor's observers, which retry a pending served instant, or cross a
  source-fed instant, only on the next delivery.

The wait is the gap to the quietest feed's next message, so it grows with every feed
added and with quieter markets. J6 measured it at up to one cadence (the table above).

**The change.**
1. **A `clock` capture record.** `CaptureRecord.kind` gains `clock`: no bytes, no
   reason, and `received_ns` stamped like any receipt.
   - It states that the feed received nothing between the previous record and that
     instant. It carries no market content, and it says nothing about venue
     liveness.
   - It replaces nothing: frames, gaps and session records keep their meaning.
2. **Written by the durable writer when the feed is idle.**
   - The capture runner's writer appends a `clock` record when its queue has been
     empty for the capture's `clock_interval_ms`. A busy feed therefore writes none.
   - The interval is a new required `CaptureConfig` field, with no default in the
     schema. The journey and the guides use 250 ms.
   - The writer stamps the clock synchronously on the event loop, and only with an
     empty queue. The receiver and the snapshot task suspend between stamping and
     enqueuing only while the queue is full, which cannot coincide with an empty
     queue. So every receipt stamped earlier is already queued, and no record stamped
     before a clock can arrive after it.
3. **Receipts become monotonic, and the writer enforces it.** The writer refuses a
   record whose `received_ns` is before the last appended record's (a wall-clock step
   back). It ends the session with the visible gap `receipt_clock_regressed`. Clock
   records rely on this, and every receipt-ordered reader gains a checked invariant
   it now assumes silently.
4. **Readers.**
   - Book and trade reconstruction (`CaptureReplay`, the trades tape) apply a clock
     as a no-op with outcome `clock`. It never changes book state, market age or
     quality counts.
   - Freshness validation does not count a clock as market data, so a feed with only
     clocks still ages its book.
   - Segment message counts, the rollover's original-message rule and the journal's
     reserve ignore clocks.
   - Dataset publication and the saved readers skip clocks. Published partitions and
     research values are unchanged.
5. **Consumers.**
   - `FollowedFeed` accepts a clock like any durable record, so the publisher's
     existing readiness rule passes a quiet feed within one interval.
   - The supervisor's decision timing changes; see addendum CK-1.
   - Delivery logs retain clock deliveries, and replay accepts them.
6. **Release and records.**
   - This changes the capture record and `CaptureConfig` schemas in place, and the
     collector, paper-services and research releases. Stage 2b qualifies all of them.
   - Existing captures and evidence stay valid at their own commits. No reader for
     the old `CaptureConfig` is kept.

**Addendum CK-1 (approved 2026-10-05): decisions run on time, matching on markets.**
- **Found while implementing.** The note said the supervisor would retry a pending
  served instant on a clock "with no rule change". It cannot. `_market` returns a
  market only for a priced book (`snapshot` or `update`), and an observer crosses,
  opens and decides instants only when a delivery carries one. Heartbeats and
  controls already advance nothing.
- **Why it matters.** Measured on `rehearsal-103`:
  - trades gaps reach 16 s (the publisher's wait, which clocks fix);
  - priced-book gaps are p99 0.3–0.5 s, with a maximum of 3.1 s on Bitfinex ETH.

  So after publication, a served decision still waits for its own book's next priced
  update, and a source-fed decision waits the same way. That wait depends on market
  activity, so a sparse instrument added later would decide late, and research's
  entry delay could not bound it.
- **The change: time and market are separate axes.**
  - **Time.** Any delivery advances the grid if its source is fresh: a priced book,
    a heartbeat, a control or a clock. Fresh means the source's latest eligible
    market (`_pending`) is current at the delivery. Such a delivery crosses instants,
    opens them (an eligible market at or before the instant still required), and
    decides every ready instant, quoted at that retained market as today.
    Coordination keeps S-1's bounds.
  - **Market.** Only a priced book matches orders and replaces the retained market.
    A decision made on a non-market delivery has `matched = false`, and its orders
    match at the next priced book, as research's orders do after their entry delay.
  - **Unchanged.** Source freshness and invalidation stay as they are. A
    non-market delivery that finds the book stale is checked by
    `_source_invalidated`, exactly as heartbeats are now.
- **Readers.** `LiveBookDecisionSource` and `BookRegistry` carry the previous
  boundary unchanged across a clock: same observation, same market. The trade source
  does the same.
- **Delivery log.** `matched` keeps its meaning (a priced book matched orders), and
  decisions may now accompany an unmatched delivery. The schema name stays
  `shared-candidate-delivery`. Replay applies the same rule: a retained group on a
  non-market delivery must be one that the fresh retained market could decide.
- **Effect.** A decision waits at most about one clock interval past readiness on
  every venue and instrument, whatever the market's activity. That makes the QR's
  modelled delay a small constant.
- **Tests.**
  - A pending served instant and a source-fed instant both decide on a clock, quoted
    at the retained market, unmatched. Their orders match on the next priced book,
    and the log replays exactly.
  - A stale book decides nothing on a clock.
  - Heartbeats and controls advance time the same way.

**Expected effect.** On the J6 layout, a served decision should wait about one clock
interval, plus the publisher's 100 ms poll, plus one warm materialization (about
0.2 s), plus at most one more clock interval for the next delivery. That is well
under 1 s against today's up-to-15 s. The development run measures it, and that measurement fixes the
QR's modelled delay.

**Tests.**
- **Writer:**
  - an idle queue writes clocks at the interval;
  - a busy feed writes none;
  - no record stamped before a clock is appended after it, under an injected snapshot
    race;
  - a regressed wall clock ends the session with `receipt_clock_regressed`.
- **Readers:** a recording with interleaved clocks reconstructs the same books,
  trades, quality, freshness and published partitions as the same recording without
  them.
- **Publisher:** with a silent trades feed that writes clocks, an instant publishes
  within one interval of the book passing it. Without clocks it waits, as today.
- **Supervisor:** as listed in CK-1.
- **Guides:** the market-data capture guide and the runtime guide's served-feature
  section document the record, the interval, and the delay a study should model.

**Validation.** The four lanes, then a J3–J6 development run whose served-delay
distribution is recorded here. J7 and M3f-3b build on that run.

## M3f-3a result (2026-10-05)

The durable receipt clock and addendum CK-1 are implemented. They land in the single
M3f-3 commit with M3f-3b.

**The development run (uncounted, not evidence).** `rehearsal-105` ran the driver's
real J1–J6 on the working tree, in continue-past-failures mode, reusing
`rehearsal-104`'s 30-minute J2 capture. The feeds declare a 250 ms clock interval, and
J6 used 300, 180 and 180 s phases.
- J1, J2, J4, J5 and J6 passed every criterion; J6 passed all 81.
- J3's one failure is a declaration error, not a code defect (see below).
- The supervised paper sources delivered 709 clocks in P-A and 402 in P-B, beside
  about 34,000 and 19,000 frames.

**Measured decision delays** (`coordinated_at − at`, from the J6 delivery logs):

| Phase | Feed | Rule (source-fed) | Learned (served) p50 / p90 / max |
| --- | --- | --- | --- |
| P-A | OKX BTC | 1 µs | 95 / 292 / 293 ms |
| P-A | OKX ETH | 1 µs | 189 / 289 / 290 ms |
| P-A | Bitfinex BTC | 1 µs | 175 / 256 / 276 ms |
| P-A | Bitfinex ETH | 1 µs | 189 / 285 / 347 ms |
| P-B | OKX BTC | 1 µs | 203 / 205 / 205 ms |
| P-B | OKX ETH | 1 µs | 185 / 187 / 187 ms |
| P-B | Bitfinex BTC | 1 µs | 172 / 312 / 312 ms |
| P-B | Bitfinex ETH | 1 µs | 237 / 324 / 324 ms |

- On `rehearsal-103`, without clocks, the served maximum was 15 s, and up to 74% of
  learned decisions waited more than 1 s. Now no served decision waits more than
  347 ms, on every venue and instrument. That is about one clock interval plus a warm
  materialization, as the note expected.
- A source-fed decision is coordinated 1 µs after its instant, whichever delivery
  crosses it, and its orders match at the next priced book. That is the book a
  research order placed 1 ms after the instant meets.
- **The QR's modelled delay is confirmed at 1 s** (`_SERVED_ENTRY_US`). It leaves about
  three times headroom over the measured maximum on a loaded host. The source-fed
  candidates keep 1 ms. The value does not change, so it needs no J3–J5 rerun.
  (Addendum P-1 changes research code, so the next rehearsal reruns J3–J5 anyway.)

**Defects the development runs found, all fixed with tests.**
- `rehearsal-104`: the saved research book projection
  (`research/exploration/projections.py`) read a clock row as a book row. A cutoff
  after a clock now reads the row before it, as the live source carries its market
  across a clock.
- `rehearsal-104`: `CapturedStudyMarket` offered clock rows to execution as market
  boundaries. It now skips them.
- `rehearsal-105`: J3's `holdout_consumed_as_declared` expected one holdout, but since
  the four-instrument J3 the driver consumes one per research instrument. The
  development declaration now declares four. Earlier J3–J5 dry runs had called the
  QR scripts directly, so this was the driver's first research check with four
  instruments.

**Refinements to the note, made while implementing.**
- **A clock producer task, not the writer.** `ReceiptStream.clock` runs beside each
  epoch's receiver. It stamps and queues a clock in one step, only into an empty
  queue, after the interval passes with nothing queued. Receivers also stamp and
  queue in one step, so the ordering argument of the note holds without touching the
  durable writer.
- **A clock waits for a settled queue (found by CI on Linux, PR #106).** The ordering
  argument above missed one step. A snapshot stamped while the queue was full waits
  for space. When the consumer frees the slot, the waiting put is woken but has not yet
  resumed. In that gap the clock saw an empty queue and enqueued a later stamp, and the
  snapshot then landed behind it. macOS scheduling hid this; the Linux runner hit it in
  `test_clock_never_overtakes_a_stamped_snapshot`. The capture queue now counts puts in
  flight, and the clock enqueues only into a settled queue: empty, with no stamped
  record still being put. A deterministic test frees the slot under a waiting put and
  checks that the queue stays unsettled.
- **The regression guard moved to receipt.** A `ReceiptClock` per recording stamps
  every receipt and refuses a wall-clock step back. A receiver ends its session with
  `receipt_clock_regressed`, and a snapshot becomes a gap with that reason. Local
  records (sessions, gaps, ends, clocks) never precede an earlier receipt. The
  journal-level guard was dropped, because the stamp is the one place a regression
  can enter.
- **The match-due rule (CK-1).** An instant crossed or decided on a non-market
  delivery sets a match-due flag. The next priced book matches orders and clears it.
  Replay applies the same rule.
- **Published histories keep clock rows.** Publication retains the capture's clock
  records, so a published recording replays exactly as captured. The saved readers,
  rather than publication, skip them, and the published partitions' market values are
  unchanged.

**QR finding.** The QR's rule policy raises on a missing touch instead of abstaining
through A-1's explicit abstention. It is recorded as a finding in the QR workspace's
`SOURCES.md`; the QR workspace is not edited to fix it, as the journey uses the QR's
work as written.

**Validation.** Before the two reader fixes, `make check`, the integration lane and
Linux strict mypy passed. The performance lane failed only timing-ratio tests that
also fail on `main` under host load. After the fixes, the unit suite passed (1,903
tests). The four lanes run again on the whole M3f-3 tree.

## M3f-3b result (2026-10-06)

The driver's J7 is implemented as the note and its addenda describe, and J7 passes
in development. It lands with M3f-3a in one commit.

**The passing development runs (uncounted, not evidence).**
- `rehearsal-115` ran the driver's real J1–J5 on the final shipped code. It reused
  `rehearsal-107`'s J2 capture, republished into its own lakeFS repository. Every
  criterion passed (J3 47, J4 16, J5 15). J3's twelve studies and grid ran in the
  bounded pool (P-1) in about 21 minutes, against 52 minutes in sequence on
  `rehearsal-105`.
- `rehearsal-117` reused `rehearsal-115`'s J2–J5 and ran J1, J6 and J7, with J6
  phases of 180/120/120 s and J7 phases of 120 s. Every criterion passed: J6 83 and
  J7 84.

**What J7 showed on `rehearsal-117`.**
- **Quiesce.** No J6 process held any of the 12 fences, and all four paper accounts
  were already stopped.
- **Backup.** The set holds `research/` (J2–J5: 1,026 files, 5.9 GB), `paper/`
  (12,034 files, 679 MB) and four account backups (28 MB). `backup-set.json`
  lists every manifest digest.
- **Restore.**
  - Research was restored with J2–J5 moved aside, so nothing could read the
    sources. Its manifest is equal, the 16 studies reopen with equal reports and
    results, and the restored QR store serves 130 values equal to the source's.
  - The restored paper store replays every J6 delivery log exactly.
  - Each restored account's receipt equals its backup receipt. Its views, orders,
    controls, fills, costs and checkpoints equal the retained journal's. It is
    quarantined, and the retained journal is not.
- **Resume (R), upgrade (U) and rollback (B).**
  - Every phase passed J6's per-phase checks: reconciliation each round, retained
    reports, the custom metric on dashboards, the alert received, and exact delivery
    replay.
  - U's receipt names v1 as the previous release. The late instance decided in six
    groups (no fills, as expected on the exhausted shared limit), and its stop
    control was accepted.
  - B's receipt selects v1 with v2 as previous, and the deployment check equals v1's.
    Fills, costs and controls were only extended, terminal orders are unchanged, and
    the late instance kept its checkpoint and placed nothing. U's delivery logs still
    replay exactly against the store.
- **Entry delay.** Every learned decision was at most 355 ms against the modelled 1 s,
  and every rule and reference decision 1 µs against 1 ms. The rule studies' 1 ms and
  the learned studies' 1 s were read from their retained orders.
- **Refusals.** Every refusal and dropped leg carried a declared paper-only reason:
  `holding_limit`, `insufficient_owned_inventory` and `self_trade_conflict`. There
  were none of `reissue_requires_current_reconciliation`, nor any unattributed stale
  decision.

**What the runs found.** Thirteen development runs (105–117) each found a defect, a
decision or a harness gap, all recorded above:
- **Shipped fixes.**
  - RP-1: a replaced, expired or rejected order ends with its parent, and no
    replaced order is reissued.
  - ST-1: a stale observation is refused, not recorded as a break.
  - RF-1, a one-call read of decision outcomes, and P-1, concurrent study sessions,
    are designs, not fixes.
- **Journey fixes.**
  - Services v2 names its predecessor.
  - Facts are retained as a typed record.
  - The study-order filter reads only timestamp pairs.
  - The restart is re-observed and resent, and every supervisor control must answer
    `ok`.
  - The race counts a reserved working order.
- **Decisions.** `self_trade_conflict` is a declared paper-only reason. A stale
  decision inside a control's run is attributed to that control. The late instance
  must decide, and its fills are retained.
- **Harness only.** These are not in the driver:
  - the holdout count is four, one per research instrument;
  - a reused J2 is republished into the attempt's own lakeFS repository, without the
    earlier attempt's feature backup;
  - `REUSE_RESEARCH` reuses J3–J5 when neither shipped code nor the QR changed.
  - Two runs (109, 112) were invalidated by my own edits to candidate-runtime modules
    mid-run. Packaged candidates pin that code, so such an edit needs a fresh J3–J5.

**Validation (as run on the committed tree, 2026-10-06).** The four lanes ran in
parallel. `make check` kept the project environment, and each other lane had its own
environment, so editable and non-editable installs could not race.

| Lane | Result |
| --- | --- |
| `make check` | Passed: 2,590 passed, 4 skipped, 25 deselected; wheel smoke passed |
| Integration (`-m integration`, Feast worker selected) | Passed: 40 passed |
| Performance (`-m performance`) | Passed: 25 passed |
| Linux strict mypy | Passed: no issues in 712 source files |

**Not done here.** The next counted-style rehearsal through J7, then M4 (MR15 R1
closure), M5 (MR15 stage 2b) and M6 (the counted journey). For M6, the six-hour
capture makes J7's backup about 60 GB, and backup plus restore double that on disk.

## M4a design note: compact market-data storage (direction approved 2026-10-06)

The owner chose this direction on 2026-10-06, over re-basing R1's limits (a named
profile R1b) and over a shallow R1 corpus. The details below follow the standing rule:
the most scalable and maintainable option, with no backward compatibility.

**Problem.**
- **The R1 corpus is gone.** Neither `data/okx/research-corpus-20260930/` nor
  `logs/capacity-closure/` exists on the host. Under owner decision 2, M4 needs a
  fresh 72-hour acquisition. The owner decided to arm it only after the rehearsals
  pass.
- **Book publication expands about 24 times.** A canonical book partition stores the
  whole visible book, as JSON, on every update (`BookStream`). On rehearsal-6, 23 MB
  of raw capture over 30 minutes published as 1.1 GB, of which two OKX partitions
  were 519 and 465 MB.
  - A 72-hour OKX BTC/ETH corpus projects to about 140 GB canonical. R1's workspace
    limit is 10 GiB, and the host has 350 GiB free.
  - M6's six-hour J2 makes J7's backup about 60 GB for the same reason, and 2b
    replays the same format.
- **Raw journals are uncompressed JSONL.** A sealed OKX book segment compresses about
  8 times with zlib. At the uncompressed rate, 72 hours of raw OKX capture projects to
  about 4.7 GB, against R1's 2 GiB source limit.

**The change.**
1. **A compressed frame container** (`FrameWriter` and `FrameReader`, in
   `serialization`). A book partition becomes:
   - a header record binding the partition to its complete source selection, as now;
   - then a sequence of independently decodable zstd frames (`compression.zstd`,
     standard library). Each frame holds at most 4,096 records and closes once it
     reaches 8 MiB. A record is at most 16 MiB, and a reader refuses a frame above
     64 MiB, compressed or not, before it allocates.
   A reader holds one frame and one book at most.
   - **Trade partitions are not changed.** On rehearsal-6 they were about 3 MB of the
     1.1 GB of canonical output; for the 72-hour two-instrument corpus they project to
     about 270 MB. Such a partition is still one in-memory history. If R1's 8 GiB
     memory limit is missed because of it, it moves to the same container, with a
     streamed reader.
2. **Book rows are stored as deltas.**
   - The first row of every frame is stored whole.
   - Every later row stores its coordinates (position, epoch, clocks, sequence,
     outcome, status, reason, state identity) and only its change from the row
     before it:
     - for L2, the levels set and the prices removed on each side;
     - for L3, the orders upserted and the order identities removed.
   - A row whose representation differs from the previous row's (no visible state,
     or a change between L2 and L3) is stored whole. An empty state on a control or
     invalid boundary therefore never reads as an empty book.
   - `BookSnapshot.observations()` rebuilds every `BookObservation` exactly. Every
     consumer reads through it: replay, query and the captured study market.
3. **One digest, of the stored file.**
   - A partition's `sha256` names the stored file, as now, and a reader checks it
     before it exposes a row.
   - Verification decodes every row and compares it with fresh normalization of the
     raw source. It never re-compresses, so it does not depend on the zstd build.
   - Publication is deterministic for one installed build. A different zstd build may
     publish the same rows under another identity. Nothing republishes to reproduce an
     identity: restores copy files, and reopening verifies rows.
   - A delta rebuilds its sides in ascending price order and its orders in
     ascending identity order. A row is therefore a delta only when it and its base
     are both in that order. Both book producers sort, so every published row
     qualifies. A derived row, such as the study market's best-first bounded depth,
     is stored whole. Ascending order is not made a `BookObservation` invariant,
     because derived rows rely on best-first order.
4. **Sealed raw captures are compressed.**
   - `RawStore.publish` takes an explicit `compress`. A compressed object is stored
     as zstd under its original bytes' `sha256` with `.zst` appended; `RawObject` is
     unchanged.
   - Capture journals (sealed or interrupted) are compressed. Archive downloads,
     already compressed and replayed by path, and REST pages are stored as they are.
   - `open` verifies the original digest by streaming decompression, then returns a
     stream of the original bytes. An object present in both encodings is refused.
   - Publication copies an object between stores in its stored encoding
     (`RawStore.copy`), so it is never decompressed and compressed again.
   - The live `journal.jsonl` stays plain, because the paper services follow it by
     byte offset. Whether the sealed copy can be the only retained raw copy is
     measured in M4a and decided with its result, not assumed.
5. **Limits.**
   - A dataset's `max_bytes` applies to stored bytes.
   - The frame bound applies to uncompressed bytes.
   - R1's source and workspace limits count stored bytes. Their measured
     uncompressed sizes are reported beside them.
6. **Release and records.**
   - This changes the book partition format and `RawStore` objects in place. It touches the collector, research and
     paper-services releases.
   - No reader for the old formats is kept. Existing captures and evidence stay
     valid at their own commits.
   - lakeFS publication copies the stored files unchanged.
   - M4a changes J2–J7's code path. The rehearsal after it therefore reruns J1–J7,
     and stage 2b qualifies the result.

**Tests.**
- Exact round trips, including decimal text (`100` and `100.0` differ): L2 sets
  and removals, L3 upserts and removals, control and gap rows, a change between L2
  and L3, a frame boundary in the middle of a book, and a best-first row stored
  whole.
- Refusal of a delta without its base: at a frame start, after an absent state,
  removing an absent entry, emptying the state, or mixing L2 and L3 changes.
- A corrupted frame, a truncated file and an oversized frame are each refused before
  any row is exposed.
- Raw objects: a compressed round trip, a copy in its stored encoding, refusal of a
  truncated object and of two encodings, and reuse across encodings.
- The existing replay, query, captured-market and publication suites, unchanged in
  expectation.

**Measurement before acceptance.** Republish one rehearsal's J2 capture (30 minutes
or more, eight feeds) on the new code. Report:
- stored and uncompressed bytes, per partition and for raw objects;
- publication, verification and reopen times;
- row-for-row equality with the old format's observations, using a one-off script
  outside `src/`;
- the 72-hour projection against R1's 2 GiB, 10 GiB and 100 GiB limits.

If raw storage still misses 2 GiB, the result goes back to the owner as a named
profile. R1's limits are not raised here.

**Addenda (2026-10-06).** While M4a was being implemented, two more scaling
defects and R1's volume question came up. The owner delegated all three under the
standing rule, and they are decided as follows.

- **CH-1: one book partition per capture chain.**
  - *Defect.* A rolled-over capture run publishes one book partition per segment, and
    each later segment's reader replays every earlier segment to rebuild its book
    (`SourceAdapters.books`). Publication, and every verification, is therefore
    quadratic in segment count. A 72-hour run may have 150 segments per source.
  - *QR gap found with it.* The QR's J3–J5 scripts select the first book partition
    for each instrument (`next(...)`). With per-segment partitions they study only a
    run's first segment.
  - *Change.*
    - A book partition is selected by its chain's last segment, as a trades partition
      already is.
    - Its rows cover every record of the chain, in one pass, with positions counted
      from zero across the chain.
    - `max_records` bounds the last segment, as for trades. The stored-bytes limit
      bounds the whole partition.
    - Publication refuses two selections from one chain.
    - The guide and the QR's `j2_publish.py` select each book run's last segment, as
      they already do for trades. This is a QR workspace commit.
- **RV-1: reopening checks digests; re-derivation is explicit.**
  - *Defect.* Every `SnapshotStore.read`, and so every study open, re-derives every
    book and trade partition from raw. That took about 49 s for 30 minutes of eight
    feeds, and the cost grows with corpus length on every open.
  - *Change.*
    - Publication still re-derives every partition before the snapshot becomes
      visible.
    - Reopening checks the manifest identity, each partition file's SHA-256 and
      each raw object's SHA-256. It does not re-derive.
    - The manifest's `normalization_identity` stays as provenance. Comparing it with
      the installed normalizer at reopen was considered and rejected: market_data
      would have to import `runtime` for the identity, and every development build
      would re-derive on every open.
    - The original REST trade format (`DatasetManifest`) still re-derives on every
      read. Its quality reports come from that reproduction, and its inputs are
      bounded in memory.
    - An explicit audit (`SnapshotStore.read(..., rederive=True)`, also on
      `BookSnapshot.read`) always re-derives. The QR's J2 reopen script uses it.
  - *What still holds.* Any byte change to a manifest, partition or raw object is
    refused. The only thing no longer repeated on every open is re-derivation. A
    snapshot published under an earlier normalizer is read as it was published; an
    audit shows whether the installed normalizer would derive the same rows.
- **R1b: a named profile on the full-rate corpus.**
  - *Finding.* R1's publication (300 s for all inputs), study (600 s) and reopen
    (60 s) limits fit its stated minimum of about 100,000 records. The fresh corpus
    is full-rate OKX BTC/ETH books and trades: about 7 book messages a second per
    instrument, so about 4 million records in 72 hours. Rehearsal-6 published about
    79,000 records in 56 s, about 1,400 a second.
  - *Decision.* M4 qualifies a new named profile, **R1b**, on the full-rate 72-hour
    corpus, because that corpus is what the journey and the runtime actually
    consume.
    - R1b keeps R1's inputs, provenance, decisions, features, retention, correctness
      and recovery rules.
    - It re-bases throughput, reopen and storage limits on M4a's measured rates, with
      the rationale recorded beside each limit.
    - R1 and its failed evidence stay as recorded.
  - *When.* R1b is declared after M4a's measurement, before the acquisition is
    armed.
  - *Owner decision (2026-10-06).* The corpus stays 72 consecutive UTC hours. A
    24-hour window was offered and declined. The acquisition is armed right after
    rehearsal-9 passes, and M5 preparation overlaps it.
  - *Superseded the same day (owner, 2026-10-06).*
    - The armed acquisition was disarmed before its window opened (all four runs
      `stopped_before_start`). The host is a laptop that sleeps in transit, and no
      always-on machine is available.
    - The owner decided not to run the 72-hour acquisition for now. R1b is qualified
      from measured runs on the one-hour corpora, with throughput, storage and
      retention extrapolated to 72 hours by a stated linear model.
    - Linear extrapolation is defensible because the paths that grew faster than
      linearly are gone:
      - full-state storage, replaced by the compact store;
      - per-segment chain replay, replaced by CH-1;
      - re-derivation on every reopen, replaced by RV-1.
    - The extrapolation is recorded beside each limit as an extrapolation, not a
      measurement. A full-length acquisition stays possible later, on an always-on host,
      as confirmation.

## UV-1 design note: an unvalued fold is an outcome, not a crash (2026-10-06)

The owner asked for the most scalable and maintainable option, with no backward
compatibility, and this is it.

**Defect (development run rehearsal-121).**
- J3's first learned study raised *"open intent holding requires a fresh terminal
  bid"* and aborted the whole study.
- At fold 2's end (05:28:22 UTC), OKX BTC's latest valid update was 2.9 s old. A
  network outage at 05:28:10 had left the reconnected stream sparse. The QR's
  `max_book_age_us` is 2 s, and the learned policy held a position.
- `IntentExecution.run` refuses a stale terminal price, which is right. But it raises,
  so one fold's missing valuation ends every fold and the study.
- Longer corpora (R1b's 72 hours, M6's six hours) make such fold ends certain.

**Options considered.**
1. *An explicit unvalued outcome* (chosen).
2. *A separate, looser valuation-age bound.* Rejected: it moves the cliff, and a long
   stale period still aborts a study.
3. *Marking at the last then-known bid of any age.* Rejected: it weakens the
   fresh-quote rule of `Ledger.mark`.

**The change.**
1. **`IntentSimulationResult`.**
   - `mark` and `net_return` become optional, beside a new `unvalued_reason`.
   - With an open holding and no fresh terminal bid, both are absent and the reason is
     `"no fresh terminal bid for an open holding"`. Otherwise both are present and the
     reason is absent.
   - The result check enforces exactly that, and recomputes a present mark from the
     ledger as now.
   - The run no longer raises at the terminal mark.
2. **`FoldSummary`.** `terminal_mark` becomes optional, with
   `terminal_missing_reason`. The curve's last point carries the same missing mark and
   reason. The report already renders a missing period ("Missing return periods").
3. **`TrialEvaluation`.**
   - `net_return` becomes optional, with `missing_reason`.
   - A trial with any unvalued fold has no objective. A mean over the valued folds is
     not used, because valued folds differ between trials, so it would compare
     different opportunity sets (study protocol, "common opportunity set").
4. **Search (`compare_studies`).**
   - A trial without an objective is rejected with its reason, through the existing
     rejection path, and told to Optuna as `FAIL`.
   - Selection proceeds among the other trials. If none is accepted, the existing
     no-selection outcome applies.
   - Tracking publishes the exact return only when present.
5. **A single study (`evaluate_study`).** It completes. It retains every fold, the
   report with the missing period, and the trial evaluation with its reason.
6. **Unchanged.**
   - `Ledger.mark` still refuses an open holding without a price.
   - Entry still requires a fresh book.
   - The candidate replay and paper paths do not use the terminal fold mark.

**Tests.**
- A fold ending inside a gap with an open holding yields the unvalued result, and
  every other fold still runs.
- A forged result is refused: a mark without a valuation price, or a reason with a
  mark.
- A search with one unvalued trial selects among the rest; with all unvalued, nothing
  is selected.
- A report renders the missing period.
- A trial evaluation cannot have both a return and a reason.

## HS-1: the journey holds the host awake (2026-10-06)

- **Finding.** Development runs 120–122 failed J3: an unvalued terminal fold, then
  singular least-squares fits. The cause was not the code. The power log shows the
  Mac went into idle sleep at 05:21:57 UTC for 358 s and again at 05:30:55 for 693 s,
  waking at 05:42:28.
  - Every collector froze: no frame and no receipt clock was written for about 18 of
    the 60 captured minutes.
  - The disconnects at 05:28 and 05:42 were reconnects after wake.
  - Neither the driver nor the development harness held a sleep assertion.
    Rehearsals 7 and 8 stayed awake only through other activity on the host.
- **Change.** `Journey.run` holds `caffeinate -i -s -w <driver pid>` for the whole
  attempt on macOS, and refuses to run there without it. The assertion dies with the
  driver. Owner decision 11 already required this for long runs.
- **What stands from these runs.**
  - QR abstention (`f66aef4`) and UV-1 remain: real gaps happen, and both fix
    fragilities those runs exposed.
  - The gapped capture itself is not used as evidence.

## Rehearsal 7 (uncounted, 2026-10-06): stopped, temporary root deleted

- **Declared run.** Rehearsal-7 ran the real driver from a clean tree at `e34d56a`, with
  QR commit `58773b2`, through J7: a 60-minute J2 window, J6 phases of 600/300/300 s and
  J7 phases of 300/300/300 s. It started at 03:04 UTC.
- **J1 passed.**
- **Why it was stopped.** During the J2 capture, `/private/tmp` was cleared in Finder:
  the folder was opened at 03:05:43 and the Trash emptied at 03:19:30. This deleted
  the attempt's temporary root `/private/tmp/mr17/rehearsal-7`, which held its build
  and research environments. The collectors kept running from memory, but every later
  J2 command named a deleted binary.
- **What was done.** At the owner's request the attempt was stopped at 04:00 UTC with
  SIGTERM, before any step could fail on the missing environment. Its summary was
  never finalized and still reads `running`. No criterion failed, and no code defect
  was found.
- **Change for later attempts.** The temporary root moves off `/private/tmp`:
  rehearsal-8 declares `/Users/lxg/mr17t` (outside iCloud, short enough for socket
  paths) and sets `TMPDIR` under it.

## Rehearsal 8 (uncounted, 2026-10-06): J2 failed, fixed by M4a

- **Declared run.** As rehearsal-7, at the same commits, with the new temporary root.
  It started at 04:01 UTC.
- **J1 passed.**
- **J2 failed** at `publish:capture_publish_succeeded`: *"book canonical stream exceeds
  max_bytes"*.
  - The QR publishes with the guide's `--max-bytes 1000000000`.
  - In the old format, 60 minutes of OKX BTC-USDT publishes as a 1,043,422,033-byte
    partition (measured below), because every update stores the whole 400-level book.
  - Rehearsals 3–6 passed J2 with 30-minute windows, at about 500 MB a partition.
    With the old format, no J2 of 60 minutes or more could pass. M6's six hours
    could not either.
- **Fix.** M4a's compact book store, below. The next attempt, rehearsal-9, runs on
  M4a.

## M4a measurement (2026-10-06, uncounted, not evidence)

Rehearsal-8's J2 capture (60 minutes, eight feeds, one segment per run) was cloned and
republished on the M4a worktree. The new code first stored the raw objects compressed,
then published each run's last segment through `DatasetPublication.publish_captures`.

| Book partition | Rows | M4a stored | Old format | Ratio |
| --- | ---: | ---: | ---: | ---: |
| OKX BTC-USDT | 28,992 | 3,420,863 | 1,043,422,033 | 305 |
| OKX ETH-USDT | 28,416 | 3,318,641 | 974,280,952 | 294 |
| Bitfinex BTC/USD | 64,650 | 3,708,544 | 232,940,925 | 63 |
| Bitfinex ETH/USD | 58,125 | 3,152,618 | 190,779,655 | 61 |

- **Exactness.** Every stored row of every partition equals a fresh normalization of
  the raw input, byte for byte in the codec's exact encoding (180,183 rows). The old
  sizes are those rows' old encodings.
- **Raw.** 56,908,924 bytes are stored as 5,950,590, a ratio of 9.6, compressed in
  0.68 s.
- **Trades.** Four trade snapshots, unchanged in format, take 10.4 MB.
- **Times** (one process, M1 Max, host shared with other work):
  - Publication, including full verification: 120 s, 162 MB peak RSS.
  - Reopen with digest checks: 0.09 s. The old full re-derivation took about 49 s for
    30 minutes on rehearsal-6.
  - Audit with `rederive=True`: 59 s.
  - Reading every book row: 28.6 s, about 6,300 rows a second.
- **72-hour projection** for OKX BTC/ETH books and trades, scaling the OKX shares
  linearly. This is an extrapolation from one hour, not a measurement:
  - about 0.5 GB of book partitions;
  - about 0.3 GB of stored raw;
  - about 0.7 GB of trades;
  - publication taking about 2 to 2.5 hours on one process.
  Storage fits R1's 2 GiB source and 10 GiB workspace limits. Publication time is the
  measured rate that R1b's throughput limit will be based on.
- **Not covered by this capture.** No run rolled over, so it exercised one-segment
  chains only. Multi-segment chains are covered by the rollover unit test (CH-1).
- **Validation on the M4a tree.**
  - `make check`, integration (40 passed), performance and Linux strict mypy passed.
  - One `make check` test failed only because the recreated lane directory had group
    `wheel`, which drops setgid; it passed after the group was fixed.
  - One performance timing-ratio test failed under host load and passed when rerun
    alone.

## M4a result (2026-10-06)

M4a lands as one commit: the compact book store, compressed raw captures, CH-1, RV-1,
UV-1 and HS-1, with the guides. The QR's changes are on its `m4a-compact-storage`
branch: `76c3643` (J2 publication and audit), `f66aef4` (the rule abstains without a
touch) and `7a7f28e` (an unvalued fold is missing in the metric and chart).

**Development run rehearsal-123** ran on a fresh 60-minute J2 with the host held
awake.
- J1, J2 and J3 passed every criterion: eight captures, publication, reopen,
  lakeFS, every rule, learned, holdout and grid study, publication and the extension
  check.
- It went on to J4–J7 unattended and passed every criterion there too: J4 16, J5 15,
  J6 83 and J7 84. That makes 291 criteria with none failed, on a 60-minute J2, the
  window that failed rehearsal-8 under the old format.

**Fault-injection development runs (uncounted, not evidence).**
- *Rehearsal-124* had a 30-minute J2 with 300 s segments.
  - Every run rolled over into 6 segments.
  - One collector was frozen for 40 s.
  - A real Bitfinex disconnect occurred at 08:41:45.
  - J2 passed: each chain published as one partition.
  - J3 failed on FX-1, the incomplete training row.
- *Rehearsal-125* reused that J2, with FX-1 applied.
  - J1–J5 and J7 passed every criterion: J3 47, J4 16, J5 15, J7 84.
  - J6 passed 82 of 83. Its one failure, `P-B:alert_received`, is fixed by AL-1: phase
    A alerted, and J7's phases received 26, 27 and 26 datagrams.

**Validation (as run on the committed tree, 2026-10-06).** The four lanes ran in
parallel; `make check` kept the project environment, and each other lane had its own.

| Lane | Result |
| --- | --- |
| `make check` | Passed: 2,611 passed, 4 skipped, 25 deselected; wheel smoke passed |
| Integration (`-m integration`, Feast worker selected) | Passed: 40 passed |
| Performance (`-m performance`) | Passed: 25 passed |
| Linux strict mypy | Passed: no issues in 715 source files |

**Plan change (owner, 2026-10-06).**
- The 72-hour acquisition is armed right after this commit, not after another
  rehearsal. It depends only on the collector, which J2 has now exercised.
- Hour-long development rehearsals give way to a fault-injection journey of about 80
  minutes: a 30-minute J2 with 300 s segments, which forces rollover chains, and one
  collector frozen for 40 s.
- R1b is assessed on sealed segments while the acquisition runs.
- One full rehearsal runs on the frozen commit, before the counted M6.
- Stage 2b's gates are brought to the owner as a trim list.

## FX-1: an incomplete training row is left out and named (2026-10-06)

- **Defect** (fault-injection run rehearsal-124).
  - Bitfinex ETH's learned study raised *"fitting requires complete matching
    feature signatures"* and aborted.
  - Its trades capture really disconnected at 08:41:45 UTC. One training row's
    trade-flow feature was then missing, and `FittingRows.select` refused the whole
    fold.
  - A missing label failed the same way.
- **Precedent.** Inference already excludes a decision whose feature is missing, and
  records it as `"missing inference feature"`.
- **Change.**
  - Transform and model fitting leave out a training row with a missing feature or
    label. Nothing is imputed.
  - Each fitted version's `fit_rows` names exactly the rows used.
  - The model's rows must be a subset of the transform's.
  - The fold's retained exclusions add each left-out row with
    `"incomplete training row"`.
  - A fit with no complete row still raises.
  - Mismatched feature signatures still raise.
- **Tests.**
  - A gapped feature row and an unlabelled row are left out and named.
  - No complete row raises.

## AL-1: the alert criterion is per step, not per phase (2026-10-06)

- **Defect** (fault-injection rerun rehearsal-125). J6 failed `P-B:alert_received`:
  0 datagrams.
- **The criterion depended on market outcomes, not on the platform.**
  - Phase B issues no control and injects no fault.
  - On rehearsal-123 its alerts came from the paper net-P&L rule (`paper.net_pnl < 0`)
    and the QR metric's warning band, because those positions lost money within the
    120 s phase.
  - On rehearsal-125 they did not lose, so no rule tripped.
- **The approved J6 criterion** is "alert observed by the local receiver".
- **Change.**
  - Each phase records its received datagrams as `alerts_observed`, which does not
    gate.
  - The driver requires at least one alert across J6's paper phases
    (`paper_alert_received`; P-A's injected order uncertainty makes it deterministic).
  - It likewise requires one across J7's R, U and B (`operations_alert_received`).

## Owner decision: stage 2b trims (2026-10-06)

The owner approved six trims to stage 2b's sequencing. Its targets, budgets and
requirements are unchanged and not waived (runtime capacity, owner decisions of
2026-10-02 and 2026-10-04).

1. **Both grant denial trials in one short session.**
   - Denial after expiry is shown with a grant of the same signed form but a
     minutes-long life.
   - Denial after revocation is shown on a 26-hour grant.
   - It is one session, not separately declared trials.
2. **Shorter uncounted rehearsals.** They run about 2 hours: rollover, the 25-hour
   lifetime caps, the order-light mix, and a 4× replay of the 2-hour corpus. Only the
   counted attempt runs 24 hours.
3. **The 4× replay of the counted 24-hour corpus** starts right after the counted
   run, while the 72-hour retention elapses.
4. **M6, the counted journey, may run while 2b's 72-hour retention elapses.**
   - J8 is evaluated once retention has passed.
   - J8 takes no new measurement; it links the accepted R1b and 2b records.
   - A retention failure still fails J8, and with it M6.
5. **The repository moves out of iCloud-synced Documents before 2b starts,** so the
   quiet-host gate needs no iCloud waiver. Recorded paths are updated at the move.
6. **Checkpoint percentiles** (at least 1,000 per account) come from the counted
   24-hour run itself.

Free disk was 470 GiB on 2026-10-06. 2b needs at least 512 GiB at its start.

## FX-1 and AL-1 validation (2026-10-06)

The four lanes ran on the tree with FX-1 and AL-1 and the day's record updates.

| Lane | Result |
| --- | --- |
| `make check` | Passed: 2,612 passed, 4 skipped, 25 deselected; wheel smoke passed |
| Integration (`-m integration`, Feast worker selected) | Passed: 40 passed |
| Performance (`-m performance`) | Passed: 25 passed |
| Linux strict mypy | Passed: no issues in 715 source files |

## M4b design note: R1's workflow streams the captured corpus (2026-10-06)

Decided under the standing rule: the most scalable and maintainable option, with no
backward compatibility. Found while building R1b's measurement on a fresh capture.

**Measurement harness.**
[`native_capacity.py`](../../tests/integration/consumers/research/native_capacity.py)
runs R1's combined workflow on a captured OKX BTC/ETH books and trades corpus:
- publication, digest reopen and a re-derivation audit;
- a completed-return feature over captured books: materialized with Feast, every PIT
  cell checked against an independent scan of the stored rows, warm close latency,
  offline Feast chunks;
- four costed `ConfirmedSignal` trials on two workers, with one worker killed mid-trial,
  recovery and an uninterrupted control;
- report reopen, then backup and restore of inputs, features and results.

It reuses `capacity_workload.py`'s measurement and runs beside it.

**Defects found on a 6-minute pilot capture**, projected linearly to 72 hours at about
2.35 million book rows per instrument:

| Defect | Pilot measurement | 72-hour projection |
| --- | ---: | ---: |
| `SavedDecisionSource` kept every full 400-level book row in memory | 64 KB a row | about 150 GB per instrument |
| `CapturedStudyMarket.read` built the whole window as one tuple | 4.9 KB a row | about 11.5 GB per trial |
| Each fold stored that market again as its `market-NNNN` artifact | 2.7 KB a row | about 6.4 GB per trial |
| `ScheduledFeatures` (completed returns) reads only the REST trade format | n/a | no native completed returns |

**Changes.**
- **SF-1: `CompletedReturnFeature`.**
  - A generic-lifecycle kernel: `completed-return`, incremental, one input, a
    `cadence_seconds` parameter.
  - It freezes each decision's then-known close from any saved source, for example a
    captured book's `bid`.
  - It returns that close against the previous decision's close only when both exist
    exactly one cadence apart. Otherwise the return is missing, with its reason.
  - `ScheduledFeatures` is unchanged and remains the REST-format path.
- **SM-1: the study market streams.**
  - `StudyMarketSource.read` returns an iterable, consumed once.
  - `IntentExecutionModel.run` takes an iterable market. `IntentSimulation` validates
    each row as the model reads it, and validates any rows it leaves unread after it
    returns.
  - `LimitOrderExecution` schedules a row only when the next event is no earlier than
    the row. It releases the row once stepped. Every row still joins before any later
    event and before an equal-time event of a later phase, so results are unchanged.
  - Nondecreasing availability was already a validated contract, and capture receipts
    never move backward (`ReceiptClock`).
  - `CapturedStudyMarket.read` is a generator.
- **MK-1: a fold retains a market manifest, not the rows.**
  - `market-NNNN` is a `StudyMarketManifest`: market identity, window, row count, first
    and last clocks, and the SHA-256 of the consumed rows' canonical encodings.
  - The rows are reproducible from the pinned snapshot.
  - The cutoff check (no row past the fold's market window) runs on each row as it
    streams.
- **SB-1: `SavedDecisionSource` walks books forward.**
  - The book index holds the row at or before the latest cutoff asked, plus one query
    batch.
  - An earlier cutoff restarts the stream, so any order of reads returns what a fresh
    read returns.
  - `ResearchReader.books(query)` opens a verified reader for streaming.
  - Other inputs are read whole once, as before. Trade histories stay in memory: R1b's
    workflow does not select them.
  - Memory is bounded by `batch_size` whole books, so a long consumer should choose a
    small batch. The harness uses 32: a close that crosses a batch decodes it, so a small batch keeps close latency even.

**Not changed.** Feature values, fills, fees, marks and the order of every execution
event are unchanged. The existing simulation, study, captured-market and decision
suites pass unchanged in expectation, apart from:
- the market manifest check;
- the generator call sites in two captured-market tests.

**Tests.**
- Completed returns: exact values, every missing reason, checkpoint continuation and
  refused definitions.
- A single-use market iterator gives the tuple's exact result, and disorder is refused.
- Saved book fields read in reversed and shuffled cutoff order, through 3-row batches,
  equal a forward pass.

## M4 result: R1b qualified by extrapolation (2026-10-06)

- **Corpus.** A fresh 2-hour OKX BTC/ETH books and trades capture, taken with the laptop
  on AC and held awake: 221,240 raw positions, chained replay parity, and one real ETH
  trades disconnect kept as an explicit gap.
- **Workflow.** R1's combined workflow ran on it end to end, with M4b's fixes. Recorded
  in [research capacity](research-capacity.md#named-profile-r1b-declared-2026-10-06-by-extrapolation).
  - Every PIT cell and every trial's fees and terminal NAV equalled independent
    recomputation.
  - A killed worker's retried trial equalled an uninterrupted control.
  - Restore matched every result.
- **R1b.** The named profile is declared there, with each re-based limit and its
  rationale. Every 72-hour extrapolation is inside its limit, so R1b is qualified by
  extrapolation, labelled as such.
  - The main re-based limits: publication ≤ 4 h for 72 hours (measured about 760
    positions a second), materialization ≤ 1 h, studies ≤ 3.5 h in total.
  - R1's latency, reopen, memory and storage limits are unchanged and met.
- **Not established.** 72 hours of original-clock coverage is not established. A
  full-length acquisition on an always-on host remains the confirmation.
- **Trade partitions.** They are still held whole in memory during publication, which
  projects to a peak of about 5.4 GB at 72 hours. They move to the frame container if a
  measured run nears 8 GiB.
- **Service docs.** The lakeFS and ClearML guides no longer name the deleted MR04
  restored projects. They give the first-user setup for an empty lakeFS volume, which
  reuses the existing keys.

**Validation (as run on the committed tree, 2026-10-06).**

| Lane | Result |
| --- | --- |
| `make check` | Passed: 2,621 passed, 4 skipped, 25 deselected; wheel smoke passed |
| Integration (`-m integration`, Feast worker selected) | Passed: 40 passed |
| Performance (`-m performance`) | Passed: 25 passed |
| Linux strict mypy | Passed: no issues in 717 source files |

An earlier run of the same lanes failed only the engineering-standards check: nested
and module-level helpers, and one missing docstring. They were moved to class owners.

## Repository move (2026-10-07)

The owner chose `~/Code/alpha-research-lab-private` (stage 2b trim 5).
- **Clean-up.** Before the move, 28 cloud-only iCloud conflict copies were deleted:
  `.git/AUTO_MERGE N`, `.git/index N`, and `jwt/* 2.py` in the worker environment.
- **The move.** The checkout was then renamed out of iCloud Documents.
- **Links.** The `.venv` and cache symlinks were kept. The `~/mr17t/r1b/src` worktree was
  repaired. The Feast worker environment was rebuilt for the new path.
- **Caches.** Bytecode caches compiled at the old path were cleared: their stale file
  names failed the venue-secret tests' traceback checks.
- **Recorded paths.** No tracked file named the old path. The harness tools
  (`dev_journey.py`, `validate-isolated.sh` and `validate-parallel.sh`) were updated. The
  rehearsal 1–8 declarations keep the old path as historical records.
- **Effect on 2b.** The quiet-host gate no longer needs an iCloud waiver for the
  repository.

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
4. **M4 — MR15 R1 closure.** Done 2026-10-06 as the named profile R1b, qualified by
   extrapolation ([M4 result](#m4-result-r1b-qualified-by-extrapolation-2026-10-06)).
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
