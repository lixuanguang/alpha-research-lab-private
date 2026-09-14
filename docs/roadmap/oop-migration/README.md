# Runtime OOP migration review and implementation handoff

Owner: repository founder. Reviewed: 2026-09-14.
Status: runtime batches 1–4 complete and locally verified on 2026-09-14.
Repository-wide tooling/test migration and automated enforcement remain pending.
Reviewed source: `7f4893a78d9866fff634ad562eb459112a42d8ab`, with a clean working
tree at review time. The inventory and review evidence below describe that
baseline; the [implementation record](#runtime-implementation-and-validation)
describes the subsequent uncommitted runtime changes and actual verification.

The runtime contains reusable behavior implemented as free functions even though
the adopted engineering policy assigns that behavior to cohesive classes. Most
small classes represent useful domain types, schemas, or adapter contracts.
Consolidate duplicated implementation where contracts coincide while preserving
those distinctions.

## Authority and scope

The [engineering guide](../../coding_standards/README.md#design-and-interfaces)
owns the class/function rules, including
[orchestrator boundaries](../../coding_standards/README.md#orchestrator-pipelines-and-libraries)
and [migration scope](../../coding_standards/README.md#python-scope-and-migration).
The [main roadmap](../README.md#oop-migration-status) owns overall migration
status and delivery coordination. This README supplies the runtime inventory,
review decisions, and implementation handoff for that existing work.

The reviewed scope is all 25 Python files under `src/alpha_research`, with the
relevant contracts, exports, callers, examples, and tests inspected as supporting
evidence. The assessment focused on architecture and standards for the market
and reference-data foundation, with inferred risk tier 2. The findings below
establish compliance and maintainability gaps; they do not establish a runtime
failure or a complete correctness/security review.

Runtime remediation includes affected tests, package exports, maintained examples,
documentation, and installed-consumer checks. Repository-wide conversion of
unrelated development tools and tests, and new OOP checker enforcement, remain
separate work in the main roadmap. Completing this runtime scope cannot mark the
whole repository OOP migration complete.

## Findings

### F1 — P2: reusable behavior lacks class ownership

The inventory contains **62 module-level functions in 13 modules**, including
17 names without a leading underscore. These implement library operations rather
than workflow coordination. There are also **5 nested helper functions**. Both
patterns require migration under the adopted policy.

For example, serialization exposes encoding/decoding hooks and operations beside
module-global compiled codecs, while existing decoder and record classes call
free parsing and validation helpers. Callers therefore continue to depend on
function APIs that the target architecture requires replacing.

Give each operation a meaningful owner. Prefer an existing record or adapter;
introduce a cohesive service only when several operations share a concrete
contract or resource lifetime. A function-by-function conversion into separate
classes, or a miscellaneous static-method container, would not satisfy this
review. Stateless operations can remain pure methods.

### F2 — P3: settlement retains redundant forwarding APIs

The module-level `adjust_business_day` and `settlement_date` functions in
[conventions.py](../../../src/alpha_research/financial_units/conventions.py)
repeat argument validation, construct `SettlementConventions(calendar)`, and
forward the call. Each call constructs and revalidates the calendar-bound service
again. Their retirement is already specified by the
[financial-units contract](../../architecture/financial-units.md#convention-adapter).

Migrate callers to a reused service, then retire both functions and their package
exports together. Preserve supported exception types, causes, coverage behavior,
and method validation order. Review the legacy multi-invalid-input cases
explicitly: construction now validates the calendar before a method can be
called, so any changed constructor-versus-call error timing must be accounted
for in the migration rather than hidden by weakened assertions.

### F3 — P3: identity and calendar error translation is duplicated

`_InstrumentIdentityModel` and `_VenueCalendarModel` duplicate their
`_ValidationErrorReader` protocol, error context/detail schemas, compiled
`TypeAdapter`, and message-construction algorithm in
[identity models](../../../src/alpha_research/instrument_identity/models.py)
and [calendar models](../../../src/alpha_research/venue_calendar/models.py).
Changes to the shared error-formatting contract require coordinated edits.

Share this private implementation with the domain exception type supplied
explicitly, using a neutral internal dependency that does not make either domain
depend on the other. Preserve error locations, owned causes, input hiding, and
exception chaining. Retain separate domain exception classes and domain model
boundaries.

Do not automatically absorb `_FinancialUnitModel`: C03 uses a different error
translation path and overrides `model_copy` to reconstruct and validate values.
C01 and C02 retain trusted, unchecked framework copy operations. Those differences
are established contracts, not duplication to erase.

All three findings are high-confidence architecture/standards findings in the
reliability/operability dimension. Their disposition is advisory for the current
runtime and unresolved for the claimed OOP target; no P0/P1 behavioral defect was
established by this review.

## Complete function inventory and ownership direction

Counts describe the reviewed revision. Suggested service names and private
boundaries are design directions, not existing APIs or a required class count.
F2's two forwarding functions are included in the total of 62.

| Source module | Count | Functions | Ownership direction |
| --- | ---: | --- | --- |
| [core/events.py](../../../src/alpha_research/core/events.py) | 3 | `_require_text`, `_normalize_utc`, `_validate_provenance` | `EventProvenance` owns its validation and UTC normalization. |
| [data/events.py](../../../src/alpha_research/data/events.py) | 5 | `_require_text`, `_require_int`, `_validate_decimal`, `_validate_levels`, `_validate_market_fields` | Existing event owners share coincident field-validation contracts; keep disconnect-specific invariants distinct. |
| [data/providers/tardis/decoder.py](../../../src/alpha_research/data/providers/tardis/decoder.py) | 1 | `parse_capture_time` | `TardisDecoder` owns provider capture parsing. |
| [data/venues/binance/codecs.py](../../../src/alpha_research/data/venues/binance/codecs.py) | 4 | `validate_market_event`, `encode_market_event`, `decode_market_event`, `_decode_binance_payload` | One canonical event codec owns the first three operations; raw source-payload decoding belongs with `BinancePayloadDecoder`. |
| [data/venues/binance/events.py](../../../src/alpha_research/data/venues/binance/events.py) | 1 | `_validate_symbol` | `BinanceMarketEvent` owns its symbol rule. |
| [data/venues/binance/payloads.py](../../../src/alpha_research/data/venues/binance/payloads.py) | 4 | `_event_time`, `_decimal_text`, `_levels`, `_instrument_by_symbol` | `BinancePayloadDecoder` owns venue parsing, configuration indexing, and cached source decoders. |
| [financial_units/conventions.py](../../../src/alpha_research/financial_units/conventions.py) | 2 | `adjust_business_day`, `settlement_date` | Retire forwarding APIs in favor of existing `SettlementConventions` methods. |
| [financial_units/models.py](../../../src/alpha_research/financial_units/models.py) | 8 | `require_type`, `require_currency`, `require_decimal`, `_validate_currency_code`, `_validate_currency_quantum`, `_load_default_currencies`, `exact_decimal`, `round_fraction` | Currency-specific operations belong on their currency owner; share exact grid validation/conversion/rounding under a cohesive arithmetic contract. Preserve typed validator callback signatures and bounded preset loading. |
| [instrument_identity/models.py](../../../src/alpha_research/instrument_identity/models.py) | 11 | `_require_non_nil_uuid`, `_parse_canonical_uuid`, `_require_bounded_text`, `_validate_identifier_namespace`, `_has_valid_luhn_checksum`, `_has_valid_isin_checksum`, `_cusip_character_numeric_value`, `_has_valid_cusip_checksum`, `_has_valid_sedol_checksum`, `_validate_identifier_value`, `require_utc_datetime` | IDs own UUID behavior; identifier validation owns checksum and namespace mechanics; shared model methods own coincident boundary checks. Preserve query-specific namespace semantics. |
| [reference_data.py](../../../src/alpha_research/reference_data.py) | 3 | `_require_utc`, `_require_text`, `_require_decimal` | `SpotInstrument` and `CatalogSnapshot` own reference-record invariants, sharing only matching contracts. |
| [serialization.py](../../../src/alpha_research/serialization.py) | 10 | `_dimension_wire`, `_dimension_value`, `_decimal_value`, `_currency_wire`, `_currency_value`, `encode_domain`, `decode_domain`, `_json_decoder`, `encode_json`, `decode_json` | A cohesive serialization owner supplies domain hooks and deterministic JSON operations with an explicit compiled-schema lifetime. |
| [venue_calendar/adapter.py](../../../src/alpha_research/venue_calendar/adapter.py) | 4 | `_calendar_library_version`, `_as_date`, `_as_utc_datetime`, `_required_utc_datetime` | `ExchangeCalendarsAdapter` owns native metadata checks and source-value conversion. |
| [venue_calendar/models.py](../../../src/alpha_research/venue_calendar/models.py) | 6 | `_require_bounded_text`, `_require_stable_token`, `require_utc_datetime`, `_require_date`, `_require_timezone_name`, `_require_non_nil_uuid` | Existing calendar records/base own their boundary validation; `VenueId` owns UUID behavior. |

The five nested functions are:

| Existing owner and operation | Nested helpers | Migration concern |
| --- | --- | --- |
| `SymbologyCatalog._validate_mapping_graph` | `mapping_order` | Preserve chronological overlap checking. |
| `SymbologyCatalog.current_projection_mappings` | `mapping_order` | Preserve the complete deterministic projection key. |
| `SymbologyCatalog.get_mapping_history_for_identifier` | `correction_depth_for_mapping`, `mapping_order` | Preserve correction-depth ordering and keep per-call indexes local; do not introduce stale instance state. |
| `SettlementConventions.adjust_business_day` | `select` | Preserve bounded selection failures and modified-convention fallback order. |

These occur in [catalog.py](../../../src/alpha_research/instrument_identity/catalog.py)
and [conventions.py](../../../src/alpha_research/financial_units/conventions.py).
Use class-owned callbacks with the required signatures. Their current nesting is
not an exception to the ownership rule.

## Class consolidation decisions

Of 109 class definitions, 23 define exactly one method directly. This count
includes records, protocols, properties, and classes with inherited operations.
It is not a removal target.

| Classes or implementation | Decision | Reason and constraint |
| --- | --- | --- |
| C01/C02 error readers, detail records, and translation algorithm | Share the duplicated private implementation | Same framework boundary and formatting contract; retain domain exceptions and copy semantics as described in F3. |
| `InstrumentId`, `MappingId` | Consider sharing UUID implementation; retain distinct concrete types | Constructor, canonical parsing, non-nil validation, and rendering overlap. Preserve signatures, equality, hashing, error labels, and strict nested-type checks. |
| `ExternalIdentifier`, `IdentifierQuery` | Share matching validation mechanics; retain separate classes | Scheme/value checks overlap, but a missing local namespace broadens a query and invalidates an exact identifier. |
| `TardisDecoder`, `BinancePayloadDecoder` | Keep separate and move their helpers onto them | Provider framing/provenance and venue parsing/configuration are distinct responsibilities with real consumers. |
| `TaggedEvent`, `MarketEventRecord`, `BinanceMarketEvent` | Retain separate responsibilities | Frozen tagged-schema policy, common market fields, and venue symbol rules are different reusable contracts. Preserve validation dispatch. |
| `DepthSnapshot`, `DepthUpdate`, `Trade`, `Disconnect` and their wire/source schemas | Keep distinct | Tags, required fields, timestamp bases, unknown-field policies, and invariants differ. A broad optional-field record weakens these boundaries. |
| `Money`, `Price`, `Quantity`, `Tick`, `Lot`, `Rate`, `Yield`, `Volatility`, `Duration` | Keep distinct; reuse existing `_Value` behavior | Arithmetic, dimensions, positivity, equality, and units depend on concrete types. Similar numeric fields do not make the concepts interchangeable. |
| `AuctionWindow`, `TradingSession`, `MarketInterruption`, `PriceLimitWindow` | Keep distinct | Their containment expressions overlap, but session, auction, halt, and independent price-limit semantics differ. A generic window hierarchy solely to remove a short expression has little benefit. |
| `QuantLibConventions`, `SettlementConventions`, `SettlementCalendar` | Keep separate | Native day counts, calendar-bound adjustment/lag, and immutable eligible dates have different dependencies and ownership. |
| `PayloadDecoder`, `_TimestampConverter`, `_AttributeReader`, domain exceptions | Retain meaningful narrow contracts | Single operations or empty exception bodies can carry type and failure semantics. Only the duplicate C01/C02 error-reader definitions are identified for sharing. |

UUID and identifier-field sharing are recommendations to assess against the final
diff. Retain a small amount of duplication when eliminating it requires extra
forwarding layers, changes public semantics, or creates an unrelated framework.

## Suggested execution batches

These are subdivisions of the existing OOP migration, not new roadmap milestones.
All were pending at the reviewed revision. See the current implementation record.
Recheck the current tree before editing
and keep changes from other work intact.

| Batch | Deliverable and affected consumers | Sufficient evidence |
| --- | --- | --- |
| 1 — Domain ownership and shared validation | Move C01/C02/C03, provenance, reference, and shared event helpers to cohesive owners; migrate nested catalog callbacks; consolidate F3 and assess UUID/identifier sharing. Update direct consumers and validator callbacks together. | Existing identity/calendar/financial goldens, invalid-construction/copy/error tests, exact arithmetic, provenance and reference tests; no changed type or wire identity. |
| 2 — Serialization and decoding | Introduce the cohesive serialization/canonical event codec owners; move provider and venue helpers/cached source decoders to their existing adapters. Migrate imports, exports, tests, maintained snippets, and the active research-foundations notebook. | Deterministic bytes and catalog hashes, exact numeric and legacy currency round trips, malformed/unknown-field rejection, capture rounding, disconnect provenance, configured-symbol behavior, and decoder reuse after failure. |
| 3 — Settlement and calendar adapter cleanup | Retire settlement forwarding functions, move nested selection and calendar adapter helpers into their existing owners, and migrate affected callers/exports/docs. | Existing settlement/coverage/native adapter goldens, exact owned errors, constructor-versus-call review, and repeated-call/failure isolation. |
| 4 — Runtime integration and handoff | Re-inventory `src`, inspect ownership/cohesion and dependency direction, complete affected caller migration, and update this document plus the main roadmap. | Focused static checks during edits; final applicable source checks and installed-wheel consumer validation under the repository workflow. Record exact commands, tested state, passes, deselections, and gaps. |

Dependencies follow the imports: shared validation precedes its consumers, and
serialization hooks and canonical codecs migrate together. Adjust batch boundaries
when an atomic caller change is necessary. Do not create temporary forwarding APIs
to make an intermediate batch appear complete.

Keep library behavior independent of pipeline configuration. Reuse compiled codecs
across events; do not add per-event schema compilation or encode/decode round trips.
Preserve the distinction between rejecting non-UTC domain inputs and normalizing
aware provider timestamps. Currency lookup, native adapters, and domain validation
must retain their existing side-effect boundaries.

For reversal, revert a batch's implementation, imports/exports, consumers, and
documentation together. Serialized events and financial identities are expected
to remain unchanged; an intentional wire migration would need its own explicit
contract and is outside this refactor.

## Validation and completion

The relevant contracts remain [instrument identity](../../architecture/instrument-identity.md),
[venue calendars](../../architecture/venue-calendar.md),
[financial units](../../architecture/financial-units.md),
[market data](../../data/contracts.md), and
[point-in-time semantics](../../data/point-in-time-semantics.md).
Use their existing behavioral tests and independent goldens. Add a focused
regression only when a changed ownership/lifetime boundary introduces a realistic
failure not already covered. Do not replace assertions with class-existence tests
or alter numerical goldens to accommodate a refactor.

During implementation, use the pinned commands from the
[engineering guide](../../coding_standards/README.md#commands-and-enforcement)
and [Makefile](../../../Makefile). For example, select the affected paths from:

```sh
uv run --frozen --no-editable pytest -q tests/unit/instrument_identity tests/unit/venue_calendar tests/unit/financial_units
uv run --frozen --no-editable pytest -q tests/unit/core tests/unit/data tests/unit/test_reference_data.py tests/unit/test_serialization.py
make architecture-check
```

The first two commands are proposed implementation checks, not additional results
claimed by this document. Run relevant Ruff/mypy and engineering checks as the
code changes. The full required source and installed-wheel checks still apply
before merge; use `make check` to reproduce the local lane. Do not rerun the full
lane after each mechanical move unless a failure or uncovered risk warrants it.
Confirm the tested installed source matches the changed checkout before relying
on tests importing the installed package.

Runtime completion requires all inventoried non-orchestrator behavior to have
cohesive class owners, obsolete forwarding exports to be retired, direct consumers
to use the new APIs, and preserved contracts to have relevant evidence. Review any
remaining function by its actual workflow responsibility. A zero count alone does
not establish class cohesion or justify new wrappers.

### Recorded review evidence

The following results were observed during the preceding read-only review at the
source revision recorded above, using the existing environment with CPython
3.14.7. All 25 installed runtime Python files were compared byte-for-byte against
the checkout and matched. These results predate remediation and do not validate
future changes.

| Command or inspection | Observed result |
| --- | --- |
| AST inventory of runtime Python | 62 module-level functions, 5 nested helpers, 109 classes, 23 classes with exactly one directly defined method |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/unit` | 291 passed; 3 performance cases deselected; 2.25 seconds |
| `.venv/bin/ruff check --no-cache src` | Passed |
| `.venv/bin/ruff format --check --no-cache src` | Passed; 26 files already formatted |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/alpha-governance-engineering-standards` | Passed |
| Working-tree inspection after review | Clean; no code changes |

Full `make check`, mypy, installed-wheel rebuilding/smoke, and performance cases
were not run as part of that review. Keep this baseline historical and append
new implementation evidence with its actual source state.

### Remaining automated enforcement

The current checker does not enforce orchestrator-only functions or class cohesion.
[test_python_standards.py](../../../tests/engineering/test_python_standards.py)
explicitly accepts a documented ordinary parsing function, and
[test_python_source_standards.py](../../../tests/engineering/test_python_source_standards.py)
also accepts ordinary synchronous/asynchronous functions. Passing those checks
does not prove OOP compliance.

The [roadmap enforcement work](../README.md#oop-migration-status) must update the
acceptance tests and address the full owned implementation scope without source
waivers, weakened checks, or changed upstream stub signatures. A syntax scanner
can identify bare/nested functions; actual workflow responsibility and class
cohesion still require review. Keep that repository-wide effort visible after
the runtime batches are complete.

## Runtime implementation and validation

Implemented on 2026-09-14 in the working tree based on the reviewed commit above.
No commit or push was performed. The pre-existing main-roadmap edit and this
untracked handoff were preserved and extended. The installed skill's suggested
`docs/coding_standards/documentation.md` does not exist at this revision; the
engineering guide's Documentation section is the owning source rule.

| Batch | Delivered ownership and consumer changes |
| --- | --- |
| 1 | C01/C02 record validation moved to their domain bases; shared `_ValidationMessages` owns only their matching error reader/schema/formatter. `_IdentityUuid` and `_IdentifierFields` share matching UUID and identifier mechanics without changing concrete model inheritance or public callback signatures. C03 retains its separate model/copy boundary, with `_DecimalArithmetic` owning exact grid operations and `Currency` owning validation/preset loading. Provenance, reference records and market-event owners retain their invariants. Catalog ordering methods bind a query-local index with `partial`; no query state is cached on the catalog. |
| 2 | `DomainCodec` owns deterministic JSON and exact domain hooks with instance-owned compiled-schema reuse. `MarketEventCodec` owns canonical `encode`, `decode` and `validate`. `BinancePayloadDecoder` owns source schemas, shared compiled source decoders, parsing and configuration indexing; `TardisDecoder.parse_capture_time` owns provider capture parsing. Consumers, curated exports and the maintained notebook use these APIs. |
| 3 | Removed both settlement forwarding APIs and package exports. Callers reuse `SettlementConventions`; the date selector is an instance method. `ExchangeCalendarsAdapter` owns source metadata and timestamp conversion. Tests explicitly account for constructor-before-call errors, while preserving service validation order and chained causes. |
| 4 | Complete configured source checks, installed-wheel consumption, notebook execution, byte parity and ownership review passed. The affected wheel-smoke implementation has an `_InstalledWheelCheck` owner; its `main` remains actual build/install workflow orchestration. |

The retained ID, event, numerical and window types remain distinct. The shared
formatter imports neither domain, and C01/C02 do not depend on each other. C03
`model_copy` still reconstructs and validates, while C01/C02 framework copies
remain trusted and unchecked. Exact arithmetic, currency definitions, event
tags, source extras/closed canonical schemas and timestamp policies are unchanged.
No temporary compatibility forwarding APIs were introduced.

Migration requires replacing imports of `encode_json`/`decode_json` with a reused
`DomainCodec`, and `encode_domain`/`decode_domain` callbacks with its static
methods. Replace canonical event functions with a reused `MarketEventCodec`.
Provider capture parsing is `TardisDecoder.parse_capture_time`; the source
`BinanceEnvelope` schema now lives with the payload adapter. Construct
`SettlementConventions(calendar)` before calling its methods. Invalid calendars
now fail before candidate/convention/lag arguments; valid service method order
is unchanged. Rollback reverts owners, consumers, exports, tests and documentation
together, without changing persisted wire bytes.

Initial verification observed 291 passed / 3 deselected before changes and again
after batches 1 and 3; batch 2's narrower codec/data/reference/currency selection
passed 106 tests. Strict mypy passed on 35 affected source/test/tool files and
the engineering checker passed. These intermediate runs precede the additional
codec-recovery and settlement-precedence regressions; final results follow here.

Development failures were diagnosed and corrected: initial hoists required Ruff
formatting/docstrings and typed callback adjustments; one identity error test
still patched its retired module helper and was migrated without changing its
assertions. One collection attempt raced concurrent uv package reinstallations
(12 import errors, 1 deselection); serializing environment-mutating uv commands
resolved it. No numerical golden was changed. Sandbox cache restrictions were
retried through the approved uv permission boundary. The first complete-lane
attempt found an inferred `Any` in a new invalid-copy test; an explicitly typed
update mapping fixed it. A final ownership review removed the now-redundant
`MarketEventRecord._validate_fields` forwarding layer, after which the affected
80 tests, full lane, byte comparison and notebook were rerun on the final source.

### Final tested state and results

Environment: CPython 3.14.7, macOS arm64, frozen uv environment. All 28 installed
runtime inputs (26 Python files, currency JSON and `py.typed`) matched the checkout
byte-for-byte. For the final uncommitted state, SHA-256 over sorted runtime
relative paths and contents, each separated by NUL, is
`b6f31706c9c12a2c8f9b74f61c19875ba3b2241197fa7bc49b388147f1cc947c`.
The unchanged `uv.lock` SHA-256 is
`1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d`.
The notebook records that same runtime identity and the source/input identities
of its executed cells. The recorded source is this working tree, not an assertion
that the original reviewed commit contains these changes.

| Command or inspection | Actual final result |
| --- | --- |
| `make check` | Passed. Ruff lint and format passed (68 files); strict mypy passed (67 files), native stubtest passed (1548 modules); engineering standards, dependency admission (72 packages), vulnerability coverage, Bandit and secret scan passed. The correctness lane ran **439 tests**, with **3 performance tests deselected**, no skips or failures. |
| Installed-wheel stage of `make check` | Built and installed a fresh runtime wheel with hash-checked dependencies outside the checkout. Isolated imports, exact Money JSON round trip, catalog decoding, Tardis disconnect/canonical event round trip, native calendar construction and dependency consistency passed; governance was absent from the consumer environment. The temporary wheel and environment were cleaned by the existing harness. |
| Final AST inventory and ownership review | **26 runtime Python files, 113 classes, zero module-level functions, zero nested functions, zero lambdas.** Private record/adapter methods and domain arithmetic/codec owners have concrete consumers. No cross-domain dependency was introduced by the shared formatter; provider framing remains separate from venue parsing. Counts supplement the ownership review. |
| `uv run --frozen --no-editable python /private/tmp/oop-runtime-validation/wire_parity.py` in a separately installed archive of the reviewed commit, then the same script with `/private/tmp/oop-runtime-validation/current-wire.json` in this checkout | **13 byte-identical original/migrated round trips**: instrument ID, dimension, currency, Money, Price, Tick, Quantity, FXRate, catalog and all four event tags. Catalog SHA-256 stayed `3125723d3760b4a35238b75a493e1d1e2a6956c66566ac7231c35a0afb59bad6`. The script checked installed/source equality in both environments. |
| Notebook command below | All cells passed in one fresh-kernel execution of the final source. Successful local snapshot: `examples/runs/research-foundations/a16632a1-3904-486e-ba97-e8a5ab9b2487.ipynb`; active outputs refreshed. The earlier successful snapshot `c84143d4-0fe3-4004-b751-0d9e2425f5ef.ipynb` is retained with its earlier runtime identity. |
| `make architecture-check` (inside `make check`), plus `uv run --frozen --no-editable python /private/tmp/oop-runtime-validation/document_checks.py` | All 17 `docs/**/*.md` documents passed. Explicit component-README link validation also passed, and its changed pipeline/codec snippet executed with a synthetic trade and exact round trip. The checker only discovers inline Markdown links outside code fences; changed links use that supported syntax. |
| `git diff --check` and caller/export search | Passed. Supported consumers no longer import the retired functions. The maintained notebook was updated; historical snapshots retain their original source. No numerical golden, dependency declaration, lock, release policy or repository-wide enforcement rule changed. |

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
```

Supplementary byte-comparison scripts, the baseline archive and JSON output are
local-only under `/private/tmp/oop-runtime-validation`; they are not a permanent
test harness or release bundle. The notebook and its run snapshots are also
ignored local files. Tracked behavioral tests and the configured wheel consumer
provide the maintained acceptance path. The final full lane covers the two new
codec recovery tests and the two parametrized constructor-precedence cases;
duplicate assertions on retired wrappers were removed while retaining service
goldens and explicit error-order assertions.

Runtime remediation is complete. Remaining work is the unrelated development
tooling/test/snippet migration and repository-wide OOP enforcement in the main
roadmap. Hosted Linux/macOS merged-result gates still apply before merge; they
were not run from this uncommitted task. The three diagnostic performance tests
were not requested by the correctness lane, and no latency claim is made.
QuantLib's existing development-only admission and release block remain in force.
No empirical research, live-source, deployment or release qualification is claimed.

## Prompt to start the runtime fixes

This is the original implementation handoff prompt, retained as scope history.
The implementation and its actual evidence are recorded above:

```text
Use $quant-implement-plan and $quant-implement-doc to implement the runtime OOP
remediation in docs/roadmap/oop-migration/README.md.

Read that README, the applicable repository instructions, the engineering guide,
and the linked domain contracts. Recheck the current tree against the recorded
review and preserve unrelated changes. Treat this as authorization to implement
the fixes, not only to propose a plan.

Work through runtime batches 1–4 in small verified changes. Move reusable free
functions and nested helpers to cohesive class owners, retire the settlement
forwarding APIs, and consolidate the duplicated C01/C02 error implementation.
Assess the optional UUID/identifier validation sharing against the actual diff.
Keep distinct domain types, errors, schemas, provider/venue decoders, and their
documented copy semantics. Avoid one-class-per-function conversions, generic
utility containers, composition wrappers, and extra per-event codec work.

Update affected callers, exports, tests, maintained examples, and documentation
together. Preserve numerical goldens, exact Decimal/Fraction behavior, wire
bytes, catalog identities, timestamp/provenance semantics, error contracts,
and repeat-call/failure isolation. Reuse behavioral evidence and add focused
regressions only where the changed boundary needs them.

Run the relevant configured checks and applicable final source/installed-wheel
validation. Record actual results and remaining gaps in the README and main
roadmap. Complete the authorized runtime scope without stopping at a plan or
requesting repeated confirmation for routine refactoring choices. Leave the
separate repository-wide tooling/test migration and OOP enforcement work pending;
do not claim global OOP completion. Do not commit or push unless I ask.
```
