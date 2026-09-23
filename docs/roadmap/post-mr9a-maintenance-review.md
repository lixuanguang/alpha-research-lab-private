# Post-MR9A maintenance review

Owner: repository founder. Assessed 2026-09-23 against clean `main` at `aa6d6f0`,
before the accompanying documentation edits. Subsequent cleanup passes are
recorded below. The original findings describe that assessed revision; each pass
states its own changes and validation. Retained historical evidence bytes remain
unchanged.

The founder confirms MRs through 9A are implemented and closed. Future work follows
the [OKX/Bitfinex data policy](README.md#current-platform). Closure does not erase
historical limitations or make every acceptance consumer disposable.

## Acceptance-scaffolding cleanup

Implemented at the founder's request on 2026-09-23:

- Removed 11 standalone dataset, eligibility, query and EDA demos: 1,869 lines
  already covered by maintained regressions. Consumers fell from 28 / 7,381 lines
  to 17 / 5,485 lines after the harness changes. Notebook-used as-of/replay scripts
  and manual service checks remain.
- Replaced wheel smoke's five full acceptance workflows with one bounded OKX
  book CLI/report run. Package imports, resources, identities, historical-snapshot
  reopening and the governance-free installation boundary remain checked.
- Moved economic and engineering-sample workflows into discovered integration
  tests. Moved installed capture CLI/API parity into the existing recovery
  consumer. Feature/model/diagnostic, ingestion, checkpoint and process-death
  regressions remain in the domain test lane; no live service is required.
- Shortened the test guide and replaced links to retired demos with maintained
  tests. No notebooks or historical evidence identities were rewritten.

The deleted demonstrations' owning coverage is in `test_rows`, `test_occurrences`,
`test_revisions`, `test_datasets`, `test_quality`, `test_snapshots`,
`test_dataset_command`, `test_eligibility`, `test_eligibility_selection`,
`test_asof`, `test_query`, `test_eda` and `test_eda_pipeline`. The
[test guide](../../tests/README.md#installed-boundaries-and-domain-regressions)
describes current installed boundaries and callers.

Validation: six installed workflow tests passed, followed by 263 mapped domain,
CLI and layout regressions; both selections had zero skips/deselections. Ruff
lint/format and strict mypy passed over the integration consumers/callers and
wheel-smoke tooling (21 files). The engineering checker, scoped Bandit,
52-file Markdown link check and diff whitespace check passed. No references to
deleted consumer basenames remain in tracked code, notebooks or documentation.
`env -u ALPHA_CLEARML_LOCAL_ENV TMPDIR=/private/tmp make wheel-smoke` passed from
a fresh hash-locked installation, retaining its wheel and outputs at
`/private/tmp/alpha-research-wheel-smoke-n1p357ha/`. The first sandbox invocation
could not access uv's cache; the permitted rerun completed successfully.
The bounded retired-demo audit/removal used a `gpt-5.6-luna` subagent at `max`;
the main agent integrated and validated the combined changes.

Pre-merge local CI on 2026-09-23: `env -u ALPHA_CLEARML_LOCAL_ENV
TMPDIR=/private/tmp make check` passed on CPython 3.14.7 / macOS arm64, including
all static/security/dependency checks, **1,246 tests passed**, three performance
tests deselected and zero skips, plus fresh installed-wheel verification.
The log is `/private/tmp/acceptance-scaffolding-local-ci.log`; wheel evidence is
`/private/tmp/alpha-research-wheel-smoke-53d_x0i7/`. The founder explicitly selected
local CI as this change's merge gate because hosted credits were exhausted;
the merge uses `[skip ci]` without changing repository CI configuration.

### Second cleanup pass

The follow-up pass retires the 408-line engineering-sample runner. Maintained
qualification and economics tests retain its distinct CLI admission and unfitted
configuration/report checks; the existing economic workflow retains installed
reopen, report failure and fresh-process recovery. Frozen configurations and
historical evidence remain available.

Feature/model, economic and Feast consumers now run domain checks independently
of ClearML. One explicit [service verifier](../../tests/integration/consumers/research/clearml_publication.py)
owns local credential setup, lost-receipt recovery in a fresh process, idempotent
publication, unique tasks and exact remote artifact checks. Model creation precedes
reload publication. Former service-only rejected, failed and abandoned model
assertions now execute in ordinary CI. The [service runbook](../../configs/development/clearml/README.md)
documents the separate invocation. No runtime application or provider adapter changed.

Acceptance scripts fall from 5,485 to 4,933 lines (another 10%; 33% below the
original 7,381). This is the consumer-tree reduction, before accounting for the
small domain-test additions and documentation edits. The bounded retirement and
coverage migration used `gpt-5.6-luna` at `max`; the main agent reviewed and
integrated it. Live ClearML and the separately installed Feast worker were not
rerun in this cleanup; offline verifier probes do not claim service acceptance.

Validation on 2026-09-23: `env -u ALPHA_CLEARML_LOCAL_ENV TMPDIR=/private/tmp
make check` passed on CPython 3.14.7 / macOS arm64: **1,246 tests passed**, three
performance cases deselected, zero skips, all configured static/security checks,
and fresh installed-wheel OKX verification. The log is
`/private/tmp/acceptance-scaffolding-second-local-ci.log`; the wheel/output is
`/private/tmp/alpha-research-wheel-smoke-8768tha6/`. Offline probes over 11 actual
model-workflow attempts exercised the service verifier's publication ordering,
corrupt-byte refusal, receipt interruption and restart dispatch with fake remote
transport. Local links passed across 51 Markdown documents, including component
and runbook paths outside `docs/`.

### Remaining maintenance cleanup

The founder authorized the remaining candidates on 2026-09-23. This pass removes
the untracked, byte-identical `clearml_publication 2.py` and redundant
`history-mr1-to-mr9a 2.md` (verified against the preserved Git version), and consolidates 84
generated-output copies across 23 SHA-256 groups in `logs/book-backtest/` and
`logs/saved-baseline/`. Those names now share read-only hard links: all original
paths and bytes remain, while duplicate file contents total **120,436,145 bytes
(114.9 MiB)**. This is logical deduplication, not a filesystem free-space measure.
The local receipt is `logs/retained-output-deduplication-2026-09-23.json`; all seven
completed manifests in the six affected stores reopened successfully afterward.

New `AttemptStore` artifacts share immutable content by digest within the same
store while preserving per-attempt names and existing readers. Book runs encode
each named artifact once and link exports to retained bytes on the same filesystem.
Old independent exports and report/checkpoint schemas remain readable under the
existing identity checks. Full reports still embed observations and account state
for reader compatibility. There is no automatic evidence pruning. Editing a
retained output requires a separate working copy, not changing a shared link.

Core experiment identity, temporal splits and attempt storage stay in
`research.experiments`. The existing study, report and integration implementations
move into the public `research.studies` owner. Maintained callers and examples use
that boundary; archived notebook bytes remain tied to their historical checkout.
The package split preserves the public-import governance rule without lazy export
machinery or duplicate record implementations. Core imports still load pandas and
NumPy through the foundational financial-unit codec, but no longer load ClearML,
Optuna or the study implementations.

The feature consumer falls from 725 to 470 lines; the consumer tree falls from
4,933 to 4,688 lines. It retains installed feature/model execution and fresh-process
reopening. Factor and model-outcome checks move to discovered domain tests;
existing window tests own delayed labels, reproducibility and failure/tamper
checks. Historical P1 work is archived, and the maintained live notebook selects
Bitfinex book capture or saved-recording replay with no network call by default.
The active roadmap separates current delivery from closed execution history while
preserving future MR acceptance contracts and historical links.

Three bounded implementation agents used `gpt-5.6-luna` at `max` for the import,
test and documentation work. The main agent owns content consolidation, integration
and final validation. No provider download or live-service acceptance was requested.

Validation on 2026-09-23: `env -u ALPHA_CLEARML_LOCAL_ENV TMPDIR=/private/tmp
make check` passed on CPython 3.14.7 / macOS arm64: **1,251 tests passed**, three
performance cases deselected, zero skips, all configured static/security/dependency
checks, and fresh installed-wheel OKX verification. The log is
`/private/tmp/post-mr9a-maintenance-check.log`; wheel evidence is
`/private/tmp/alpha-research-wheel-smoke-tn2glbhn/`. A final test-fixture simplification
also passed focused Ruff, strict mypy and all seven factor tests.

Local links passed across all 54 maintained Markdown files, including component
and example guides. All six notebook files parsed; the historical live notebook
matches the original bytes (SHA-256
`1a4c6fdd3abbdd140f74aef0e6f5cdd26a95b2d7a28d8189f86daf248cf304e5`), and every
original roadmap heading anchor remains available. The active notebook has 184
code lines. Its default path ran without creating an attempt; saved Bitfinex replay
produced 27 market states from the 32-position prefix with network access blocked.
The successful replay is retained at
`data/notebooks/research-live/73ba85df-0b19-4e16-b5ed-e97ee5967b9a/`.
No new capture or live-service acceptance was run.

An isolated installed core import loaded 853 modules, compared with the original
1,812-module observation; ClearML, Optuna and `research.studies` were absent.
This is an import-graph observation, not a timing benchmark. The deduplication
receipt was rechecked against all 84 paths, digests and read-only hard links;
the installed reader reopened all seven historical completed manifests afterward.

Pre-merge confirmation on 2026-09-23: the founder selected local CI as the merge
gate because GitHub Actions credits were exhausted. A fresh
`env -u ALPHA_CLEARML_LOCAL_ENV TMPDIR=/private/tmp make check` passed with
**1,251 tests passed**, three performance cases deselected, zero skips, all
configured static/security/dependency checks, and installed-wheel verification.
The log is `/private/tmp/post-mr9a-maintenance-premerge-ci.log`; wheel evidence is
`/private/tmp/alpha-research-wheel-smoke-1bebawdj/`. The merge uses `[skip ci]`;
repository CI configuration remains unchanged.

### Follow-up import and result-contract cleanup

The follow-up checkout defers ClearML, Optuna, DuckDB and Polars imports until
their operations run, preserving existing public imports. The producer, model
admission and diagnostic consumers share `research.results.FeatureStudyResult`;
`FeatureLabelPayload` remains an alias. Regression evidence preserves the existing
wire bytes, pending labels and model-specific row-order/digest checks. An invalid
custom reader returning no selected inputs now fails the shared result validator.
All 17 untracked ` 2` copies matched their pre-fix Git originals and were removed.

Validation on 2026-09-23: the frozen installed research, comparison/pipeline and
ingestion/economic/book workflow selection passed **88 tests**. After final
contract integration, feature, diagnostic and isolated-import regressions passed
**23 tests**, including the new compatibility case; neither selection skipped or
deselected tests. Ruff lint/format, strict mypy (57 files), the full engineering
checker, scoped Bandit and changed-guide links passed. Fresh wheel smoke verified
installed APIs, resources, historical snapshot reopening and the OKX book command;
local evidence is `/private/tmp/alpha-research-wheel-smoke-ktrsz79w/`.
The schema extraction used a `gpt-5.6-luna` subagent at `max`; the main agent
integrated both fixes and ran the final checks. Full pre-merge CI and live-service
acceptance were not rerun for this follow-up.

### Follow-up P3 cleanup

The founder authorized the remaining P3 findings on 2026-09-23. Documentation
sections now depend on the contract's needs; present sections still require
content and accurate parameter names. Overloads inherit implementation docs.
Repeated calendar/identifier boilerplate and overload suppressions were removed.
Alphalens uses the existing module stubs instead of six runtime typing protocols;
its imports remain deferred to evaluation.

The four large researcher/component guides were consolidated around current
journeys and owning packages. Study details now live under `research.studies`,
and deferred P1 reproduction has a separate guide. Including both new guides,
the combined text falls from **3,279 to 1,937 lines** (40.9%); historical anchors
and evidence remain available. Current callers link directly to the new owners.

New L2 reports use digest references to their adjacent configuration, EDA and
ordered checkpoints. `BookReport.read` verifies those bytes and also opens
standalone v1 reports. Copy the complete v2 bundle when relocating it; HTML
remains standalone. The maintained saved-data notebook produced a **2,230-byte**
report instead of the equivalent **4,806,968-byte** embedded encoding, with the
same 10,000 observations and two accounts. No historical artifact was rewritten.

Validation: **1,261 tests passed**, three performance tests deselected and zero
skips. Full-scope Ruff, strict mypy (347 files), native stubtest (1,562 modules),
engineering standards, Bandit, dependency admission and secret scanning passed;
all 56 Markdown documents passed local-link checks. Installed L2 regressions
cover portable bundles, missing/changed companions, standalone v1 reading and
byte-identical resumed results. An actual retained 10,000-message v1 report
also reopened. All six notebook code cells passed in a fresh kernel; the executed
copy is `examples/runs/orderbook-research/fd070526-c1fb-4a4e-af2f-e24fcc770ca6.ipynb`.
Fresh-wheel verification passed at `/private/tmp/alpha-research-wheel-smoke-cmyk12pu/`.
Three `gpt-5.6-luna` agents at `max` handled documentation policy, guide ownership
and Alphalens typing; the main agent implemented report references and validated
the integrated tree. No provider download or live-service acceptance was run.

Pre-merge confirmation on 2026-09-23: the founder selected the full local gate.
`env -u ALPHA_CLEARML_LOCAL_ENV TMPDIR=/private/tmp make check` passed with
**1,261 tests passed**, three performance tests deselected and zero skips, all
static/security checks, dependency audit and fresh-wheel verification. The log
is `/private/tmp/post-mr9a-p2-p3-local-ci.log`; installed-wheel evidence is
`/private/tmp/alpha-research-wheel-smoke-uj72znjm/`. The merge follows the existing
`[skip ci]` convention; repository CI configuration remains unchanged.

## Original findings

Priorities describe maintenance impact, not a request to reopen closed MRs.
All findings have high confidence and advisory disposition. The relevant invariant
is keeping reproducible domain behavior while separating current execution from
acceptance machinery; risk dimensions are specified below.

### P2 — Installed smoke has accumulated full acceptance workflows

The 28 Python files in `tests/integration/consumers/` total **7,381 lines**.
This is the review surface, not a deletion estimate. The clearest accumulation is
[feature_study.py](../../tests/integration/consumers/research/feature_study.py)
(859 lines): lines 853–855 add factor, model and window acceptance to the original
feature/label handoff. [wheel_layout.py](../../tests/integration/consumers/wheel_layout.py),
lines 146–161, runs five complete consumers, each under a 60-second deadline.
The feature and ingestion consumers also run through
[test_ingestion_workflow.py](../../tests/integration/test_ingestion_workflow.py),
so `make check` exercises them in both source tests and a clean installation.

Those two environments prove different things, but each currently repeats the
whole scenario. The [historical MR9 record](README.md#runtime-feature-parity)
already records the feature consumer timing out during font-cache construction.
Every added acceptance scenario broadens this unrelated package-installation gate.
Risk: reliability/operability and CI capacity.

Consolidate by purpose: keep a bounded outside-checkout installation/reopen smoke;
give model, diagnostics, publication and recovery behavior focused domain checks.
Preserve required CI coverage and true process-death tests when moving scenarios.
Do not delete all consumers merely because their original MR closed.

### P2 — Basic experiment records eagerly load integration dependencies

[research.experiments exports](../../src/research/experiments/__init__.py),
lines 4–46, import comparison, pipeline and tracking implementations alongside
`AttemptStore` and `Fingerprint`. Their imports load ClearML and Optuna even for
callers that only need local records. A fresh installed-process probe importing
only `AttemptStore` loaded **1,812 modules**, including ClearML, Optuna, pandas and
NumPy; the single observed import took **1.819 seconds**. This is a diagnostic
observation, not a controlled performance benchmark.

The trigger is any import through this package, including ordinary local backtest
work. Risk: startup capacity and coupling of local record access to integration
installation/import health. Give the core record/store API a lightweight boundary
and load integrations at their actual consumers, preserving or deliberately
migrating supported public imports. Merely changing to a submodule import is
insufficient while the package initializer still performs these imports.

### P2 — Saved-book results repeatedly store the same large payloads

[run_books](../../src/applications/backtest/books.py), lines 94–95 and 115–117,
writes both exports and attempt artifacts for EDA and checkpoints. Lines 126–152
also embed those values into the report, retain that report and export it again.
These are useful output roles, but the current implementation materializes full
copies and repeats serialization instead of sharing immutable content.

The local `logs/` tree occupies about **429 MiB**. A SHA-256 inventory restricted
to JSON, HTML and `artifact-*` files of at least 1 KiB in `logs/book-backtest/` and
`logs/saved-baseline/` found **120,436,145 bytes (114.9 MiB)** of byte-identical
copies beyond one file per distinct payload. One 3,186,388-byte EDA payload appears
18 times. This includes repeat/restart evidence across attempts: it is logical
duplication, not an estimate of safely deletable or physically reclaimable space.
Risk: storage capacity and increasingly expensive retention/reopen workflows.

For new runs, serialize once, retain canonical immutable bytes and make exports
explicit or derived. Consider shared content only within the existing store if
the measured need justifies it; retain separate attempt histories and manifests.
Any later schema change needs old-report/checkpoint reopening compatibility.
Verify durable artifact retrieval before pruning local copies; this review did
not independently verify remote upload receipts or retention coverage.

### P3 — ClearML acceptance setup and verification are duplicated

The credential-file parsing and loopback endpoint setup are repeated in
[feature_study.py](../../tests/integration/consumers/research/feature_study.py)
at line 208, [economic_workflow.py](../../tests/integration/consumers/backtest/economic_workflow.py)
at line 526, and [offline_features.py](../../tests/integration/consumers/research/offline_features.py)
at line 155. They have already diverged: the feature consumer does not skip blank
or comment lines, while the other two do. The same credential file can therefore
work for one service acceptance path and fail in another.

Remote artifact download/hash checks are also repeated at feature lines 522–538
and 757–782, economic lines 310–323 and 636–656, and offline lines 269–288.
Risk: reliability/operability and maintenance drift. Consolidate common service
setup, receipt reconciliation and artifact verification in a bounded service
acceptance consumer; keep domain-specific expectations independent. Preserve
outside-checkout isolation rather than adding runtime imports of test helpers.

### P3 — The active live notebook contains a large deferred P1 investigation

[research-foundations-live.ipynb](../../examples/research-foundations-live.ipynb)
contains **1,197 code lines**, of which **827** belong to its ten P1 evidence cells
(`p1-inputs` through `p1-handoff`, starting near JSON line 242). These include
retention, provider-document assembly, source qualification and refusal evidence.
The maintained path also has a separate
[source_acceptance.py](../../tests/integration/consumers/backtest/source_acceptance.py)
program and several P1/provider records. P1 is deferred and the new source policy
excludes its Binance/Tardis inputs.

Risk: operability and maintenance of an obsolete default research journey.
Archive the P1-specific notebook journey with its tested identity and record;
make the maintained notebook focus on supported OKX/Bitfinex workflows. Retain
source-admission contracts, compatibility readers and useful negative regressions.
The synthetic P1 engineering consumer currently participates in wheel smoke, so
it is not dead code and cannot simply be removed with the notebook cells.

### P3 — The roadmap doubles as a large historical execution log

Before this review's small status edits, [the roadmap](README.md) had **1,898
lines / 140,886 bytes**. The MR7 section alone runs from lines 781–1234, with
successive completion attempts, validation counts, tool decisions and local
evidence locations. [The market-data command reference](../../src/market_data/README.md)
adds another **1,556 lines**, and the frozen P1 record has **555 lines**.
Length alone is not a defect: the concrete problem is mixing current delivery
status with historical acceptance narratives. It left MR9 marked open and MR9A
awaiting merge in current guidance after the founder confirmed closure.

Risk: operability and incorrect future planning. Keep the active roadmap focused
on current capabilities, limits and MRs 10 onward; move completed acceptance
narratives to historical records with preserved links, anchors and tested
identities. The accompanying edit corrects current status and source policy only.

## Cleanup order and preservation boundary

1. Separate historical roadmap/P1 material from current researcher entrypoints.
2. Consolidate service acceptance setup and split the oversized smoke scenarios,
   retaining domain assertions and installed-boundary coverage.
3. Reduce eager integration imports and repeated artifact materialization with
   focused compatibility/reopen checks.
4. Prune local generated outputs only after verifying retained evidence retrieval.

Keep the shared `AttemptStore`, `ResultManifest`, publication retry/receipt logic,
source admission, exact accounting, causal checks and checkpoint recovery. They
have ongoing runtime consumers; successful MR evidence upload does not retire
them. Large numerical/identity/calendar modules and tests are not classified as
bloat merely from their line counts. Existing provider adapters and fixtures
remain historical compatibility surfaces, not the source template for new MRs.

Review profile: research and platform architecture, risk tier 2, local/offline
scope. Validation comprised tracked-file inventories, caller/import inspection,
the isolated installed import probe and local duplicate-payload hashing. No
live service, provider download, research rerun or runtime suite was executed.
Local-link validation passed for all 38 documentation files, and
`git diff --check` passed. No package inputs or runtime contracts change in this
assessment.
