# Functional source refactoring plan

Owner: repository founder. Status: **stages 1–3 implemented and locally validated;
stage 4 historical features remains planned for a separate task**.
Started from refreshed main `a0dcc86` on `codex/mr28-functional-source-layout`,
2026-09-19. The original plan inspected `5262d61` (78 Python files, 16,459 lines).
This record governs the layout migration and functional ownership assigned to
MRs 28–62 in the [roadmap](README.md#functional-source-ownership-from-mr-28).

The [platform design](../architecture/platform-design.md#current-and-planned-repository-shape)
owns the target tree and import/entrypoint boundaries. Package names describe
functionality directly under `src/`; preserving `alpha_research` is not a design
constraint. The initial migration can still produce one `alpha-research-lab`
distribution containing multiple import packages. A separate distribution,
service, dependency environment or deployment is not implied by a folder.

## Findings and delivered outcome

The refactor preserves identity, calendars, exact units, source decoding and
saved data while giving shared behavior explicit library owners:

- [Acquisition](../../src/applications/acquire/workflow.py) and
  [collection](../../src/applications/collect/workflow.py) use runtime identity
  and dataset publication services; neither imports another application.
  `runtime.ProcessSupervisor` receives a typed spawn-picklable workload.
- [DatasetPublication](../../src/market_data/datasets/publication.py) owns assembly,
  admission and publication. Dataset and fixture commands have separate
  application APIs with one `main` each; archive/capture actions stay subcommands.
- Neutral request bindings and immutable records live in `market_data.contracts`.
  Source requests validate before exposing `.binding`; `RawFiles` and `RawStore`
  validate the binding, metadata and complete original bytes.
- `DatasetReaders` and `OccurrenceVerifier` make source selection explicit.
  Applications provide `SourceAdapters`; quality, manifests, queries and replay
  still reproduce native admission before exposing canonical content.
- `NativeBook`, `CaptureReplay` and `BookProjection` provide one reconstruction
  path for live and saved data. `SavedCapture` consumes journals. Concrete native
  implementations are supplied by `BookAdapters.create` at composition boundaries.
- `WireRecord` owns shared strict wire validation and `DecimalGrid` owns public
  exact-grid operations. `_Partition` and `_EventSteps` stay private within
  query and replay respectively. No namespace compatibility wrappers remain.

Every owned package exposes its explicit `__init__.py` API. Grouping parents stay
inert, libraries have no runnable mains, and applications have at most one command
entry function. No future-feature folders were created.

## Current file disposition

Former paths in this table are relative to the retired `src/alpha_research/`.
Destination paths are relative to `src/` and now exist. The table retains the
original disposition for review; these refinements keep dependencies below their
consumers:

- `Order` and `Level` records live in `market_data/contracts`, while shared state
  lives in `market_data/books`; canonical observation contracts must not import
  stateful reconstruction.
- `BookHistory` is the serialized envelope in `market_data/datasets/books.py`;
  its executable replay lives in `market_data/replay/books.py`. Moving the envelope
  into replay would make dataset admission depend on its downstream consumer.
- Shared source selection/verifiers live in `market_data/adapters/sources/`, and
  wire and transport each have their own package API. Their grouping parent does
  not eagerly initialize provider/venue adapters.

| Current file or family | Target owner and disposition |
| --- | --- |
| `instrument_identity/*.py` | Move models and temporal catalog to `reference_data/instruments/`; retain C01 constructors, errors and temporal behavior. |
| `venue_calendar/*.py` | Move to `reference_data/calendars/`; keep the external calendar adapter behind this owned contract. |
| `financial_units/*.py`, `financial_units/default_currencies.json` | Move to `financial_units/`, including the packaged currency resource; preserve C03 and convention adapter behavior. |
| `_validation.py` | Keep the private C01/C02 error translator inside `reference_data/_validation.py`; it is shared only within that functional owner. |
| `reference_data.py` | Move catalog/listing models to `reference_data/catalogs/`. Move the cross-domain strict wire-record validation base to `serialization/records.py`; catalog tick validation must use a public exact-grid operation in `financial_units`, not `_DecimalArithmetic`. |
| `data/eligibility.py` | Move to `reference_data/eligibility/`; retain valid-time, knowledge-time, evidence and correction histories. |
| `serialization.py` | Move exact domain codecs to `serialization/codec.py`; reuse cached schemas and preserve encoded financial values. |
| `configuration.py` | Move job/universe records and resolution to `configuration/data_jobs.py`. Extract source fingerprint calculation to `runtime/identity.py`; applications supply the resulting identity to resolution. |
| `core/events.py` | Move provenance and knowledge-basis contracts to `market_data/contracts/provenance.py`; retire the generic `core` container. |
| `data/events.py`, `data/decoders.py` | Move event templates and decoding contracts to `market_data/contracts/`; source-independent contracts must not import adapters. |
| `data/requests.py`, `data/inputs.py` | Move source request records and reader/verifier protocols to `market_data/contracts/`. Protocol signatures use lower-level byte-reader capabilities where necessary instead of importing concrete storage implementations. |
| `data/normalization.py` | Move the `Occurrence` record and its structural lineage invariants to `market_data/contracts/occurrences.py`; keep source re-decoding in adapters. |
| `data/raw_objects.py` | Put the immutable descriptor/binding records in `market_data/contracts/`; put file fingerprinting and verified file operations in `market_data/storage/objects.py`. Preserve both request-binding and full-byte verification. |
| `data/raw_store.py` | Move to `market_data/storage/raw.py`; accept a validated request binding without importing source-specific implementations. |
| `data/manifests.py` | Move acquisition completion, receipt and checkpoint behavior to `market_data/acquisition/manifests.py`; storage remains responsible for byte publication. |
| `data/revisions.py`, `data/quality.py` | Move correction admission and quality policy/services to `market_data/validation/`. Inject verification capabilities rather than selecting adapters here. |
| `data/datasets.py`, `data/snapshots.py` | Move to `market_data/datasets/`; separate immutable manifest validation from saved-input verification where collaborator injection requires it. Retain atomic publication and verified reopening. |
| `data/book_datasets.py` | Split observation records into `market_data/contracts/`, saved book admission/manifests into `market_data/datasets/`, `BookHistory` replay into `market_data/replay/`, and capture-to-canonical persistence into `market_data/collection/`. |
| `data/asof.py`, `data/query.py` | Move together to `market_data/query/`; `_Partition` stays an implementation detail within that package. |
| `data/replay.py`, `data/book_replay.py` | Move together to `market_data/replay/`; share one stepping/cursor implementation and keep `_EventSteps` internal. |
| `data/eda.py` | Move EDA selection and summary behavior to `research/exploration/`; market-data access stays in query/replay. |
| `data/live/config.py` | Move pure capture configuration to `configuration/capture.py` and retained capture request records to `market_data/contracts/`. Configuration must not construct transports or applications. |
| `data/live/journal.py` | Move durable journal behavior to `market_data/storage/journal.py`, with capture record/cursor values in `market_data/contracts/` where needed by other owners. |
| `data/live/book.py` | Move `Order`/`VisibleBook` and shared state operations to `market_data/books/`; move vendor JSON `Wire` decoding to `market_data/adapters/wire.py`. |
| `data/live/replay.py` | Move reusable reconstruction state to `market_data/books/` and saved-journal consumption to `market_data/replay/`; supply the selected book implementation through its narrow contract. |
| `data/live/quality.py` | Move continuous freshness/validity gates to `market_data/validation/freshness.py`; depend on record contracts, not journal implementation. |
| `data/live/health.py` | Move observations, health policy and bounded alert delivery to `telemetry/`; process termination and supervision belong to `runtime/`. |
| `data/live/transport.py` | Move transport behavior to `market_data/adapters/`, with venue discovery/snapshot specifics under its venue owners. Put `FeedSocket` in the neutral contracts. |
| `data/providers/catalog.py` | Retain the small explicit capability mapping in `market_data/adapters/catalog.py`, consumed by application composition only. No new plugin registry or dynamic imports from configuration. |
| `data/providers/admission.py` | Move source re-decoding/verifiers to `market_data/adapters/verification.py`, implementing the retained neutral verifier contract. |
| `data/providers/transport.py` | Move shared retry classification to `market_data/contracts/errors.py`. |
| `data/providers/binance/rows.py`, `data/providers/binance/occurrences.py`, `data/providers/binance/transport.py` | Move to `market_data/adapters/providers/binance/`; retain source rows, transport bounds and occurrence lineage. |
| `data/providers/binance/trades.py` | Move the immutable archive-trade schema to `market_data/contracts/binance.py`; keep row parsing and record construction in the Binance provider adapter. Preserve archive-specific absent capture clocks. |
| `data/providers/tardis/*.py` | Move to `market_data/adapters/providers/tardis/`; retain provider framing separately from venue payload parsing. |
| `data/venues/binance/events.py` | Move the native event schemas to `market_data/contracts/binance.py`, preserving native names, fields and wire tags. |
| `data/venues/binance/payloads.py`, `data/venues/binance/codecs.py` | Move to `market_data/adapters/venues/binance/`; native schema codecs and parsing remain explicitly Binance-owned. |
| `data/venues/bitfinex/*.py`, `data/venues/coinbase/*.py` | Move to the corresponding `market_data/adapters/venues/` owners; retain authentication and native sequence/book semantics. |
| `data/venues/okx/book.py`, `data/venues/okx/history_reader.py`, `data/venues/okx/history_store.py`, `data/venues/okx/history_transport.py` | Move to `market_data/adapters/venues/okx/`; native archive admission/storage composes neutral byte storage without leaking into it. |
| `data/venues/okx/history_config.py` | Move pure archive selection/limits to `configuration/archives.py`, immutable request records to `market_data/contracts/`, and discovery-response/URL interpretation to the OKX adapter. Preserve the existing serialized fields and strict validation. |
| `pipelines/acquisition.py` | Put CLI and actual fetch/resume/archive workflow coordination in `applications/acquire/`; put reusable acquisition policy/checkpoint behavior in `market_data/acquisition/`. Keep one command entry function, with archive actions as subcommands. |
| `pipelines/dataset.py` | Split CLI/coordination between `applications/publish_dataset/` and `applications/inspect_fixture/`. Put reusable assembly/publication in `market_data/datasets/`, revision/quality behavior in validation, and reader behavior in adapters. Preserve actual coordination as orchestration functions. |
| `pipelines/live.py` | Put capture/probe/replay command coordination in `applications/collect/`; reusable receipt/session behavior in `market_data/collection/`, watchdog/process lifecycle in `runtime/`, identity in `runtime/identity.py`. Optional publication uses dataset services, never another application. |
| `pipelines/eda.py` | Move the configured callable workflow to `applications/explore/`; reuse `research/exploration/` and query services. |
| Every `__init__.py`, root `py.typed`, `data/README.md` | Replace old exports with functional public APIs; retire obsolete root/pipeline/provider namespace files. Install a `py.typed` marker in each shipped top-level import package. Move the data guide to `src/market_data/README.md` during implementation and update its links/examples. |

## Dependency repairs before relocation

Moving files alone will not establish the target boundaries. In particular:

1. Shared event/request/occurrence records currently import source event types
   whose modules also parse rows and read storage. Separate those schemas from
   adapters first. Preserve native record distinctions and strict tagged unions;
   do not replace them with untyped dictionaries or broaden accepted products.
2. Raw storage checks a validated request identity and exact bytes. Source
   configuration/request validators must still run before storage operations;
   changing a type annotation to a permissive protocol is not equivalent proof.
3. Quality and snapshot reopening still re-decode original bytes and reproduce
   admission before exposing canonical content. Inject the saved reader and
   occurrence verifier; never remove the revalidation to break an import cycle.
4. Books and replay receive native decoders/state implementations from application
   composition. Journal records and book contracts stay below adapters and
   replay. Live receipt and offline reconstruction continue to apply the same
   message-boundary transitions.
5. `runtime` receives a callable/typed workload and explicit configuration; it
   never imports an application to start it. `configuration` does not import
   runtime, applications or adapter factories. Applications supply installed
   identity and construct supported implementations.
6. Preserve cohesive methods and genuine orchestrator functions under the
   [engineering guide](../coding_standards/README.md#orchestrator-pipelines-and-libraries).
   A new folder, forwarding function or static-method collection does not by
   itself establish ownership. Keep namespace-parent initializers minimal to
   avoid eager imports that recreate cycles through otherwise independent leaves.

## Application entrypoints and compatibility

These are the **current installed bindings** in
[pyproject.toml](../../pyproject.toml). Each application owns one public API module
(`__init__.py`) and at most one registered command entry function (`main`). Its
actual programmatic workflow can also be exported from that same API module;
this is not a one-function limit on reusable Python interfaces. Internal helper
modules do not add independently runnable commands or `__main__` entrypoints.

| Existing supported entry | Target binding | Compatibility |
| --- | --- | --- |
| `alpha-acquire` | `applications.acquire:main` | Preserve arguments, archive subcommands, resume behavior, output and exit codes. |
| `alpha-collect` | `applications.collect:main` | Preserve capture/probe/replay actions, bounded supervision and explicit credential selection. |
| `alpha-dataset` | `applications.publish_dataset:main` | Preserve both publish and inspect subcommands, admission outcomes and retry acknowledgement. |
| `alpha-inspect-fixture` | `applications.inspect_fixture:main` | Preserve fixture selection, clocks and strict input refusal. |
| Callable `inspect_eda` | `applications.explore:inspect_eda` | Preserve callable use; no additional CLI is required by this refactor. |

Existing Python import paths change at the coordinated source-layout cutover.
Update every repository caller, test, notebook source cell and installed consumer
with that cutover. Do not retain a permanent `alpha_research` umbrella or add
forwarding compatibility implementations. If an actual out-of-repository consumer
is found, record its migration before removing the path it needs; no such consumer
was established by this repository inspection. Keep CLI names and semantic
configuration identifiers such as `dataset.inspect` stable; they are not Python
module paths and must not acquire arbitrary-import semantics.

Old stored JSON schemas, raw digests, source timestamps, quality scope and
snapshot identities remain readable. Refactoring does not grant causal quality,
new source support or operational readiness. Do not regenerate historical
notebook outputs or acceptance records just to replace import names; annotate
their tested revision and update maintained source links as appropriate.

### Installed identity and package inputs

Before migration, `Configuration._implementation_identity` scanned its containing package, including
Python/JSON/typing assets and selected dependency versions. `InstalledIdentity`
scanned Python files from a different path-derived root. Moving either
unchanged would hash an incomplete subtree or the wrong parent directory.

Move the responsibility to `runtime/identity.py` and discover the shipped
functional package files from the installed distribution, bounded to its owned
roots/resources. Keep deterministic relative paths and fail visibly on missing
required files. Preserve the distinction between the two existing identity
contracts; do not silently unify their input sets. The new source paths and bytes
produce new implementation/run identities. Reopening old snapshots must use their
retained identities; a resume request bound to an old implementation must not be
silently relabeled to match a new run. Keep the prior wheel/config for such a run
or explicitly start a new run.

The packaging cutover must update Hatch's included packages/assets, strict mypy
package discovery, Ruff first-party imports, the engineering checker's explicit
project-package list, entrypoint metadata, package-definition tests and
installed-wheel smoke. Preserve all existing check roots and strict settings.
The distribution name and frozen dependency set can stay unchanged; any lock
metadata update follows the normal frozen-build contract. Verify currency JSON
and `py.typed` placement, all application imports, and that no functional package
is shadowed by another installed module. Never scan all of `site-packages` to
construct a runtime identity.

## MR 28 delivery stages

These are ordered reviewable stages within MR 28, not new MR numbers or a new
milestone. They may use more than one pull request; each accepted intermediate
state keeps the current commands usable. The source-layout stage is a
prerequisite for new MRs 28–62 source placement, including E1. Historical feature
completion is not a new prerequisite for the deterministic baseline.

| Stage | Work and concrete consumer | Sufficient completion evidence |
| --- | --- | --- |
| 1. Separate contracts and shared behavior | Repair the dependencies above in the current layout: source records vs adapters, byte binding vs source requests, injected admission/readers, shared book reconstruction, reusable dataset publication, and identity/supervision outside peer pipelines. Each extraction has the existing CLI, query or replay consumer named in the disposition table. | Focused regressions cover strict source refusal, re-decoding, immutable storage, saved snapshot verification and live/replay parity affected by the extraction. No command behavior or schema change is hidden in a move. |
| 2. Cut over functional packages and callers | Move existing functionality using the disposition table; split the two dataset commands; update Python imports, package metadata, resources, governance package discovery, notebooks and installed consumers atomically. Retire `src/alpha_research/` after its callers are migrated. | Installed wheel outside the checkout imports every shipped functional public API and executes the four existing command contracts using synthetic/saved inputs. Verify old snapshot readability, expected new implementation identity, source/asset scan scope, currency resources and typing markers. |
| 3. Enforce ownership and finish migration | Add small AST/import and metadata checks to the existing engineering checks for forbidden dependency directions, cross-owner private imports and multiple command entry functions in one application directory. Library folders must not gain executable mains. Update current architecture/data/test usage docs and the first-party import rule. | Positive cases plus representative forbidden imports/duplicate entrypoints prove the checks work; affected integration tests and required full pre-merge checks pass. Report counts/skips honestly; retired paths have no maintained callers. Record the migrated revision and reversal artifact here. |
| 4. Deliver MR 28 historical features | Implement the selected causal feature contract in `research/features/` and its configured consumer in `applications/features/`, using `market_data/query/` and `market_data/replay/` APIs. Do not move transforms into the application or add an independent feature runner elsewhere. | Retain MR 28's independent window examples, future-perturbation checks, units, availability, lineage and explicit missing/stale outcomes. Layout completion alone does not complete feature acceptance. |

Stages 1–3 are the **MR 28 source-layout stage** referenced by later dependency
cells. They may close before stage 4 so E1 can proceed without feature/model
work. There is one installed source tree at cutover, not two long-lived parallel
implementations. R1 can still be pulled forward for a concrete deployment before
this migration; it verifies the actual selected artifact layout.

## Verification, evidence reuse and reversal

Use existing tests and installed consumers before adding new harnesses. During
extraction, select tests for the touched contract. At the broad package/import
cutover, all runtime imports are affected, so run the complete configured static
scope and correctness lane, including the existing installed acquisition,
publication, EDA, capture/recovery and replay consumers. The existing wheel smoke
must cover the new package roots outside the checkout; source imports alone
cannot establish packaging correctness. Keep the required full merge lane.

Compare exact event/financial serialization, retained raw bytes, canonical
payloads, temporal selection, quality refusal and replay traces. Implementation
hashes and newly resolved run/snapshot identities are expected to change; do not
assert their equality across different code versions. Verify old snapshots by
their retained identities and compare economic/canonical content separately.

No fresh venue capture, data purchase, model fitting or baseline rerun is required
solely for relocation. Existing source qualification and research records remain
evidence for their recorded revisions. If a domain transition, timestamp rule,
admission rule or encoded value changes, treat it as a behavioral change and
renew the relevant evidence instead of calling it a mechanical migration.

Classify the first failure as implementation, import/packaging, test harness,
saved data or external access before broadening tests. Record commands, tested
revision, failures, fixes, skips and remaining limits in the MR acceptance record.
Do not repeatedly rerun the whole suite without a relevant correction.

Reverse a failed implementation slice through an ordinary reviewed revert of its
source, metadata and callers together; retain the prior installed wheel and
configuration. Do not rewrite stored manifests or identities to make rollback
appear compatible. New records that the older artifact cannot read remain tied
to the compatible artifact; directory rollback is not a data migration.

## Original planning verification

The original plan recorded source inspection and planned acceptance only. The baseline
architecture-link check passed for 60 documents before these documentation edits;
`.venv/bin/alpha-governance-architecture` passed for 61 documents with the plan.
A read-only inventory check accounts for all 78 Python files in the disposition
table, including the explicit initializer rule. A table audit verifies all 35 MR
rows from 28 through 62 have owner/application assignments, retains the original
domain acceptance for MRs 29–62, and adds only the stated layout dependencies.
`git diff --check` validates patch whitespace. No runtime tests are claimed for
these documentation edits. No runtime files, commands, imports or package
metadata were changed by authoring the plan. The implementation evidence below supersedes only that planning status.

## Cutover evidence

The locally tested source is the `codex/mr28-functional-source-layout` cutover;
the implementation commit is recorded below before the final documentation commit.
CPython 3.14.7, macOS arm64, frozen dependencies; no dependency or serialized-schema
version was changed. All commands ran from the repository root unless isolated by
the existing consumers.

| Check | Actual result |
| --- | --- |
| Focused extraction regressions | Storage, occurrence/quality, saved datasets and book replay: 71 passed, 1 harness failure, 2 deselected; the failure reused an intentionally corrupted request and was fixed without relaxing validation. |
| Focused cutover correction run | 123 passed, 1 deselected, 17.68 s; command aliases, asynchronous snapshot test patching, committed journal replay, supervision, identity inventory and source-layout checks. |
| `TMPDIR=/private/tmp make check` | Passed: formatting/lint; strict mypy over 236 sources; native stubtest over 1,548 modules; engineering, dependency and architecture checks; Bandit; dependency audit; secret scan; **1,064 correctness tests passed, 3 performance tests deselected, no skips**, 69.16 s; isolated wheel smoke passed. |
| Isolated wheel smoke | Imports every functional public API outside the checkout, verifies all nine roots, currency JSON and typing markers, excludes governance/retired namespace, exercises all four commands and existing ingestion/recovery consumers, and reopens the pre-cutover snapshot. |
| Maintained notebooks | All 70 code cells compile with notebook top-level-await support; every functional import resolves. Outputs and execution counts are byte-for-byte-equivalent JSON values to their retained revisions. No notebook/live source or historical benchmark was rerun. |

The first broad unit run found stale command/resource imports and test patch targets;
these were migrated. A macOS Unix-socket path exceeded its OS limit under the long
default temporary directory; the complete lane uses `/private/tmp`. Concurrent
uv checks initially switched a running test's environment between editable and
installed forms; subsequent validation ran sequentially. Identity fault injection
found that Python 3.14 filters missing files from `Distribution.files`; `RuntimeFiles`
now reads the wheel RECORD directly, rejects missing/duplicate owned inputs, checks
root shadowing, and excludes unrelated installed files. These are validation and
packaging corrections, not new source capabilities.

The [historical fixture](../../tests/fixtures/datasets/historical_snapshot/provenance.json)
was generated by the pre-cutover installation at `a0dcc86`, with retained original
implementation identity `ba478bfc5f722da7217f94a042e1ef0117531d74730e381522d62b30645604d1`
and snapshot identity `23378e41e37533c74a41a3ce5bfa4046aa659ae3bd4131b08321c72dc3a448b9`.
Tests reopen it and compare exact manifest/canonical bytes; they never substitute
current implementation identity. Its producer installation included files outside
the clean wheel inventory, so its stored identity is deliberately distinct from
the clean reversal wheel. The fixture proves historical reading, not identical
run IDs between different installation inventories.

A clean pre-cutover reversal wheel is retained locally at
`/private/tmp/source-layout-reversal/alpha_research_lab-0.1.0-py3-none-any.whl`,
SHA-256 `11676ad0a111f951750e5f6ae9ef6c182663701f1fe44514a32f1dd560b6a612`.
Configuration/reference inputs remain unchanged in Git at `a0dcc86`, and resolved
configuration is embedded in the retained fixture. This local artifact is not a
published release. For an existing resumable run, use that run's exact retained
artifact/configuration, or start a new run; do not relabel stored identities.
Revert source, packaging, callers and docs together through ordinary review.

Stage 4 remains unimplemented: no historical feature definitions, causal window
acceptance, feature application, model work, new empirical capture or baseline
research result is claimed. Existing exploratory/degraded source limits remain.
