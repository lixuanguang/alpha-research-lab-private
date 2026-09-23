# Post-MR9A maintenance record

Owner: repository founder. Status: the reviewed P2/P3 findings are resolved,
merged through `31fcc84` on 2026-09-23. The original assessment used `aa6d6f0`;
each cleanup pass below retains its own changes, validation and evidence scope.
This is a completion record, not an active backlog. New work belongs in the
[active roadmap](README.md). Historical artifact bytes remain unchanged.

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

### Documentation follow-up

The 2026-09-23 documentation cleanup removes the two detailed roadmap files and
their duplicated narratives: completion status and planned dependencies now fit
in the 112-line master roadmap. Git retains cited historical evidence. Withdrawn
outreach drafts and duplicate release guidance are removed; stale API/status
instructions are corrected. Links pass across 52 Markdown documents, nine cited
Git targets/anchors resolve, and secret scanning passes. The offline wheel build
preserves the updated README metadata and all 194 Python modules match unchanged
source. Runtime tests and research notebooks were not rerun for these prose edits.

## Original findings

All six original findings and the follow-up P2/P3 items are closed. The
[detailed assessment at the merge revision](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/post-mr9a-maintenance-review.md#original-findings)
retains the original line references, measurements and recommendations. Those
references describe the assessed checkout, not the current implementation.

| Finding | Resolution and retained evidence |
| --- | --- |
| Full acceptance workflows duplicated in wheel smoke | [Bounded installation smoke and maintained domain regressions](#acceptance-scaffolding-cleanup) |
| Core records eagerly load integration SDKs | [Separate owners and deferred operational imports](#follow-up-import-and-result-contract-cleanup) |
| Saved-book payloads are repeatedly materialized | [Content sharing](#remaining-maintenance-cleanup) and [v2 report references with v1 reading](#follow-up-p3-cleanup) |
| ClearML service setup and verification are repeated | [One explicit service verifier](#second-cleanup-pass) |
| The maintained live notebook contains deferred P1 work | [Preserved P1 notebook and current Bitfinex journey](#remaining-maintenance-cleanup) |
| The roadmap mixes active work and closed delivery logs | [Concise master roadmap with completion status and remaining work](README.md) |

The shared attempt store, result manifests, source admission, exact accounting,
causal checks and recovery remain supported runtime contracts. MR closure does
not retire them. Retained provider evidence and historical failures continue to
explain their original acceptance limits.
