# P1 implementation roadmap: first causal baseline

Owner: repository founder. Status: refined implementation plan as of 2026-09-14;
no P1 end-to-end result is claimed. The MR 00 specification and library-guideline
checkpoint merged in [PR 14](https://github.com/lixuanguang/alpha-research-lab-private/pull/14)
at `8b53d7507c313a96e1a31bc080839a60f9821ac6`. Cleanup C0 merged in
[PR 15](https://github.com/lixuanguang/alpha-research-lab-private/pull/15)
at `67b740197cdf27113fddd98030b32ba83ab2e59c`. MRs 01–62
remain **planned**. The [selected experiment](../research/p1-baseline.md)
continues to own the frozen economic assumptions.

The [capability milestone plan](capability-milestones.md) now owns delivery order
and integrated exits, including EDA, live capture and operation. Both plans use
the single MR 01–62 sequence: this page defines the core data and baseline
contracts, while the milestone plan defines their additional workflow/control
packages. The milestone table identifies the full range for each usable outcome.

This page turns [P1: first causal baseline](README.md#p1-first-causal-baseline)
into individually reviewable merge requests. The
[platform design](../architecture/platform-design.md) owns future architecture;
the [research program](research-program.md) owns hypothesis and selection
discipline. This page owns the concrete P1 library responsibilities, pipeline
composition and delivery dependencies. Follow the
[engineering guide](../coding_standards/README.md) and
[development workflow](../governance/workflow.md), including exact financial
arithmetic, strict typing, immutable validated records and the existing CI lane.

## Finish and scope

P1 finishes when one permitted, bounded raw sample can be acquired, resumed,
verified, normalized and published, then consumed causally by no-trade and one
transparent baseline to produce a reproducible net report. Another process must
reproduce the result using retained bytes, configuration and code identities.
Independent hand calculations must reconcile cash, positions, costs and NAV.

The founder selected the Tardis/Binance BTCUSDT spot case and one-minute
positive-return hypothesis in MR 00; the [owning specification](../research/p1-baseline.md)
fixes the sample, quantity, costs and timing before comparative results.
**Access, retention rights and historical eligibility/revision evidence remain
unresolved.** This source selection does not authorize controlled data access.
No-trade uses the same accounting as the single unlevered, long-or-flat baseline.

The selected pair and hypothesis are configuration for this experiment, not
special cases in shared implementation. Follow the
[generalization and activation standard](../coding_standards/README.md#generalized-code-and-configuration-driven-activation)
from the first consuming slice. Synthetic configurations may exercise another
compatible asset or strategy through the same code without changing the frozen
empirical case. P1 will support independent single-instrument, cash-funded spot
instances; broader mechanics require their own implemented capability.

This trade-price model needs neither book reconstruction nor an OMS. Fills are
declared simulation assumptions; trade prints do not establish executable prices,
spread, liquidity or queue priority. Depth decoding already works and remains
supported, but the selected P1 strategy does not consume depth. A future change
to provider, an order-book hypothesis, shorting, derivatives or multiple
currencies requires a versioned experiment and revised slices with the necessary
lifecycle work before implementation. Do not silently model it as cash-funded spot.

A negative net result can complete this engineering baseline. It does not prove
alpha, satisfy a future strategy-selection threshold or grant trading readiness.
Synthetic examples establish software properties; final permitted-source
acceptance is a separate requirement. P2 fitting/sweeps, P3 venue fidelity and
P4 operation remain outside this baseline's dependencies unless the selected
strategy requires a specific capability. M2 historical EDA and M5 deterministic
backtesting can advance while M3 live capture is built; neither waits for M4 models.

## Existing libraries and remaining work

| Boundary inspected | Existing capability | Remaining P1 work |
| --- | --- | --- |
| [C01](../architecture/instrument-identity.md), [C02](../architecture/venue-calendar.md), [C03](../architecture/financial-units.md) | Canonical IDs, temporal symbology, bounded calendars, exact `Currency`, `Money`, `Price`, `Quantity`, tick/lot arithmetic | Compose these contracts; do not recreate identifiers, clocks or money in notebooks. C01 valid-time mapping alone is not a knowledge-time universe selector. |
| [serialization.py](../../src/alpha_research/serialization.py) | Cached typed JSON codecs and exact financial values, including currency quantum | Reuse for actual new records; add their constructor/invariant checks and schema versions with their consumers. |
| [core/events.py](../../src/alpha_research/core/events.py) | `EventProvenance`, UTC normalization, source revision/sequence, knowledge/valid times, deterministic ordering and `is_available` | Cross-object ordering, correction admission and dataset-level as-of selection. No replacement provenance framework. |
| [reference_data.py](../../src/alpha_research/reference_data.py), [authored catalog](../../configs/reference/binance-spot.json) | Strict `SpotInstrument`/`CatalogSnapshot`, canonical snapshot hash and complete-interval resolution | Load run selections; add evidence-backed historical eligibility and required quantity rules. The catalog covers BTCUSDT/ETHUSDT for 2024-06-01 only and explicitly records research assumptions. |
| [data contracts](../data/contracts.md), [decoder context](../../src/alpha_research/data/decoders.py) | Frozen trade/depth/disconnect records and source lineage; strict canonical codecs | Raw requests, storage, request manifests, checkpoints, dataset identity/publication and quality reports. |
| [Tardis framing](../../src/alpha_research/data/providers/tardis/decoder.py), [Binance payload decoding](../../src/alpha_research/data/venues/binance/payloads.py) | One-line capture parsing, conservative submicrosecond rounding, configured symbol validation, payload mapping, blank-line disconnect proxies | C0 retains these libraries with direct caller composition. Add transport and multi-line streaming with actual pipeline consumers. A decoder is not a downloader or completeness check. |
| [pyproject.toml](../../pyproject.toml), [Makefile](../../Makefile), [CI](../../.github/workflows/ci.yml) | CPython 3.14.7, uv 0.12.7, strict source checks and installed runtime wheel checks | Add narrow public imports/runner coverage when introduced. Jupyter tooling is not in the project lock. |

There are no implemented strategy, simulation, accounting or run/report packages
at this revision. New paths below are **proposed**, not current imports or
commands. Create a module only with working behavior, tests and a concrete
consumer; names may change without changing the agreed contracts.

## P1 code ownership and call flow

Only orchestrator pipelines own workflow composition, following the
[library boundary rule](../coding_standards/README.md#orchestrator-pipelines-and-libraries).
Libraries implement parsing, validation, transformations, calculations and
bounded I/O contracts. They receive explicit inputs and may call other libraries
to fulfill those contracts; they do not select a run, construct its dependency
graph or import a pipeline. A class must own behavior, invariants or a useful
configuration lifetime. Wiring two existing classes together does not justify
another library class, even if more features might arrive later.

The target P1 artifact flow is:

```text
acquisition pipeline -> verified raw objects + acquisition manifest
dataset pipeline     -> those saved inputs -> immutable canonical snapshot
research pipeline    -> snapshot + frozen config -> trial record + net report
```

These are callable workflows in the existing package, not mandatory services.
Artifact arrows do not imply imports between pipelines. In particular, a saved
snapshot research run does not implicitly acquire or rebuild data. The names
below are proposed modules under `src/alpha_research/`; create each with its first
working workflow, not as an empty skeleton or a forwarding facade.

| Pipeline owner | Explicit inputs and result | Coordination owned here | First working slice and growth |
| --- | --- | --- | --- |
| `pipelines/acquisition.py` | Resolved data-job/universe bindings, validated requests, permitted access reference, destination and clock → verified raw objects and acquisition manifest | Construct/reuse the configured provider transport; select partitions; sequence fetch, verification and durable publication; record original clocks; apply bounded retry and restart policy; expose progress/failure. | MR 05 fetches/stores one partition; MR 06 adds resume; MR 07 adds the installed acquisition command. |
| `pipelines/dataset.py` | Saved request/raw manifest and verified objects, resolved universe/catalog, eligibility evidence and explicit normalization/quality policy → immutable snapshot | Construct/reuse configured decoders; iterate frames; bind occurrences; apply revision, eligibility and quality operations; assemble/publish the snapshot and expose its quality report. | MR 02 starts fixture inspection; MR 09 adds persisted occurrences; 10–15 complete publication; MR 16 adds the validated-dataset command. |
| `pipelines/research.py` | Resolved active strategy instances and saved input bindings, frozen strategy/execution parameters, seeds, trial and output locations → per-instance attempts and exact net reports | Select configured implementations; own each instance's decision clock, ledger and pending intent; sequence observations, decisions, fills, costs and valuation; record outcomes and publish results. | MR 44 executes callable synthetic runs sequentially; MR 45 adds durable reports; MR 46 adds argument parsing and an installed command entry point here. |

The library contracts consumed by those workflows are:

| Library responsibility | Meaningful operation and output | Consumer |
| --- | --- | --- |
| Configuration resolution | Read versioned definitions and explicit active selections; resolve implementation, reference and input bindings; validate capabilities and exact parameters; identify the resolved configuration. | Pipeline setup. This library does not construct collaborators or execute a workflow. |
| Request and reference selection | Validate a bounded request, resolve full-interval instrument mappings, identify exact partitions and evidence references. | Acquisition setup; dataset input validation. |
| Provider transport | Fetch one explicit partition with timeout and response validation; expose response bytes and receipt metadata. It does not select the next partition, retry the run or write the raw store. | Acquisition pipeline. |
| Raw objects, storage and manifests | Verify byte identity; atomically publish/reopen immutable bytes; validate and append manifest/checkpoint records. Workflow advancement remains in the caller. | Acquisition pipeline; dataset readers. |
| Tardis lines and `TardisDecoder` | Iterate verified bytes into ordered frames with source positions and explicit gap/proxy metadata; decode one frame's capture/provenance and delegate its payload. | Dataset pipeline. The line iterator does not construct a venue decoder. |
| `BinancePayloadDecoder` and event codecs | Validate/index the configured symbols once; parse Binance payloads into exact events; validate and serialize those records. | `TardisDecoder` through its existing payload contract; canonical data consumers. |
| Occurrence normalization and revisions | Bind a decoded event to request/partition/raw/line identity; resolve economic duplicates and justified corrections while retaining lineage and effective availability. | Dataset pipeline and snapshot readers. Normalization does not construct decoders. |
| Eligibility and quality | Read evidence-backed assertions; select membership bitemporally; validate coverage and normalized partitions with explicit accepted/rejected results. | Dataset pipeline and as-of reader. |
| Dataset manifests and snapshots | Validate semantic identity and references; atomically publish and reopen an explicitly identified snapshot. | Dataset publication; research input reading. |
| As-of selection and observations | Select known eligible revisions and derive completed observations from explicit cutoffs/windows with missing/stale status. | Research pipeline; strategy receives the resulting decision inputs. |
| Strategy configuration, context and rules | Resolve strategy/instance definitions and the frozen specification; compute a target from unit-bearing completed observations. | Research pipeline. A strategy does not read raw files, fetch prices, mutate the ledger or choose account limits. |
| Simulated risk decisions | Validate explicit intent, cash, holdings and pending commitments against supported bounds, without changing strategy parameters. | Research pipeline before fill evaluation; MR 42 supplies this contract. |
| Fills, costs, ledger and valuation | Evaluate a pending intent against an eligible event; cost an accepted fill; apply a pure state transition; mark and reconcile exact balances. | Research pipeline, which supplies and retains per-run state. |
| Trials and reports | Validate identities and append attempt records; serialize, publish and verify exact report artifacts. | Research pipeline, which decides when an attempt starts, fails or completes. |

This is an ownership map, not a class or file checklist. Keep closely related
functions together; introduce a record, protocol or module only with a real
operation and named consumer. File/transport persistence can be a reusable
library operation: only coordinating the overall workflow belongs in a pipeline.
Use a small declarative mapping to reviewed installed implementations for the
actual configured consumers. Do not add a decoder factory, registry service,
generic runner framework or composition subclass for this selected path.

### Configuration delivery and onboarding

The [planned configuration design](../architecture/platform-design.md#configuration-and-active-workflows)
separates reference/universe definitions, data jobs, strategy definitions,
instances and deployment authority. A catalog entry is never an instruction to run it.
Shared variables, operations and paths describe their roles; the BTCUSDT pair,
quantity, currency, selected rule and data binding live in the experiment config.
Venue-specific decoding and strategy-specific formulas retain meaningful names
and their own substantive library contracts.

- MR 01 introduces only the configuration records needed to select bounded data
  jobs/requests and resolve an immutable run manifest. MR 02 exercises its fixture
  consumer. MRs 05, 09 consume those bindings for acquisition and decoding.
- MR 34 extends the same boundary with strategy definitions, instances,
  parameters and required data bindings. Match strategy requirements to compatible
  data jobs/snapshots; collection may cover a wider independently selected universe.
  Deactivating a strategy does not disable an independently requested data job.
  MRs 35–36 supply compatible decision
  contracts and implementations; combine dependent declarations with their first
  working consumer where needed. Configuration cannot enable unfinished code.
- MR 44 composes only the explicitly active instances through a shared research
  path. MR 46 accepts an explicit config file and verifies installed entry-point
  resolution. The frozen comparison selects no-trade and return-momentum
  instances with independent cash and state; it is not a combined portfolio.

Use one supported file format and the existing exact typed codecs. Validate
references, periods, instrument units, parameter schemas and implementation
capabilities before workflow execution. Resolve the actual universe for the
selected data job or strategy instance rather than consuming every catalog entry.
Saved-snapshot research still performs no implicit acquisition or dataset build.
Retain immutable resolved manifests and implementation/reference identities with runs.

The bounded onboarding proof changes only config/reference fixtures to run the
same strategy on another supported synthetic instrument, then adds a compatible
test strategy entry point plus config without editing shared orchestration.
MR 21 adds a bounded different-family fixture at neutral query/replay interfaces;
MR 48 exercises overlapping inputs, two instances, failed/restarted state and
unsupported economic capabilities. These are interface/isolation proofs, not
production support for another instrument family or another empirical experiment.

### Existing abstractions to retain or retire

| Retained abstraction | Responsibility | Consumer contract |
| --- | --- | --- |
| C01/C02/C03, provenance, reference records, immutable market events and canonical codecs | Domain contracts and exact arithmetic. | Event bytes, validation failures, temporal semantics and configured-symbol support remain covered. |
| `TardisDecoder` | Source framing and provenance. | Reuse a configured instance across lines, including after rejected input. |
| `BinancePayloadDecoder` | Venue parsing and validated symbol configuration. | Supply it explicitly to the framing decoder; no provider-specific composition subclass. |
| Curated `data/__init__.py` exports | Public event, codec and retained decoder types. | External callers use this surface; internal modules use defining imports. |

C0 removes `BinanceTardisDecoder` and the compatibility-only `data/models.py`
and `data/venues/binance/decoder.py` modules. These imports are no longer
supported in the current candidate. Tests, installed-wheel smoke and the active
local notebook now use retained library types. Construct
`TardisDecoder(payload_decoder=BinancePayloadDecoder(instruments), source_id="tardis.binance.spot")`
at the caller, later in the dataset pipeline. See the
[working call example](../../src/alpha_research/data/README.md#pipeline-use).
Serialized events and historical notebook snapshots keep their original meaning.

### Consequential integration details

- `DecodeContext.provenance()` currently emits revision zero and an event ID
  containing source ID, source sequence and a payload suffix. The sequence is
  supplied by the caller and can restart in each file. Preserve this public
  decoder behavior; define collision-safe persisted occurrence identity before
  combining objects. A raw digest identifies bytes, not an economic trade.
- Decoded point events have a one-microsecond validity interval at capture time.
  `is_available(decision_time, decision_time)` is not a last-observation query.
  The observation builder must select eligible point events and separately
  enforce its observation window and maximum age.
- Historical capture time is the existing `source_capture` knowledge model;
  local receipt/ingestion occur when the archive is downloaded. Preserve both.
  A later correction must not inherit the original capture as its availability.
  Unknown correction history cannot establish historical knowability.
- The authored catalog was recorded in 2026 for a 2024 scenario. Changing its
  timestamps or labeling it historical would not establish point-in-time venue
  membership. Preserve it as an engineering fixture and obtain separate evidence
  for any empirical eligibility assertion.
- Persist original acquisition timestamps with raw manifests and reuse them on
  rebuild. New build/attempt timestamps belong to execution records, otherwise
  identical saved inputs would acquire a new dataset identity on each run.

## Merge size and review contract

The sequence describes behavior to deliver, with proposed MR boundaries. MR 00
and C0 are completed prerequisites; planned work uses MR 01–62 across both plans.
Branch from updated `main` after prerequisites merge; use
`codex/mr-<NN>-<topic>` for implementation branches unless another name is requested.
Follow the milestone dependency graph, subject to the source-evidence limits
below. MR IDs remain meaningful even when independent work advances
out of order. A row is not a requirement to create a separate file or class. Combine a
declaration with its first working consumer when separating them would leave
scaffolding; record the covered IDs in the actual MR.

Aim for **fewer than 150 changed production code lines per MR**. Count
added plus deleted code-bearing physical lines, excluding blank lines,
tests/fixtures, docstrings and comments. Imports, annotations, validators, codec
setup, public exports and executable tooling count. Report additions and deletions
separately, plus their sum, against the actual MR base; do not use net growth as
the review size. Report declarative configuration and dependency changes
separately so large behavioral changes cannot hide in excluded files.

Do not forecast per-row line ranges before the implementation is known. If a
slice exceeds the target, split at a useful boundary such as validated file reading
versus publication, with a usable/tested outcome on each side. Do not compress
code, remove validation, manufacture forwarding layers or commit a stub to hit
the count. A cohesive change slightly above the preference may be justified in
the MR description with its actual count and the reason a split hurts review.
For each slice, identify the operation, its actual caller, inputs/output and
state lifetime in the normal description. Review whether composition belongs
in one of the pipelines above and whether a proposed abstraction adds a contract
beyond forwarding. This needs no new registry, wrapper-count test or review form.

Every MR carries focused tests, applicable progress/failure telemetry and
recovery behavior with the capability it introduces, plus documentation,
the local notebook exercise below, and validation in the existing PR
template. Tests need not fit the production-line budget. The notebook does not
replace retained regression tests. New event/economic records follow the existing
frozen `msgspec.Struct`, cached codec and explicit validation requirements;
preserve foundation behavior and exact Decimal/Fraction rules. C0 explicitly
retires the construction/import APIs listed above; unrelated API changes require
their own concrete migration. Documentation-only refinements use the link and
semantic checks below without rerunning behavioral notebooks.

## Local notebook workflow

Use long-lived notebooks organized by research activity under repository-root
`examples/`, ignored by the root `/examples/` rule. On 2026-09-13 the founder
selected local retention and then activity-based notebooks, superseding both
the original temporary-directory/deletion requirement and one notebook per MR.
The [research program](research-program.md#notebook-research-and-package-promotion)
owns the boundary between exploratory ideas and maintained package behavior.

| Notebook responsibility | Intended contents | Package boundary as behavior matures |
| --- | --- | --- |
| Data fetching | Explore permitted source APIs, bounded requests, responses, clocks and acquisition quality. | Reusable clients, validation, immutable storage and resumable acquisition. |
| EDA | Inspect saved data, coverage, missingness, distributions, temporal alignment and candidate features. | Shared quality/feature transformations needed by retained consumers. |
| Quant strategy research | Prototype hypotheses, signals and models; compare scenarios, costs and attribution. | Versioned strategy logic, configuration, simulation/accounting and reproducible runners. |
| Strategy monitoring | Inspect saved or available runtime reports, exposures, P&L, data freshness and drift. | Persistent monitoring, metric definitions, alert delivery and operational controls when implemented. |

Use `examples/research-foundations.ipynb` as the working foundation example,
with editable scenarios, intermediate tables, findings and separate fixed
reference checks. Its local runner defaults to one execution and preserves
distinct successful or failed snapshots under ignored `examples/runs/`.
Split or move its sections into these activity notebooks as actual work grows;
do not create empty notebooks or fictional fetching/monitoring capabilities now.
Each MR names the notebook and relevant scenario/section it exercised. Notebook
lifetime follows the research activity, while package changes remain one bounded
MR at a time. MR 00 has merged; C0 is implemented in this candidate. MR 01 is
the next planned implementation slice.

1. Import the package APIs from the candidate installed by the frozen project
   environment, using the pinned interpreter. Keep notebook tooling in a
   separately identified development environment/kernel; do not silently change
   `uv.lock`, add runtime Jupyter dependencies or patch `sys.path`. Confirm the
   interpreter, package location and candidate identity before interpreting a
   result. Refresh the install/kernel after source changes.
2. Start with a tiny synthetic or permitted saved sample. Display meaningful
   intermediate objects/tables: clocks, identities, eligibility, observations,
   targets, fills, cash or report attribution. Exploratory transforms, signals,
   models and hand calculations may remain notebook-local while an idea is being
   evaluated. Reuse existing foundation APIs; promote mature shared behavior and
   selected strategy implementations into the package when they need retained
   consumers, regression coverage or reproducible execution outside a notebook.
3. Exercise the listed boundary failure, then restart the kernel and run all cells
   in order. Promote decisive cases into focused tests and small permitted
   fixtures. Record commands, identities, conclusions and limitations in the MR.
   Keep a retrievable protected reference for permitted raw data/bulk outputs.
4. Before **each commit, push and merge to main**, confirm notebooks, checkpoints
   and local exports stay under ignored `examples/`. Close finished execution
   kernels; notebooks may remain locally. After promotion, notebooks import the
   packaged implementation for formal comparisons and monitoring, retaining
   independent hand calculations only as explicit oracles. Preserve decisive
   cases in retained tests and research attempts outside mutable notebook output.
5. Inspect the staged diff and notebook paths. `git ls-files -- examples/ '*.ipynb'`
   must be empty; run `git check-ignore` on the actual notebook paths and confirm
   they are ignored. Stage explicit retained files; never force-add examples.
   Before push/merge, check the branch diff/history contains no example/notebook
   addition; a later deletion does not erase an earlier committed notebook.

Do not inspect a final holdout through a notebook. Synthetic learning exercises
are engineering work; any real-data attempt influencing hypothesis or parameter
selection must be retained, including failed/abandoned attempts. Before MR 43
implements the journal, use an append-only text record beside protected research
outputs with the [trial fields](research-program.md#small-records-and-artifacts).

## MR sequence

Dependencies identify required contracts under the
[milestone map](capability-milestones.md#completion-and-dependency-model);
they do not require parallel agents or stacked unmerged MRs.
`NB XX` identifies an MR's learning checkpoint in the relevant activity notebook;
it does not prescribe a separate notebook file. Python module paths below are
relative to `src/alpha_research/`; documentation paths are repository-relative.
Unlinked module names are proposed unless identified as existing above.

### C0. Remove redundant composition before adding consumers

**Implemented in the current checkpoint.** The composition-only class
and both compatibility import modules are removed. Retained callers and public
exports use the generic and venue libraries directly; no replacement factory,
wrapper or empty pipeline was added. MR 02 starts the fixture pipeline; MR 09
adds the persistent dataset workflow to it.

The existing tests exercise trade, depth snapshot, depth update and disconnect
behavior, invalid mappings, exact timestamps/identities and recovery after a
failed line. Installed-wheel imports and the active local foundation notebook
use direct composition. Serialized fixtures remain unchanged; historical
notebook snapshots retain their original code and environment identity.
**NB C0:** reuse one directly composed decoder across valid, invalid and
subsequent valid lines. This cleanup adds no acquisition or dataset functionality.

### A. Fix the experiment and acquire immutable inputs

| MR | Depends on | Owned behavior and consumer | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **00 — Freeze the bounded P1 case** | Current foundations | **Merged specification.** Added `docs/research/p1-baseline.md` as the owning experiment specification, recording the decisions below and a hand ledger before any comparison. | **NB 00:** decode a synthetic trade and disconnect, inspect all clocks and exact units, then show catalog interval rejection. Completion is an explicit selected scope and unresolved-access status, not a research result. |
| **01 — Resolve configured source requests** | 00, C0 | Introduce `configuration.py` with typed data-job/universe definitions and immutable resolved run manifests. `data/requests.py` derives bounded per-instrument requests from the selected provider, dataset/stream, pipeline, universe, half-open range and partition rule. Bind actual instrument/reference versions, policies and rights references; resolve complete intervals using `CatalogSnapshot`. Add strategy/deployment records with their consumers. | Unknown fields/references, unsupported source/product/mode combinations, invalid intervals and insufficient catalog coverage fail before source access. Equivalent resolved requests have stable identity; a changed underlying universe cannot hide behind the same config name. **NB 01:** select two supported instruments through config and inspect exact partitions; reject an unsupported family and incomplete interval. MR 02 supplies the runnable fixture consumer. |
| **03 — Describe and verify a raw object** | 01 | `data/raw_objects.py`: immutable object descriptor with SHA-256, byte size, request/partition identity, retrieval reference and original receipt/ingestion times; callable verifier for an existing saved file. | Hash the exact retained bytes, including compression where present. Mutation, truncation and a descriptor for another request fail. **NB 03:** verify a tiny local object, change one byte and observe identity failure. |
| **04 — Publish raw bytes durably** | 03 | `data/raw_store.py`: content-addressed write/read boundary, staging on the destination filesystem, durable completion and atomic publication. Reuse the verifier; preserve immutable existing objects. | Readers see complete verified objects only. Repeating the same write reuses bytes; a conflicting object is rejected. Interrupt before/after publication and reconcile the observable files. **NB 04:** inspect staging versus published state after injected failure. |
| **05 — Fetch one provider partition** | 01, 03–04 | `data/providers/tardis/transport.py` implements one bounded partition fetch with explicit timeout and response validation. Introduce `pipelines/acquisition.py` with working fetch/verify/store composition from the resolved data job and explicit clock/transport dependencies. Emit run/partition identity, progress and failure status from this first consumer. The first transport is Tardis; reject unsupported selections and verify current primary provider documentation during implementation. | Fake transport covers success, malformed/truncated response, auth failure and timeout through the pipeline. A smallest permitted source probe confirms actual endpoint/framing, retention and timestamp assumptions; a fake cannot close that boundary. **NB 05:** inspect a saved response through the retained decoders. Do not print credentials or label retained raw data as a validated dataset. |
| **06 — Resume the acquisition manifest** | 05 | `data/manifests.py` validates, reads and appends acquisition completion/checkpoint records. Extend `pipelines/acquisition.py` with sequential partition selection, restart and bounded transient retry/backoff. Advance only after verified raw publication; do not introduce a second acquisition wrapper in `data/`. | Restart skips verified completed partitions; missing/mutated completed objects fail. Failure after object publication but before checkpoint does not lose or duplicate observations. Auth/schema errors are terminal; exhausted transient retries leave an incomplete run. **NB 06:** interrupt a three-partition fake run and compare the resumed manifest with uninterrupted acquisition. |
| **08 — Read saved raw frames with explicit gaps** | 06 | `data/providers/tardis/lines.py`: bounded decompression/UTF-8 iteration over explicit verified objects and expected partitions. Emit ordered frames with stable zero-based positions, origin, blank-line lookahead and terminal interval-end proxy metadata for the dataset pipeline. Report missing partitions and disconnect intervals without constructing a decoder. This is saved-file iteration; M3 owns live capture. | Preserve source bytes and line order, including repeated captures and trailing blanks across object boundaries. A quiet interval is distinct from a missing object; a missing object is not an empty market. Truncation/invalid encoding fails. **NB 08:** inspect blanks at beginning/middle/end and an absent partition without inventing timestamps or padding prices. |

MR 00 must name the provider/access method and permitted use/retention, source
revision and capture semantics, exact sample range, universe and eligibility
evidence, quote currency, cadence/lookback/horizon, fixed quantity/lot and tick
assumptions, initial cash, maximum age/gap policy, fill delay/price rule, cost
rounding, fee and slippage assumptions, end-of-sample treatment, and the
transparent hypothesis. Record financing as explicitly inapplicable only for the
selected cash-funded, unlevered spot case; there is no implicit USD/USDT conversion.

Distinguish engineering samples from any future validation/holdout intervals.
This fixed baseline fits no parameters; training-only fitting, purge and embargo
are inapplicable only while that remains true. Any comparative tuning requires
the research program's split and trial discipline before it begins. Preserve
the declared acceptance even if observed results are poor.

MR 05 is the early source feasibility checkpoint. Source access is not assumed
by this roadmap. If it is unavailable, retain the exact unproven boundary and
continue synthetic/storage/accounting work that does not depend on it. Do not
mark permitted-source acquisition or P1 complete, purchase access, or substitute
an unapproved provider to obtain a pass.

### B. Build a causal, versioned dataset

| MR | Depends on | Owned behavior and consumer | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **09 — Bind decoded events to raw occurrences** | 08, 02 | `data/normalization.py` binds a decoded event and explicit raw origin into an occurrence envelope identifying request partition, raw digest and line position. Extend `pipelines/dataset.py` from fixture inspection to persisted input: resolve the data-job decoder binding/universe, reuse framing/payload decoders, iterate frames and bind occurrences. The first binding composes `TardisDecoder` with `BinancePayloadDecoder`. Retain exact bytes and original provenance. | Two files starting at sequence zero cannot collide. Saved-input rebuilds and identical retries reproduce occurrence identities. Reject incompatible bindings; an unselected catalog instrument is not implicitly admitted. Keep occurrence identity separate from the venue trade key used in MR 10. **NB 09:** trace two colliding local sequences to their raw bytes; retain failures with job/partition identity. |
| **10 — Admit duplicates and corrections explicitly** | 09 | `data/revisions.py`: resolve economic duplicates by source/venue/instrument/stream/trade ID for the selected trade representation; record conflicting payloads, revision linkage and correction publication/availability beside original occurrences. The dataset pipeline supplies occurrences and explicit correction evidence/policy. | Exact duplicates retain all lineage and contribute once. Conflicts without justified revision ordering/availability fail publication. Known corrections append versions; effective knowledge is no earlier than original capture and correction availability. **NB 10:** add a late correction and show the earlier version remains reconstructible. Positional IDs alone cannot match revisions after inserted lines. |
| **11 — Read historical eligibility assertions** | 00–01 | `data/eligibility.py`: strict file-backed assertions for canonical instrument, valid interval, knowledge time, included/excluded state, reason and evidence identity. Validate linkage to the selected catalog/units without changing its authored meaning. | Reject missing evidence, overlapping contradictory assertions and invented knowledge dates. Preserve excluded/delisted members. Synthetic assertions are labeled as such. **NB 11:** compare a 2026-authored assumption with an assertion actually evidenced as known during the sample. |
| **12 — Select the universe as of a decision** | 11 | Extend `data/eligibility.py` with pure bitemporal selection and explicit unknown/unsupported outcomes. Use validity and knowledge independently; append corrections rather than rewriting history. | A later listing correction/exclusion cannot change an earlier universe. Unknown membership cannot silently become eligible. **NB 12:** display inclusion before/at/after both knowledge and validity boundaries, including the half-open endpoint. |
| **13 — Validate a canonical partition** | 09–12 | `data/quality.py`: consume occurrences and declared-use policies; check schema, identity/units, timestamps, revisions, coverage, duplicate disposition and ordering. Produce canonical bytes plus accepted/rejected outcome, quality scope and reasons; distinguish admissible degraded use from valid data. The dataset pipeline reports invalid/gap counts and routes failures before publication. | Invalid records and unresolved required coverage/eligibility never become valid data. Retain exclusions and reasons; no silent row drops, zero/forward fill or fabricated completeness. Same inputs/policies reproduce the partition. **NB 13:** inject a duplicate, gap, wrong instrument and conflicting correction, inspect the report and demonstrate publication refusal. Advanced statistical quality analysis is not needed to meet these basic checks. |
| **14 — Validate and identify a dataset manifest** | 13 | `data/datasets.py`: versioned manifest reader/identity over ordered partition digests, raw manifests, resolved job/universe/catalog/eligibility identities, normalization code/schema and quality/correction/availability policy. Verify referenced files and declared quality/use scope. The dataset pipeline assembles these inputs from admitted partitions. | Equivalent saved inputs rebuild the same identity; a policy/schema/reference change changes identity. Missing bytes and unknown versions fail; a mutable config/universe name cannot substitute for its resolved content. Keep build wall-clock/path metadata outside semantic identity. **NB 14:** rebuild twice, then change one policy and compare hashes. |
| **15 — Publish and reopen one snapshot atomically** | 14 | `data/snapshots.py`: stage verified partitions/manifest, publish the immutable snapshot as one visibility boundary, and reopen by explicit snapshot ID. Use existing raw-publication primitives only where semantics match. Complete the dataset pipeline by calling this publication operation and returning the snapshot identity. | An interrupted build exposes no partial snapshot. Prior snapshots remain readable after failure and publication of a new one. Never silently resolve a mutable latest tag in a run. **NB 15:** fail before publication, inspect reader behavior, then reopen the completed snapshot. |
| **17 — Read point events as of a cutoff** | 10, 12, 15 | `data/asof.py`: select known revisions/eligible events from an explicit snapshot and business/decision window, preserving distinct event, availability and ingestion clocks. Define ordering from effective knowledge, stable partition identity and source order with deterministic tie-breaks. This is the reference contract for M2 query/replay adapters. | Filter availability before latest-revision selection; event-time-only joins and later corrections cannot bypass the cutoff. Same snapshot without the proper knowledge filter is reproducible but not causally valid. **NB 17:** compare equal captures, late publication, future corrections and universe changes at a fixed cutoff. |
| **33 — Build completed observations at a fixed cadence** | 17, 19 | `research/observations.py`: derive trade-price observations and preceding return from bounded query batches and explicit half-open windows. Carry lineage, availability and staleness; emit missing/invalid status. This small deterministic operation needs neither the full M4 feature pipeline nor a fitted model. | A decision sees only completed, then-available observations. Newer-but-late events are unavailable; later changes cannot revise an already emitted input. Require enough valid observations; no future/backfill imputation. **NB 33:** show warm-up, a late trade and a stale/disconnected interval through the shared data-access contract. |

Persisted event revisions may carry the current decoder output in an envelope
instead of widening every public event type. The envelope owns occurrence and
revision metadata. Whichever representation is implemented, all dataset
consumers must use its effective availability and revision identity. Never leave
an easy reader path that drops the correction metadata. Preserve raw versions;
where the selected source cannot establish prior revision availability, reject
that empirical claim or explicitly bound the experiment to supported data.

Canonical publication retains earlier event/reference revisions and their
exclusion annotations. Do not prune them using the final sample date's universe
or latest corrected value: the as-of reader needs them to reconstruct earlier
decisions. Coverage checks report what the provider's stream contract can prove;
neither nonempty files nor an assumed consecutive trade ID prove completeness.

The snapshot is a small local file format, not a catalog service or table platform.
Use existing codecs and streaming files first. Add a dataframe/storage dependency
only for a concrete consumer with normal dependency admission; do not bundle it
into a nominally small MR without counting its integration and review scope.

### C. Make decisions and reconcile exact economics

| MR | Depends on | Owned behavior and consumer | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **34 — Resolve active strategy configurations** | 00–01, 05, 09 | Extend `configuration.py` with strategy definitions and distinct instances/state namespaces. Bind exact strategy/version, canonical instruments, named dataset/data-job dependencies and typed cadence/horizon, quantity, capital and execution/cost parameters. Preserve many-to-many bindings and independently configured collection universes. Validate rule parameters with MRs 35–36 and freeze resolved identities. | Duplicate instances/namespaces, missing bindings, unsupported mechanics and unsafe parameters fail. Empty selection never enables all definitions. Two instances may share matching inputs without sharing state. **NB 34:** deactivate one instance while another consumer and an independent collection job retain their bindings; reject missing data and attempted trading authority in research config. |
| **35 — Define decision context and typed targets** | 33–34 | `strategies/contracts.py`: typed entry-point contract and immutable context binding instance/run/state namespace, strategy/version, instrument and data/config identities, explicit clock and seed. The supported P1 output is target quantity/time/horizon/lineage, not a universal contract for all future quoting or execution strategies. | Context cannot silently change dataset or another instance's state. Units belong to the selected instrument; expiry/time are explicit. Seed is retained even when unused. **NB 35:** round-trip context/target and reject another instrument's quantity or unsupported output contract. |
| **36 — Implement no-trade and the transparent rule** | 35 | `strategies/no_trade.py` and `strategies/return_momentum.py`: pure decision functions and rule parameter validation under the shared contract. Use the context's instrument and configured cadence/quantity; produce zero or the configured fixed quantity. Resolve these installed entry points through config definitions. No fitting, parameter search or notebook-owned signal calculation. | No-trade always stays flat. Hand examples cover positive/zero/negative return, warm-up and invalid/stale observations using the frozen policy. Same context reproduces decisions, independent of invocation order. Unsupported parameter/contracts fail resolution. **NB 36:** display inputs beside targets for two compatible synthetic instruments and perturb future observations without changing the frozen empirical case. |
| **37 — Select a causally delayed simulated fill** | 17, 34–36 | `simulation/fills.py`: exact immutable simulated fill record and the selected full-fill price rule. Evaluate an explicit pending intent and causally admitted event; return a fill, pending or expiry/rejection outcome. The research pipeline supplies events in order so a target delta uses the first eligible subsequent trade after the positive delay, within its horizon; retain decision and price-event identities. | No same-observation fill. Price event and its effective availability meet the delay; source quantity does not imply available liquidity. Missing/stale/gapped prices expire or reject according to the frozen policy. **NB 37:** show decision, earliest-fill and actual-fill times, including equal-time and no-price cases. |
| **38 — Compute fees and adverse price costs** | 37 | `simulation/costs.py`: versioned quote-currency fee and declared adverse slippage rules using C03 arithmetic/rounding. Preserve reference and effective fill prices and signed trade quantity. | Buy and sell fees reduce NAV; adverse slippage worsens both sides. Zero cost gives exact gross parity. Wrong currency, negative unsupported fee and nonfinite values fail. **NB 38:** hand-calculate one buy and one sell with nonzero costs and inspect rounding. |
| **39 — Establish bounded ledger state** | 34, 37 | `accounting/state.py`: immutable validated single-instrument cash/position/cost-basis state, initialized from explicit cash and zero holdings. Use existing `Money`/`Quantity` values and expose working initialization/validation. | Reject inconsistent instruments/currencies, unsupported negative cash/holdings and unsafe copies. This is an economic position, not a portfolio weight. **NB 39:** inspect initialized balances and show a unit-mismatched state fails. |
| **40 — Apply a costed fill exactly once per run** | 38–39 | `accounting/ledger.py`: pure ledger transition for buys/sells, exact fee cashflows, cost basis and realized P&L; retain applied fill identity in the bounded run state. | Repeated fill ID cannot change cash/position twice. Buy, partial sell, full sell, oversell and insufficient-cash cases follow explicit rejection rules. No external deposits are invented. **NB 40:** reconcile each step of the hand ledger below, then repeat a fill. Durable account recovery remains P3 work. |
| **41 — Mark NAV and reconcile gross to net** | 17, 38, 40 | `accounting/valuation.py`: exact point-in-time marking, unrealized P&L and attribution for the same accepted quantities against reference/effective prices. Record fees, slippage and applicable financing separately. | Ending NAV equals cash plus marked position and reconciles to initial NAV plus net P&L. No double subtraction of slippage already embedded in fills. Stale/missing marks invalidate the valuation; terminal open holdings are marked, not magically liquidated. **NB 41:** reconcile flat and open-position cases and zero-trade/zero-cost variants. |

The research pipeline will own a single outstanding target intent per instance.
The frozen MR 00 policy skips new intents while one is pending. Derive quantity deltas from actual
holdings, apply no-trade and rejection policies consistently, and test this
interaction when composing the pipeline. Do not add partial-fill, margin or OMS
machinery to simulate unsupported precision.

### Independent accounting example

This synthetic example is a test oracle, not a Binance price, fee schedule or
chosen strategy configuration. Use one arbitrary instrument, one quote currency
with quantum `0.01`, initial cash `1000.00`, quantity `2`, and fee rate `0.001`.
Reference prices are `100.00` and `110.00`; adverse slippage of `0.50` per unit
produces a buy at `100.50` and sell at `109.50`. Round each fee half-up to `0.01`.

| Event | Cash change | Cash | Position | NAV / reconciliation |
| --- | --- | --- | --- | --- |
| Start | — | 1000.00 | 0 | NAV 1000.00 |
| Buy 2 at 100.50; fee 0.20 | -201.20 | 798.80 | 2 | At mark 105.00: NAV 1008.80 |
| Sell 2 at 109.50; fee 0.22 | +218.78 | 1017.58 | 0 | Final net P&L 17.58 |
| Attribute the round trip | — | — | — | Reference gross 20.00 - slippage 2.00 - fees 0.42 = net 17.58 |
| No-trade from the same initial cash | 0.00 | 1000.00 | 0 | Zero turnover, costs and P&L |

For the open position after the buy, reference gross marking P&L is `10.00`,
slippage is `1.00` and fees are `0.20`, giving net `8.80`. Specify separately how
cost basis treats fees so realized plus unrealized attribution remains consistent.
Costed/reference attribution uses the same accepted quantities; it is not a
separately resized zero-cost strategy. No annualized ratio is necessary to prove
this example, and absent observations must not produce fabricated zero returns.

### D. Record attempts and reproduce the report

| MR | Depends on | Owned behavior and consumer | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **43 — Persist append-only trial attempts** | 14, 34–36 | `research/trials.py`: semantic run identity from source commit, lock/environment, resolved active config, instance/implementation versions, reference/data bindings and seed; distinct attempt ID; append-only start/completion/failure records under an explicit single-writer local policy. Retain resolved non-secret configuration alongside its identity. | Repeating the same inputs retains semantic identity but creates another attempt. Changed config/data/code cannot overwrite history. A crash leaves a visible incomplete attempt; startup identifies it, and a truncated tail is reported without erasing prior records. **NB 43:** append success, failure and interrupted attempts and inspect retained history. |
| **44 — Compose configured causal runs** | 15, 17, 33–41, 43, 19, 42 | `pipelines/research.py`: resolve instances/saved bindings and compose bounded queries, cadence/clock, configured decisions, independent simulated risk checks, delayed fills, costs, ledger and valuation. Execute sequentially with isolated ledger/pending state and frozen tie order. Journal starts/outcomes and expose per-instance progress/failure. No shared strategy-name switch or forwarding runner is needed. | Compare no-trade/return-momentum through the same economic path. Compatible asset or strategy additions change config/reference fixtures or strategy code only. Inactive instances never execute; failures cannot leak state. Pin tie order, pending policy and expiry; rejected risk or incomplete valuation cannot become a successful fill/report. **NB 44:** inspect traces and rerun after failure; MR 48 broadens isolation proof. |
| **45 — Save the net report and durable references** | 41, 43–44 | `research/reports.py` owns versioned exact report serialization and atomic output persistence. Include instance/implementation/config/input identities, initial/final cash, positions/NAV, gross/net P&L, fees/slippage/financing, turnover, fill/decision counts, coverage and assumptions. Extend the research pipeline to publish each report, append its digest references and complete its trial only after durable publication. | Report totals match that instance's retained ledger/trace; independent trial NAVs are not combined into portfolio NAV. Refuse clobbering another result; incomplete output is never a completed trial. Missing bytes or digest mismatch fail reproduction. **NB 45:** reopen a saved report and reconcile totals; tamper with an output and show rejection. |
| **46 — Add the reproducible command and installed consumer** | 45 | Add argument parsing with a required config file, explicit saved-input/output resolution and exit handling in `pipelines/research.py`, with an installed entry point targeting that module. The config selects active instances and implementations; no hidden pair, strategy or working-directory default. Reuse the callable workflow and save the actual command and resolved identities. Extend the existing wheel smoke for the new public consumer. | From a fresh process outside the checkout, install the candidate wheel and reproduce configured synthetic reports from saved inputs, without notebooks, editable imports or a network fetch. Verify installed strategy resolution and config-only activation changes. Unsupported/missing bindings fail before a run; an active-instance failure produces a nonzero exit and retains its outcome. **NB 46:** compare fresh-process output with the callable results; execute the command independently as retained acceptance proof. |
| **49 — Close P1 with a permitted saved sample** | 05–06, 08–15, 17, 33–41, 43–46 | Acceptance tests, documentation and retained evidence. Run the frozen case on the permitted source and retain the request/raw/canonical/report identities and protected retrievable bytes. Update the owning experiment, this status and the roadmap after acceptance. | Resume actual acquisition, rebuild the snapshot and reproduce the report in another process using saved inputs. Hand-reconcile a bounded ledger excerpt; audit the selected source availability/eligibility assumptions and keep failures/limits. **NB 49:** explain the end-to-end trace and cost attribution, keeping the notebook under ignored `examples/`. Any product defect is fixed in its owning small MR before claiming completion. |

Run identity excludes attempt timestamps and local output paths. Report comparison
uses canonical economic bytes/values; operational attempt metadata may differ.
Retain the lock, interpreter/platform, code and input bytes needed to recreate the
environment. A hash with missing or inaccessible content is not reproduction.
Do not hash the final output into an input identity or make a trial ID depend on
its own serialized completion record.

The planned CLI has no current verified invocation. MR 46 must add its tested
command and prerequisites to the [development index](../README.md). Local
installed-wheel acceptance is development evidence; the existing
[dependency/release restriction](../architecture/README.md#dependency-and-release-boundaries)
still applies and does not become a P1 deployment task.

## Validation, evidence reuse and reversal

During each MR, run changed-path Ruff checks and the configured strict typing for
the affected source/consumers, plus focused behavioral tests. Run the engineering
checker when source rules change or new source is introduced. Keep tests in the
owning mirrored tree: shared data under `tests/unit/data/`, provider-specific tests
under `tests/unit/data/providers/tardis/`, and new components under their matching
`tests/unit/<component>/` directories. Select affected integration cases explicitly;
the default pytest selection excludes integration/performance cases.

The retained hosted merged-result lane must pass before merge. Local `make check`
reproduces that lane when needed; this plan does not add a full local suite run to
every notebook iteration or waive any hosted gate. For documentation-only slices,
check local links and semantic accuracy. The architecture command discovers only
`docs/**/*.md`; explicitly include changed component READMEs in link validation.

Use the cheapest sufficient evidence for the boundary:

- Pure types, timing, selection and accounting: small deterministic examples and
  focused negative/round-trip tests; add future-perturbation tests at the actual
  selector/runner boundary, not only at a record constructor.
- Raw transport: injected failures plus the bounded real source probe in MR 05.
  Persistence: interrupt at the specific publication/checkpoint boundaries in
  MRs 04, 06, 15. These catch behaviors that a prebuilt fixture bypasses.
- Final composition: one synthetic fresh-process installed-wheel reproduction in
  MR 46 and one permitted saved-input acceptance in MR 49. No universal network,
  performance, venue or operating-system matrix is introduced beyond existing CI.

Record tested commit/candidate state, exact command, input/config identities,
passes/failures/skips, notebook findings/local ignore verification and material limits in each MR.
For an uncommitted notebook iteration, identify the base commit and candidate
diff/content digest; the base commit alone does not identify modified code.
Final reproduction uses the retained committed implementation and its lock.
After a failure, first distinguish product, fixture/harness, source/data,
environment and access. Retry an expensive run only after a specific correction
or changed prerequisite; retain the initial failure and the successful rerun.

Reuse evidence for unchanged contracts. A change to timing, correction policy,
eligibility, observations, fills, costs or accounting requires renewal of affected
downstream datasets/results. A changed reporter need not redownload immutable raw
inputs. New wheel bytes require the affected installed-consumer proof, not every
previous live probe. Do not consume a holdout again as an unexplained rerun.

Each MR should be independently revertible before dependent consumers merge.
After consumers exist, revert the dependent slice as well or select a compatible
prior config/snapshot/code set. Preserve old raw objects, manifests and trial
history; unknown schema versions fail visibly. Do not delete data to make a
rollback appear successful. No service migration or trading rollback is implied.

## P1 acceptance map

| Roadmap requirement | Implemented foundation reused | MRs closing the remaining gap | Decisive final evidence |
| --- | --- | --- | --- |
| Configuration and onboarding | Typed codecs, canonical IDs, configured decoder inputs | 01, 05, 09, 34–36, 43–46; 02, 21, 48 | Scoped data jobs and instances preserve immutable resolved identity; compatible additions leave shared orchestration unchanged. Multiple instruments/instances and explicit unsupported-family boundaries are exercised. |
| Time and event identity | `EventProvenance`, decoder capture/sequence semantics | 08–10, 12, 17, 33 | Late publication/corrections, equal timestamps, UTC boundaries and future-universe changes cannot alter earlier decisions. |
| Raw ingestion | Tardis/Binance decoding | 00–01, 03–06, 08, 07 | Permitted source probe plus installed, observable interrupted/resumed acquisition and mutated-object rejection. |
| Canonical dataset | Exact events, authored catalog, codecs | 09–15, 17, 33; 16, 18–20 | Repeatable atomic snapshot with lineage, eligibility, exclusions and as-of selection; bounded queries/replay preserve those semantics. |
| Strategy input/output | Canonical IDs and units | 34–36 | Same immutable context gives the same unit-bearing target; changed configuration gives another identity. |
| Baseline accounting | C03 exact values/rounding | 37–41, 44, 42 | Buy/sell/open/no-trade goldens and exact gross-to-net cash/position/NAV reconciliation with independent supported risk checks. |
| Run and report | Frozen build and installed imports | 43–46, 49, 47–48 | Retained attempts/selection controls and retrievable inputs reproduce the net report; failed/restarted instances do not corrupt peers. |

Mark P1 complete only when all seven rows have actual passing evidence for the
assembled candidate and selected permitted source. Preserve the reported source,
capture, universe and simulated-fill limitations. If historical eligibility or
source revision availability cannot be established, the engineering path may be
complete while the empirical causal baseline remains incomplete.
