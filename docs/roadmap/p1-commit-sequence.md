# P1 incremental commit and push plan

Owner: repository founder. Status: the full source workspace is
`/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private` on
`codex/implementation-plan` at `de932733e470c1991aa421d0369693e31adec06c`.
The reusable `dev` staging branch is
`/private/tmp/p1-assembly-20260908/dev` at `b2e8cf1` and holds only the next
independently valid small MR candidate: Currency, serialization, provenance,
reference catalog, and the market-data event/decoder foundation. This candidate
is locally validated and staged for publication; publication remains pending. Commit
01's authorization and the historical Currency records below retain their
original identities and outcomes. The
[publication record](#commit-01-publication-authorization) records this authorization.
The historical [commit 01 record](#commit-01-preparation-record) identifies its
intermediate-checkout validation. Originally assessed on 2026-09-08 against the working tree on `codex/implementation-plan`,
based on `c035f8870a980c4a125974b0d6ea573b63f6c07c`.

The requested review budget is approximately **300 changed implementation lines
per commit**, with **test changes reported separately** and related documentation
included. Use additions plus deletions in implementation `.py` files, including
comments/docstrings, as the conservative implementation measure. Report authored
configuration and generated lockfile changes separately as well. The captured source tree
had 5,486 new runtime Python lines and 2,628 new test lines, plus small changes to
existing runtime/governance code. Whole-file staging would hide useful boundaries.

Follow the existing [engineering guide](../coding_standards/README.md),
[development workflow](../governance/workflow.md), and
[platform roadmap](README.md). This is an assembly/review plan for the current
implementation; it does not propose new strategy behavior, weaken validation or
recreate the earlier hardcoded implementation.

## Approach and preservation

Treat the `codex/implementation-plan` checkout as the full source workspace and
leave it intact. Use this `dev` checkout on `dev` as a reusable staging branch
containing only the next independently valid small MR candidate. Before
reconstructing hunks, retain a local snapshot of all changed tracked and
untracked source, tests, configuration and documentation, with a file/hash
inventory. A patch of tracked files alone misses most of this work. Keep ignored
market data, wheels, environments and bulk reports out of the commits; preserve
them separately under their current rights.

Build only the next candidate in the DEV staging checkout. Its imports, tests
and documentation must work using that checkout alone. Testing the full source
workspace after staging a subset would let later uncommitted code mask missing
dependencies. Start a fresh development environment in the DEV staging checkout;
the original `.venv` contains extra legacy Python copies and is not clean-install
proof. Do not copy it or silently remove those files.

The table retains the original **29-row proposal**, with two expected size
exceptions. Figures
are planning estimates, not measured staged diffs or claims that intermediate
states pass. Imports, exports, blank lines and test-fixture changes must be counted
when each candidate is assembled. The final runtime/config/lock files should be
byte-identical to the captured completed implementation. Retain every original
test/assertion and historical result; any useful additional boundary tests should
be identified separately in the final diff.

## Commit sequence

Every row includes focused tests for the behavior it introduces, relevant source
checks, and the indicated documentation. Test figures estimate changed lines;
shared fixture/import adjustments can change the distribution across commits.
They are not proposed limits or numbers of test cases.

Paths below are repository-relative. They are rendered as code because many do
not exist in the early proposed commits. Introduce links to them only once their
targets exist in that candidate tree.

The selected current candidate spans rows 02, 03, 04, 05 and 08–11: Currency,
serialization, provenance, reference catalog, and the generic/Binance market-data
event and decoder boundary. The user-requested inclusion is an explicit
exception to the approximate 300-line review budget; the primary audit will
measure the final assembled diff. Rows 06–07 and 12 onward remain later planned
boundaries. This scope statement makes no expanded validation claim.

The foundation candidate's provider/venue boundary keeps `data/decoders.py`
neutral with `DecodeContext` and the `PayloadDecoder` protocol, places Tardis
framing, capture parsing, and blank-line handling in
`data/providers/tardis/decoder.py`, composes the Binance provider in
`data/providers/tardis/binance.py`, and keeps Binance combined-stream payload
interpretation in `data/venues/binance/payloads.py`. This candidate does not add
acquisition, storage, book, replay, or live-feed behavior. Acceptance is runtime
and source-byte, timestamp, source-order, and event-identity parity through the
foundation decoder tests and affected source/link checks. Reversal is a bounded
patch restoring the prior defining imports while retaining the compatibility
facades; the hosted CI lane remains required.

The market-data module split supersedes the original monolithic `data/models.py`
layout in rows 08–11. Assemble shared records in `data/events.py`, the neutral
decoder context/protocol in `data/decoders.py`, Tardis framing in
`data/providers/tardis/decoder.py`, Binance provider composition in
`data/providers/tardis/binance.py`, and concrete events, wire codecs, and payload
mapping in `data/venues/binance/`. Keep `data/models.py` and
`data/venues/binance/decoder.py` as explicit compatibility exports. Those rows
retain their behavioral acceptance boundaries; remeasure their implementation/
test estimates and dependency order against the new files when assembling them.
Preserve complete validation and decoder methods instead of splitting them merely
to retain an earlier line estimate. For this candidate, `data/__init__.py` exports
the event, codec, and line-decoder surface only; acquisition, storage, book,
accounting, strategy, and replay consumers remain later planned paths.

Current test paths mirror the source boundary: provenance is under
`tests/unit/core/`, neutral decoder-context tests under `tests/unit/data/`,
provider framing and Binance composition tests under
`tests/unit/data/providers/tardis/`, and Binance payload/model/event tests under
`tests/unit/data/venues/binance/`. Reference-catalog and serialization tests
remain `tests/unit/test_reference_data.py` and `tests/unit/test_serialization.py`.
Old root-level paths and commands in retained historical evidence remain
historical; active plan references use this split.

| # | Suggested commit and complete boundary | Implementation lines | Test lines, separately | Related documentation and focused proof |
| --- | --- | ---: | ---: | --- |
| 01 | `build: admit locked msgspec runtime dependency` — `pyproject.toml`, `uv.lock`, dependency admission policy and package-count expectation, kept together | 0 Python; 1 project-config line, plus generated lock/policy diff | 2 | Serialization-choice portions of engineering/architecture guides; dependency admission, installed package metadata and locked dependency checks. Retain QuantLib restriction. |
| 02 | `feat(units): make Currency configuration-driven` — frozen code/quantum values, packaged default definitions, typed code lookup, and generalized foundation tests | 175 changed Python lines; 13 JSON lines and 1 cache-key line separately | 307, including 109 migrated C03 test lines | C03 currency/rounding paragraphs; generalized Currency identity and rounding tests. |
| 03 | `feat(codec): preserve exact domain values with msgspec` — complete `serialization.py` | 187 | About 38 | Codec/precision contract; money round trips and malformed-wire tests. Withhold the `ResearchParameters` import and its test until 06. |
| 04 | `feat(core): add immutable event provenance` — complete `core/events.py` and core exports | 247 | 272 | Provenance/availability sections of `docs/data/point-in-time-semantics.md`; `tests/unit/core/test_event_provenance.py`. |
| 05 | `feat(reference): add authored spot catalog snapshots` — complete `reference_data.py`, plus `configs/reference/binance-spot.json` | 214; JSON separately | About 40–70 | Metadata assumptions, units, coverage and identity; `tests/unit/test_reference_data.py`, with future loader imports withheld. |
| 06 | `feat(research): define typed parameters and instrument roles` — `ResearchParameters`, `ResearchConfig`, required imports, docstring-only research package initializer | About 150–180 | About 20–60 | Parameter/role identity contract; strict parameter decoding, incompatible roles and deterministic config identity. Add the deferred serialization test. |
| 07 | `feat(config): resolve authored runs from relative catalogs` — complete `research/configuration.py`, plus `configs/research/p1-binance.json` | 273; JSON separately | About 65–95 remaining | Research configuration editing and resolution instructions; complete configuration tests, including path resolution, interval coverage and unknown fields. |
| 08 | `feat(data): define strict depth event records` — shared event validators/base records, `DepthSnapshot`, `DepthUpdate`, matching package exports | About 240–260 | About 80–130 | Canonical depth identity/time/level rules; direct constructor and revalidation tests with event fixtures. |
| 09 | `feat(data): complete canonical events and strict codecs` — `Trade`, `Disconnect`, closed union, event validation/encoding/decoding | About 170–190 | About 50–90 | Trade/disconnect/proxy/schema contract; invalid event bases, unknown fields, exact round trips and immutable-copy boundaries. |
| 10 | `feat(data): define neutral decoding and typed Binance payloads` — `DecodeContext`, `PayloadDecoder`, Binance combined-stream codecs, and `BinancePayloadDecoder` | About 180–210 | About 40–70 | Source timestamp precision and wire boundary; neutral context, malformed payloads, exact decimal/level parsing, and direct Binance payload tests. No acquisition API claimed yet. |
| 11 | `feat(data): compose Tardis framing with Binance decoding` — provider capture/blank-line boundary, `BinanceTardisDecoder`, `decode_tardis_line`, mapping resolution, and compatibility exports | About 250–280 | About 90–130 | Runtime and source-byte/timestamp/order/identity parity; provider framing/composition tests and `tests/unit/data/venues/binance/test_binance_decoder.py`. Storage remains a later planned boundary. |
| 12 | `feat(book): add validated immutable book tops` — `BookTop` and its helpers | About 105 | About 25–50 | Top-of-book units/time/shape; direct float, crossed/invalid level and timestamp checks. |
| 13 | `feat(book): reconstruct bounded Binance depth` — intact `BinanceBook` state machine, error/sequence helpers and exports | **About 370–390; exception** | Remaining book cases; final file 405 | Book buffering, bridge/gap/duplicate/reset and snapshot-coverage rules; complete `tests/unit/data/venues/binance/test_binance_orderbook.py`. |
| 14 | `feat(tardis): define transport and bounded request scope` — HTTP types/transport, constants, hashing/write/URL/symbol/instrument helpers | About 250–285 | About 40–80 | Source, rights and request-scope sections; bounded URL/filter validation and mocked transport behavior. No real HTTP needed. |
| 15 | `feat(tardis): define immutable acquisition manifests` — `RawManifest`, `DatasetManifest`, checkpoint record | About 170–190 | About 50–90 | Manifest schema, range, source rights and digest rules; direct malformed-range/lineage/schema and deterministic identity cases. |
| 16 | `feat(tardis): acquire and resume raw minute objects` — complete fetch-only `TardisSampleStore`, checkpoint/object verification, retry policy and package exports | About 285–300 | About 90–140 | Raw-storage/resume Python API; existing checkpoint/resume/retry cases with injected transport. Defer publication-only methods as detailed below. |
| 17 | `feat(tardis): publish validated canonical datasets` — `publish`, source-line/selection handling, canonical identity and book-quality helpers | About 260–295 | About 40–80 | Atomic canonical publication and rejection; malformed/conflicting data and incomplete publication tests that need no loader. |
| 18 | `feat(tardis): verify persisted datasets and raw lineage` — `load_dataset`, strict digest extraction and final exports | About 120–140 | About 40–80 | Readback, tamper detection and recovery limits; remaining publish/load/interruption tests. Run the complete affected data/book/provenance selection. |
| 19 | `feat(accounting): define exact fill and valuation records` — `SpotFill`, `SpotSummary`, revalidation helpers and record-only exports | About 185–200 | About 50–90 | Record units and NAV identities; direct constructor/codec/reconciliation rejection cases. Ledger consumers remain absent. |
| 20 | `feat(accounting): apply reconciled spot ledger transitions` — intact `SpotLedger`, fee helpers and final exports | About 290–300 | Remaining ledger cases; final existing file 373 | Cash/inventory/fee/valuation equations and limits; full accounting tests with independent buy/sell/no-trade goldens. |
| 21 | `feat(strategy): define quote context and configuration` — `StrategyContext`, `QuoteConfig`, their validators and partial exports | About 200–230 | About 40–80 | Strategy identity, sizing and input bounds; direct valid/invalid context/config cases. |
| 22 | `feat(strategy): define market observations and quote intents` — `QuoteMarket`, `QuoteIntent`, needed validators and exports | About 140–170 | About 70–120 | Market/intent schemas, time and dimension rules; direct intent dimension/positivity, copied-record and codec cases. |
| 23 | `feat(strategy): implement exact reference-adjusted quotes` — complete `InventoryMarketMaker`, remaining calculation/freshness/affordability helpers and final exports | About 250–280 | Remaining kernel cases; final existing file 425 | Formula, tick rounding, fee-aware sizing, freshness and missing-reference behavior; complete market-making tests. |
| 24 | `feat(replay): define results and isolated variant state` — variant/result records, resting/variant state, unit conversions and `_states` ledger/kernel construction | About 150–185 | About 40–80 | Result units and state isolation; direct result validation and independent variant construction. Bring only required imports forward. |
| 25 | `feat(replay): enforce causal arrival and trade-through fills` — event loop, quote advancement, trade fills and market-input assembly | About 260–295 | 359 | Causal timing/fill/final-mark rules; all replay tests, including future perturbation, partial fills, stale reference and asset isolation. |
| 26 | `feat(runs): retain immutable reports and every started attempt` — complete `research/runner.py` | **321; exception** | About 140 | Run/report/trial identity, preflight/failure and partial-directory limits; repeat/conflict/failure/changed-config runner tests. Withhold CLI-only imports/cases. |
| 27 | `feat(cli): expose configured fetch and replay commands` — `research/__main__.py` and incremental P1 installed-wheel imports/checks | 82 + 17 = 99 | About 120 remaining | Current fetch/run examples and package usage; synthetic CLI asset-switch test, package-definition checks and clean installed-wheel smoke. |
| 28 | `fix(docs): discover root and component Markdown` — canonical discovery method and CLI wiring | 47 | 108 | Documentation standard/tooling scope; architecture-governance tests plus installed CLI positive and broken-link fixtures. |
| 29 | `docs(p1): reconcile navigation and preserved validation history` — remaining root/component navigation, workflow/research extraction, project/strategy/evidence records and owning plans | 0 | 0 | Most domain prose has arrived with its code; now restore the complete cross-links and tested/planned labels, preserve historical anchors/results, and record exact commit/checkpoint validation. Final link/semantic/package checks as affected. |

### Why the two larger commits remain intact

Commit 13 retains the book's coupled snapshot/bootstrap, buffered-update,
sequence-gap, coverage and atomic-state rules. `BookTop` is already separate;
further splitting the mutable book would either expose incomplete behavior or
require source refactoring just to shape history.

Commit 26 keeps the runner's identity, started/terminal attempt records, immutable
writes and replay/report error boundary together. Its 321 implementation lines
are only slightly above the target; the CLI and installed import additions are
already separate. This avoids an identity-only commit with little existing
consumer coverage merely to save 21 lines.

The other figures require hunk-level assembly, not whole-file `git add`. If an
actual dependency closure takes a slice above the target, report its measured
size and combine the smallest related boundary. Do not add placeholder methods,
remove mandatory validation, introduce compatibility wrappers or split financial
invariants solely to satisfy a line count.

## Required staging details

- `data/__init__.py`, `accounting/__init__.py` and `strategies/__init__.py` currently
  import their completed packages eagerly. Start with exports for the records
  that exist and add each concrete service when it lands. These are real narrower
  APIs, not stubs. Restore the captured final exports when the component completes.
- `research/__init__.py` is already docstring-only. For 06, `replay.py` imports only
  its parameter/config dependencies. Bring ledger, strategy, book and event imports
  with 24/25. This lets typed asset configuration arrive before ingestion/replay.
- `test_serialization.py` currently imports `ResearchParameters` at module scope;
  its money tests can land in 03 only after withholding that future import/case.
  Catalog-only tests similarly withhold `load_run_spec` until 07.
- Neutral decoder tests are staged in `tests/unit/data/test_decoders.py`, provider
  framing and composition tests in `tests/unit/data/providers/tardis/`, and direct
  Binance payload tests in `tests/unit/data/venues/binance/test_binance_decoder.py`.
  Storage tests remain a later planned boundary; do not let pytest collection rely
  on a missing future package export or on compatibility facades as defining
  modules.
- For 10, source-time/wire tests exercise real conversion/validation semantics,
  not class existence. Directly test conservative rounding and invalid wire values;
  the complete decoded-event cases still land with 11. Small test adaptations can
  be worthwhile to prove an early boundary; no new test framework is needed.
- The accounting/strategy record steps use direct constructor and strict codec
  tests. Current ledger/kernel-based examples belong with 20/23. Preserve their
  original assertions when completing the final test files.
- For 16, defer `_validate_manifest_selection` and `_source_lines` until 17;
  together they account for about 25 publication-only lines. Include fetch's
  actual checkpoint/raw/retry dependencies and package exports in the same commit.
- For 17, bring every helper called by `publish` even though some currently appear
  after `load_dataset` in the file. In 18, insert `load_dataset` before those
  top-level helpers. Definition order must preserve complete callable behavior.
- Keep the runner unit tests before CLI integration by withholding their `main`
  import and CLI source-body test helper until 27. Never add all current wheel-smoke
  imports before the corresponding packages exist.
- Carry related doc sections with the behavior they describe. Until later code or
  pages exist, label them planned and render proposed paths as code. Do not copy
  completed P1 commands/status/navigation wholesale into an early partial commit.
  Commit 29 restores the captured complete documentation and preserves all original
  evidence; new per-commit proof is appended with its own identities.

## Local validation for every commit

Validate in the clean assembly checkout containing only that candidate and its
predecessors. For each row, run the smallest relevant selection of behavior tests,
Ruff lint/format and strict mypy on changed Python files; run the retained source
standards checker over those files and Bandit when implementation/tooling changes
make it applicable. Check related documentation links and meaning. Keep commands
and output attached to that exact candidate commit, including failures and
skips/deselections. A previous final-tree pass is not proof of these earlier trees.

The supported command forms include:

```sh
uv run --frozen --no-editable pytest -q <affected-test-paths-or-node-ids>
uv run --frozen ruff check <changed-python-files>
uv run --frozen ruff format --check <changed-python-files>
uv run --frozen mypy --strict <changed-python-files>
uv run --frozen alpha-governance-architecture
git diff --cached --check
git diff --cached --numstat
```

These are templates: replace the angle-bracket placeholders. Tests marked
`integration`/`performance` need explicit selection when affected; ordinary
pytest defaults exclude them. Do not claim a selected file ran all its marked
cases without checking collection/results. Follow the guide's global-static-scope
rule if global tooling configuration changes; this plan does not change that config.

Use additional checks only at the boundary that needs them:

- 01: locked dependency/policy/package proof, including current source/native
  admission and applicable audit. A skipped native verification because Cosign
  is absent is not an admission pass. This step preserves the existing release block.
- 18: saved synthetic raw → canonical → readback, mutation and interruption
  behavior. No new market-data download is needed for commit assembly.
- 25: complete affected causal replay/strategy/accounting regressions. No new
  hypothesis, parameter search or holdout evaluation.
- 27: clean wheel installation outside the checkout, public CLI/import checks
  and synthetic configured acquisition/replay. A build or README change needs
  the corresponding package proof; obsolete smoke imports must not be present.
- 28: invoke the installed documentation executable against valid and broken
  root/component/PR fixtures, beyond checking only the Python service.
- 29: final local links, semantic/anchor/evidence comparison and any package
  proof affected by packaged README edits. Reuse the earlier domain evidence
  only after checking that source/config/lock/data identities still match.

Do not repeat the complete local suite at every micro-commit. Do retain the
required hosted lane. End-of-assembly acceptance is a clean installation and
matching captured runtime/config/lock content, all original behavior tests retained,
current affected proof, preserved older research results, and truthful completion
of the owning plan. Any actual runtime change discovered during assembly is a
separate fix with its own relevant proof, not concealed inside staging.

## Push and hosted validation checkpoints

The inspected `.github/workflows/ci.yml` runs on pushes to `main` and PR events
whose base is `main`. **Pushing an ordinary feature branch alone does not trigger
this workflow.** No remote settings beyond that checked-in workflow were inspected.

Open a draft PR from the assembly branch to `main` when beginning remote
validation. Keep it unmerged while assembling. A stacked PR targeting another
feature branch would not receive this workflow under the current filters.
Changing those filters is unnecessary for the proposed sequence.

The eight grouped checkpoints below are retained as the original proposal, not
the selected current workflow. The selected workflow uses one small MR candidate
at a time: each candidate first passes its local affected checks, then its
publication and hosted gate before the next candidate is restaged from the full
source workspace.

| Checkpoint | Commits | What the user can validate |
| --- | --- | --- |
| A | 01–07 | Locked dependency, exact currency/codecs, provenance and editable typed asset configuration |
| B | 08–11 | Strict canonical events, neutral payload boundary, and Tardis/Binance provider composition |
| C | 12–13 | Bounded book reconstruction, gaps and coverage rejection |
| D | 14–18 | Complete resumable raw acquisition and verified canonical readback |
| E | 19–23 | Exact ledger and deterministic configuration-driven quote kernel |
| F | 24–25 | Causal three-variant replay and reconciled net results |
| G | 26–27 | Callable trial/report persistence and installed configured CLI |
| H | 28–29 | Complete documentation, maintained navigation and recorded evidence |

This gives eight full hosted checkpoints instead of repeating the full hosted
suite 29 times. The checkpoint tip's merged result receives hosted proof; earlier
commits in that group have their local affected proof only. If full hosted proof
is wanted for every intermediate commit, push one commit at a time and wait for
that result before pushing the next. Do not describe a later successful CI run
as evidence for all earlier commits.

Keep published commits append-only. After publication, fix a defect with a small
follow-up commit and retain the failed check; avoid force-pushing away reviewed
states. The PR's total diff will grow, but each commit remains reviewable. If small
PR diffs are also required, use sequential PRs merged into `main` after each
accepted checkpoint rather than a feature-based stacked chain under the current
workflow. Creating/pushing/merging those branches and PRs is execution of this
plan, not something performed by this planning task.

## Evidence and final limits

The retained final runtime source identity is
`cc89efcf02991c56e384515316bf5917e21bc142f0894d54c9eeffa4504508e8` and lock identity is
`6841091812d681df9b49af3741940224d358d6643512e2f6418404619323db46`.
These are final-state targets for content comparison, not expected hashes for
each partial commit. Keep the existing local raw objects, reports, rejected
ten-minute corpus, negative comparison results and earlier wheel identities.
A new Git commit or documentation-bearing wheel does not rewrite old run evidence.

Per-commit validation records should identify commit, implementation/test diff
counts, command, result and remaining gate. Do not relabel the original 91-test
or later 18-test results as fresh checks of the reconstructed history. A new run
with a new caller-supplied source commit may have a different run ID even when
its economic source is unchanged; preserve both identities when executing one.

The original development environment's extra files, local-only artifact retention,
missing independent backup/restore, empirical research limits, future runtime
capabilities and release blockers remain as documented. Commit organization
resolves review and validation size; it does not resolve those runtime or
operational dependencies.


## Commit 01 preparation record

Owner: repository founder. Status at preparation: **prepared and staged; awaiting authorization**.
Prepared on 2026-09-08 for `build: admit locked msgspec runtime dependency`.
Only commit 01 is prepared; commits 02–29 require separate authorization.

### Candidate and preservation

The assembly checkout is `/private/tmp/p1-assembly-20260908/worktree`, branch
`codex/p1-incremental`, based on `c035f8870a980c4a125974b0d6ea573b63f6c07c`.
It adds the exact `msgspec==0.21.1` dependency, lock artifacts, native/license
admission and package-count expectation. The engineering and architecture
serialization guidance labels the P1 consumers as planned. There are no runtime
Python changes, new codecs, exports, fixtures or changes to financial, temporal
or research-configuration behavior. Reversal is removal of this dependency,
lock/policy and its related test/docs together before a later consumer uses it.

The original `codex/implementation-plan` checkout is unchanged. Its 68 changed
tracked/untracked files are retained with an inventory in the local-only
`/private/tmp/p1-assembly-20260908/source-snapshot.tar` and `inventory.json`.
The archive SHA-256 is
`bf0e97b24a2ed2d2ce823ceee4ef242f41a7bba0db2858375fc529fe037cf312`.
Tracked/index patches and starting refs/status are retained beside the archive.
Ignored data, environments and historical reports remain in their original
locations. This local archive is not an independent backup.

The candidate manifest, lock, policy and changed test exactly match the captured
source bytes. Runtime/governance source and the packaged `docs/README.md` retain
the base revision bytes. The lock SHA-256 is
`6841091812d681df9b49af3741940224d358d6643512e2f6418404619323db46`.
Final staged file identities and the staged patch are retained locally as
`/private/tmp/p1-assembly-20260908/staged-inventory.json` and `staged.patch`.
The documentation diff includes this previously untracked sequence, preserving
its later proposed rows and original evidence instead of preparing those rows.

Measured review size (additions + deletions): implementation **0**; tests **2**;
authored configuration **5**; generated lockfile **18**; documentation **425**.
There are seven staged files; no implementation size exception is needed.

### Validation of this intermediate checkout

All commands below ran from the assembly root, using a newly created `.venv`,
Python 3.12.14, uv 0.12.7 and non-editable installed project/governance packages.
The environment was not copied from the original checkout. The initial
`uv run --frozen --no-editable python --version` built both distributions and
installed 73 packages. Subsequent `--no-sync` checks used these same installed
bytes; the only later edits were to unpackaged Markdown.

For native-dependent commands, the exact prefix was
`PATH=/private/tmp/p1-assembly-20260908/bin:$PATH`. That directory exposes the
existing Cosign 3.1.3 binary at `/private/tmp/step6_final/cosign-darwin-arm64`,
SHA-256 `5cf948c2f4dfe59687bdd0b8523709067383e03982cc543475c8a7dc70e92a76`.
No native verification was skipped.

| Command (native PATH prefix where indicated) | Actual result |
| --- | --- |
| `uv lock --check` | Exit 0; resolved 74 packages, including the two local distributions. |
| `uv run --frozen --no-editable --no-sync pytest -q -ra tests/engineering/test_dependency_admission.py tests/engineering/test_package_definition.py` (native PATH) | Exit 0; **25 passed in 2.12s**, 0 skipped, 0 deselected. Covers lock/native evidence, invalid identities/audit reports, QuantLib release rejection, installed metadata and governance separation. |
| `uv run --frozen --no-editable --no-sync alpha-governance-dependencies audit` (native PATH) | Exit 0; current-date repository/source/native validation followed by exact locked-graph pip-audit; no unresolved vulnerabilities or coverage gaps. |
| `uv run --frozen --no-editable --no-sync ruff check tests/engineering/test_dependency_admission.py` | Exit 0; all checks passed. |
| `uv run --frozen --no-editable --no-sync ruff format --check tests/engineering/test_dependency_admission.py` | Exit 0; 1 file already formatted. |
| `uv run --frozen --no-editable --no-sync mypy --strict tests/engineering/test_dependency_admission.py` | Exit 0; no issues in 1 source file. |
| Source standards command below | Exit 0; `tests/engineering` and retained tooling configuration passed. |
| `uv run --frozen --no-editable python -m alpha_research_governance.wheel_smoke` | Exit 0; built this candidate, installed 16 hash-checked runtime dependencies including msgspec plus the runtime wheel outside the checkout, checked all 17 packages, and passed isolated C01/C02/C03 imports with governance absent. The standard smoke command removed its temporary wheel/environment afterwards. |
| `uv run --frozen --no-editable --no-sync alpha-governance-architecture` | Exit 0; 19 Markdown documents passed. The current checker discovers `docs/**/*.md`; all changed Markdown is inside that scope and uses supported inline links. |
| `git diff --cached --check` and staged-content comparison | Exit 0; whitespace clean, no unstaged tracked/untracked candidate files, and every staged file equals its reviewed working file. |

The retained source checker accepts directory roots. Its exact focused invocation
was:

```sh
uv run --frozen --no-editable --no-sync python - <<'CHECK'
from pathlib import Path
from alpha_research_governance.engineering_standards import source_tree_findings, tooling_configuration_findings
root=Path.cwd()
findings=source_tree_findings(root, source_roots=('tests/engineering',)) + tooling_configuration_findings(root)
assert not findings, '\n'.join(findings)
print('Source standards passed for tests/engineering; retained tooling configuration passed.')
CHECK
```

An additional isolated-interpreter check of the fresh development installation
confirmed msgspec version 0.21.1, installed BSD-3-Clause metadata, a native JSON
round trip retaining the exact string `0.00000001`, and runtime/governance imports
inside the fresh environment. Its exact command and result are retained in the
local `validation.json`; this is dependency smoke evidence, not a P1 codec test.

Initial test, lock and source-check invocations failed before checks ran because
the sandbox denied access to the uv cache. Each affected check was then run with
approved cache access and passed. No product/test failure or skipped native gate
was substituted with a success. The source checker directory scope was corrected
before it executed. The branch/worktree creation also initially hit a Git metadata
sandbox denial and succeeded after approval.

Semantic review preserved C01–C03, the QuantLib restriction and future P1 labels;
no later package import or final-tree evidence is used to validate this candidate.
Bandit is inapplicable to this test/config/docs-only slice: runtime and governance
implementation are unchanged. Global lint/type/checker configuration is unchanged.
No financial replay, market-data download, benchmark or whole local test suite ran.

### Remaining limits and authorization

The local wheel proof is Darwin arm64 only. The required hosted merged-result
lane, including Linux source/wheel checks and macOS smoke, has not run and remains
a merge gate. QuantLib source-to-wheel binding is still unverified; the existing
2026-10-04 development/CI expiry and artifact release block are unchanged. This
slice claims neither P1 implementation nor performance, empirical or operational
qualification. Older run hashes/results remain attached to their original bytes.

At preparation, nothing had been committed or pushed. The later authorization
below applies only to commit 01; later commits and deployment remain unauthorized.


## Commit 01 publication authorization

On 2026-09-08 the founder authorized committing this slice, pushing it to `dev`,
and merging it to `main`. The original preparation record above is historical;
its hashes and results have not been rewritten to describe a later checkout.

Publication uses `/private/tmp/p1-assembly-20260908/dev` on `dev`, starting at
`38f96ad`. Only the approved seven-file patch was transferred from the original
assembly; its two earlier documentation/instruction commits (`9c6bc07` and
`c035f88`) are excluded. Both the original dirty checkout and the staged assembly
remain preserved. This preserves the approved dependency/serialization scope.

Runtime/governance source, dependency configuration/lock/policy and the changed
test match the validated assembly bytes. The target branch has an older packaged
README, so package installation and affected tests are validated in a fresh
publication environment. The unrelated README and instruction changes are not
included. The approval/status prose in this plan is the only additional edit.

Publication validation on 2026-09-08 used Python 3.12.14 and uv 0.12.7 in the
fresh `dev` checkout. With the same native PATH prefix as above,
`uv run --frozen --no-editable --no-sync pytest -q -ra tests/engineering/test_dependency_admission.py tests/engineering/test_package_definition.py`
passed **25 tests in 3.70s**, with no skips or deselections.
`uv run --frozen --no-editable python -m alpha_research_governance.wheel_smoke`
passed its isolated 17-package install/import proof.
`uv run --frozen --no-editable --no-sync alpha-governance-architecture`
passed **20 documents**; the target branch retains its historical cleanup page.
The prior Ruff, strict mypy, source-standards and audit results remain applicable
because their source/config/lock inputs are byte-identical; no new global tooling
configuration is introduced. Final whitespace and staged-content checks passed.

The required hosted `Authoritative merged-result full lane` must pass on the
`dev`-to-`main` pull request before merging. Actual publication commit and CI run
identities belong to that PR and the local `publication.json` alongside the
preservation archive. This historical record authorizes only commit 01; commit 02
is separately prepared below and remains unauthorized.


## Commit 02 preparation record

Prepared on 2026-09-08 (Singapore) in `/private/tmp/p1-assembly-20260908/dev`
on `dev`, starting at `b2e8cf1` and using the synchronized source revision
`de932733e470c1991aa421d0369693e31adec06c`. Only the USDT accounting-precision
boundary was transferred; no later source implementation, configuration or
lockfile changes were included.

| Category | Exact candidate result |
| --- | --- |
| Runtime implementation | 7 changed lines: 6 additions and 1 deletion in `src/alpha_research/financial_units/models.py` |
| Tests | 30 additions in `tests/unit/test_usdt_units.py`; existing currency/rounding tests unchanged |
| Related documentation | 9 changed lines: 8 additions and 1 deletion in `docs/architecture/financial-units.md` |
| Configuration and lockfiles | None |
| Staged paths | The three paths above; this preparation record is the fourth staged documentation path |

The documentation keeps the future baseline specification as the planned code
path `docs/roadmap/p1-binance-baseline.md`, because that page is not present in
this candidate tree. The separate msgspec migration hunk in the source document
was withheld for its owning step.

### Commit 02 validation

The clean candidate was validated before this record was added:

| Command | Result |
| --- | --- |
| `uv run --frozen --no-editable pytest -q -ra tests/unit/test_usdt_units.py tests/unit/test_financial_units.py` | Exit 0; **107 passed, 1 deselected in 11.12s** |
| `uv run --frozen --no-editable ruff check src/alpha_research/financial_units/models.py tests/unit/test_usdt_units.py` | Exit 0; all checks passed |
| `uv run --frozen --no-editable ruff format --check src/alpha_research/financial_units/models.py tests/unit/test_usdt_units.py` | Exit 0; 2 files already formatted |
| `uv run --frozen --no-editable mypy --strict src/alpha_research/financial_units/models.py tests/unit/test_usdt_units.py` | Exit 0; no issues in 2 source files |
| `uv run --frozen --no-editable alpha-governance-engineering-standards` | Exit 0; Python clarity standards passed for the candidate source, tests, governance and native stubs |
| `uv run --frozen --no-editable bandit -q -c pyproject.toml src/alpha_research/financial_units/models.py` | Exit 0; no findings |
| `uv run --frozen --no-editable alpha-governance-architecture` | Exit 0; architecture link check passed for 20 documents |
| `git diff --cached --check` | Exit 0; staged candidate is whitespace clean |

No full local suite, market-data download, research rerun or hosted CI lane was
run. The required hosted `Authoritative merged-result full lane` remains a
future merge gate; pushing an ordinary feature branch does not trigger it under
the current workflow. No configuration or lockfile proof is applicable to this
step.

**Prepared and staged; awaiting authorization.**

### Commit 02 Currency configuration revision

The original 7-line implementation and 30-addition USDT-only test candidate
recorded above, including its historical 107-test result, is superseded by the
requested configuration-driven Currency revision. That record and its validation
remain preserved as historical evidence; they do not validate the revised source.
The revised boundary adds immutable `(code, minor_unit)` identity, packaged
`default_currencies.json` compatibility definitions, generalized code/quantum
and rounding coverage, and the corresponding uv JSON cache input. The primary
agent planned and audited the change; Luna `xhigh` subagents implemented it.
This foundation-only candidate includes no later P1 consumers or wire schemas.

Validated on 2026-09-08 from this `dev` worktree at `b2e8cf1`. The final model,
defaults and generalized test match the prepared source checkout byte for byte:

| Input | SHA-256 |
| --- | --- |
| `src/alpha_research/financial_units/models.py` | `686d913fb22bee71a4ca906af9244c44e4ed7afe2bb9341d0fa7cf2421c2e843` |
| `src/alpha_research/financial_units/default_currencies.json` | `909281b4c16e1ae38ae69544b42d95add22e8b64241f1d0b0182158057c3719f` |
| `tests/unit/test_currency_units.py` | `f72d78c7a6410c8a84f0696415dfd261f870651dfb9193b12572dbea7b987873` |
| `pyproject.toml` | `891d26c80d59ab99bd945db54529c7fd38e043bbf96852db805513958e042003` |
| Unchanged `uv.lock` | `6841091812d681df9b49af3741940224d358d6643512e2f6418404619323db46` |

The primary agent ran the following affected selection from this worktree:

```sh
uv run --frozen --no-editable pytest -q -ra tests/unit/test_currency_units.py tests/unit/test_financial_units.py::TestFinancialArithmeticContracts tests/unit/test_financial_units.py::TestFinancialModelContracts tests/unit/test_financial_units.py::test_rounding_is_on_grid_idempotent_and_has_bounded_error tests/unit/test_financial_units.py::test_fx_conversion_has_declared_currency_rounding_tolerance tests/engineering/test_package_definition.py
```

It passed **83 tests in 1.03s**, with no skips and one deselected performance
diagnostic. After strengthening the FX example to require rounding `0.525` to
`0.6` on the configured `0.1` grid, the final
`uv run --frozen --no-editable pytest -q tests/unit/test_currency_units.py`
passed **22 tests in 0.45s**, with no skips or deselections. The only subsequent
source delta was corrected docstring wording; numerical behavior is unchanged.

| Additional check | Observed result |
| --- | --- |
| `uv run --frozen --no-sync ruff check src/alpha_research/financial_units/models.py tests/unit/test_currency_units.py` | Passed; final docstrings and final test also checked |
| `uv run --frozen --no-sync ruff format --check src/alpha_research/financial_units/models.py tests/unit/test_currency_units.py` | Passed |
| `uv run --frozen --no-sync mypy --strict src/alpha_research/financial_units/models.py tests/unit/test_currency_units.py` | Passed, two files; reused across docstring and Decimal-literal-only changes |
| Existing `PythonSourceChecker.scan` over those two paths | Zero findings; final docstring meaning reviewed by the primary agent |
| `uv run --frozen --no-editable python -m alpha_research_governance.wheel_smoke` | Clean isolated 17-package install/import passed; Currency import loads the packaged JSON |
| Bandit over the identical Currency implementation in the prepared source checkout | Passed; reused across the docstring-only delta |

The primary review found no remaining issues in currency identity, exact rounding,
unsafe nested-value rejection or configuration ownership. The original staged
patch is preserved locally at `/private/tmp/currency-config-NWW9re/dev-staged-before.patch`.
Wheel-smoke environments are disposable; this is development evidence, not a
retained release artifact. The complete required hosted lane remains pending.
The revised candidate is ready for staging and a separate publication decision;
no commit, push, merge or operational activation is authorized by this revision.

### Commit 02 Currency lookup follow-up

The user's follow-up removed the remaining source-level currency declarations.
`Currency.from_code(code)` selects an immutable value from packaged JSON;
named class attributes and their dynamic installation are removed. Existing C03
callers migrate with the API. Configuration-wide lookup coverage replaces the
selected-preset assertions, including absence of generated class attributes,
unknown/type rejection and synthetic code/quantum identity. This supersedes the
source and test identities in the preceding revision, whose results remain
historical. The primary agent planned, reviewed and tested; Luna `xhigh`
subagents implemented the source, test and documentation edits.

Final identical files in this candidate and the prepared checkout on 2026-09-08:

| File | SHA-256 |
| --- | --- |
| `src/alpha_research/financial_units/models.py` | `89a5cd3795d3a6225212ed3135249109ef7029ae5e5c23638b895d9bf6e2b005` |
| `tests/unit/test_currency_units.py` | `7257286bae512957c52f4c83ec1cb4c6d06087edbdf9d1f884782ebb4db3711c` |
| `tests/unit/test_financial_units.py` | `dbfe355504e194b1171220e90febe270f8e04ddd310847bf913ee5eb68f6763a` |

The preceding JSON, metadata and lock hashes are unchanged. The primary agent
reran the preceding affected pytest command: **89 passed, one performance
diagnostic deselected, no skips, in 0.66s**. Subsequent test edits only applied
Ruff formatting; the identical final tests also passed in the prepared P1
selection. Final `uv run --frozen --no-sync` commands with `ruff check`,
`ruff format --check` and `mypy --strict` over the three files above passed.
`PythonSourceChecker.scan` reported no findings; Bandit passed on the model.
Initial overlong migrated test lines were corrected by Ruff before acceptance.

`uv run --frozen --no-editable python -m alpha_research_governance.wheel_smoke`
passed a clean isolated 17-package installation and import in this worktree.
The primary review found no remaining issues with configuration ownership or
the migrated lookup contract. Reversal restores source, callers and docs
together; no currency data or numerical rule changed in this follow-up.
The prior staged patch is locally preserved at
`/private/tmp/currency-lookup-20260908/dev-staged-before.patch`. Hosted CI remains
pending, and no commit, push, merge or activation was performed.

### Currency and market-data staging candidate

On 2026-09-08, Luna `xhigh` implementers delivered the reviewed source and tests;
the primary agent planned, audited, tested, and integrated the source-first
candidate in DEV at `b2e8cf1`; the full source workspace
is `codex/implementation-plan` at `de932733e470c1991aa421d0369693e31adec06c`.
The candidate contains rows 02, 03, 04, 05 and 08–11 only: Currency, exact
serialization, provenance, the authored reference catalog, and the generic and
Binance market-data event/decoder boundary. Later P1 code remains out of scope.
The 36-file staged review measures 2,041 implementation lines, 1,299 test
lines, and 45 authored-configuration lines by additions plus deletions with
renames; the frozen lock is unchanged. All copied runtime and JSON files match
SOURCE byte for byte, and the source runtime/JSON content did not change during
the test reorganization.

All 181 original test-function AST bodies and decorators were retained, with
only path-parent indices changing; 14 new canonical/catalog cases bring the
source selection from 343 tests plus three diagnostics to 360 tests. The exact
affected commands were:

```sh
# SOURCE
uv run --frozen --no-editable pytest -q -ra -m '' tests/unit
# DEV
uv run --frozen --no-editable pytest -q -ra tests/unit tests/engineering/test_package_definition.py
```

SOURCE passed **360 tests in 4.34s**, with no skips or deselections, including
the three local diagnostics. DEV passed **285 tests in 3.28s**, with three
deselected and no skips. Ruff check/format and strict mypy passed over the
SOURCE 18 unit files and DEV 11 unit files; DEV wheel-smoke also passed, and
the prior DEV 14-file runtime scope passed. PythonSourceChecker found zero findings over SOURCE's 18
tests and DEV's 26 affected Python files, and Bandit passed over the affected
runtime and wheel-smoke scope. The 41-document SOURCE link check, 22-document
DEV check and explicit component README checks passed after the relocated
strategies test link was corrected. Typed construction fixes removed draft
`Any` inference while retaining independent wire-tag assertions.

The frozen build command was:

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/dev-restaging-_d671jzt/wheels
```

Both clean 17-package isolated wheel installations and extended public-import
smoke checks passed. The DEV wheel SHA-256 is
`78c8160889a17c767b4690f030357133fc64b23b76835d617ab71303e963d705`; the
corresponding SOURCE wheel is
`c3709fdd5c8a30e3b93e1c6bd9d8c0c150722450145d2296b35362bfa85cca1c`.
The DEV installed audit found 24 runtime Python/JSON files matching the DEV
checkout and
redecoded all 11,963 canonical events plus every retained raw line to identical
bytes; the canonical event SHA-256 is
`fbbab9f7e474ce478ee6cc66fd23f10033d24dc020c11030fcdc7ab9879eb2ab`.
The verifier was `/private/tmp/dev-restaging-_d671jzt/verify_market_data_installed.py`
and wrote `installed-validation.json`; initial uv-cache denials were retried with
approved access before acceptance.
Final wheel ZIP audits found all packaged runtime Python/JSON/README/py.typed
files exact: 40 in SOURCE and 26 in DEV. Ten organized test files common to
both trees also match byte for byte; two direct-module tests remain at the unit
root, with five Binance tests in SOURCE and three in DEV.
The audit also verified that later P1 modules are absent from DEV; this is
decoder parity only, with no DEV storage or replay implementation introduced.
The artifact and rollback root is `/private/tmp/dev-restaging-_d671jzt`, which
contains the backups, `installed-validation.json`, the verifier, and the SOURCE
wheel under `source-wheels/`. These are local-only checks with no new data fetch;
hosted full CI remains pending. No commit, push or merge was performed.


### Provider and venue decoder separation

On 2026-09-08, Luna `xhigh` implementation subagents separated provider framing
from venue payload interpretation on `codex/implementation-plan` first. The
primary agent planned, reviewed, checked the combined source, and copied the
reviewed foundation changes to the `dev` worktree. Shared `DecodeContext` and
`PayloadDecoder` contain no provider framing or Binance schema. Tardis framing
and Binance composition live under `data/providers/tardis/`; Binance envelope
and payload decoding live under `data/venues/binance/`. Tests mirror those
boundaries. The old public line-decoder and model imports remain compatibility
exports. This slice adds no second exchange implementation.

The primary market-data review (tier 2, offline research/staging) found no
remaining code findings. It verified unchanged context/provenance, capture
rounding, numeric parsing and instrument-lookup function ASTs, and retained all
four original Binance decoder test bodies in the provider composition tests.
The provider regression accepts a native JSON object without a `stream` field;
direct Binance tests accept unframed JSON and reject non-Binance envelopes.
Currency, existing configuration, dependencies and the lockfile are unchanged.

The final affected test selections were:

```sh
# SOURCE: codex/implementation-plan
uv run --frozen --no-editable pytest -q -ra tests/unit/data tests/unit/research/test_research_replay.py tests/unit/research/test_research_runner.py tests/engineering/test_package_definition.py
# DEV
uv run --frozen --no-editable pytest -q -ra tests/unit/data tests/engineering/test_package_definition.py
```

SOURCE passed **64 tests in 1.75s** and DEV passed **28 tests in 1.00s**, with no
skips or deselections in either selected run. These are affected selections,
not a rerun of the previous full-unit totals. Ruff check/format, strict mypy,
PythonSourceChecker, and Bandit passed for the data source/tests and wheel-smoke
scope (25 Python files in SOURCE; 21 in DEV). Local-link validation passed for
41 SOURCE documents and 23 DEV root/docs/component documents.

Both wheels were built with the following command, replacing the output path
with `source-wheels` or `dev-wheels` under the artifact root below:

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/tardis-separation-ll54qzmi/dev-wheels
```

Each wheel passed the existing `_install_and_import` smoke in a fresh locked
17-package environment outside both checkouts. Every packaged runtime file
matches its checkout: 45 in SOURCE and 31 in DEV. Wheel SHA-256 identities are:

- SOURCE: `2c280fd768e9e1e645aec3a89bb4e9ff167d625e1e450f4e2c0f31e7717a140f`
- DEV: `95ea077df1daf081a8135a839bcfea469dcafd84e880e410e90158d93395a795`

The DEV isolated interpreter ran
`/private/tmp/tardis-separation-ll54qzmi/verify_market_data_installed.py` against
the DEV checkout and the retained SOURCE dataset. All 11,963 canonical events
and their raw lines reproduced identical bytes, including timestamps, decimal
values, source order and provenance. The event-file SHA-256 remains
`fbbab9f7e474ce478ee6cc66fd23f10033d24dc020c11030fcdc7ab9879eb2ab`.
The audit verified all 29 installed DEV Python/JSON files, legacy/public decoder
import identity, and absence of later acquisition, book, research, accounting
and strategy modules. This is installed decoder parity, not a new data fetch or
research result. Fourteen transferred runtime/test files match SOURCE exactly;
DEV package exports and wheel-smoke retain their smaller foundation surface.

The first primary test collection failed while concurrent uv commands switched
editable/noneditable environments; sequential `--no-editable` checks resolved
that environment conflict. An import-order lint finding was fixed. The DEV
link-check harness was adapted to its existing `validate_local_links` API after
an unsupported discovery-method call. Sandbox uv-cache denials were retried
with approved access. These failed attempts are retained separately from the
successful checks; no dependency or tool-policy relaxation was required.

The local artifact/reversal root is `/private/tmp/tardis-separation-ll54qzmi`,
containing before-state copies and hash inventories of both workspaces, wheels,
isolated environments, the parity verifier, and `installed-validation.json`.
Reversal restores only this bounded decoder/test/documentation patch and the
corresponding imports, preserving the existing Currency and other P1 work.
Hosted full CI remains pending. Changes are uncommitted and unpushed.
