# P1 implementation roadmap: first causal baseline

Owner: repository founder. Status: proposed implementation sequence; no P1
end-to-end result is claimed. Prepared on 2026-09-11 on `p1-roadmap`, based on
`main` at `f9cee2819eaa6c2a3e8ab47220922f566bff16f5`. After fetching `origin`,
`origin/main` matched that commit. MR 00 is **ready for review** on
`codex/p1-00-baseline-spec`; MRs 01–28 remain **planned**. See the
[selected experiment](../research/p1-baseline.md) and
[MR 00 validation record](../research/p1-mr-00-review.md).

This page turns [P1: first causal baseline](README.md#p1-first-causal-baseline)
into individually reviewable merge requests. The
[platform design](../architecture/platform-design.md) owns future architecture;
the [research program](research-program.md) owns hypothesis and selection
discipline. Follow the [engineering guide](../coding_standards/README.md) and
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

This trade-price model needs neither book reconstruction nor an OMS. Fills are
declared simulation assumptions; trade prints do not establish executable prices,
spread, liquidity or queue priority. Depth decoding already works and remains
supported, but the proposed P1 strategy does not consume depth. If MR 00 selects
another provider, an order-book hypothesis, shorting, derivatives or multiple
currencies, revise the affected slices and add the necessary lifecycle work
before implementing that choice. Do not silently model it as cash-funded spot.

A negative net result can complete this engineering baseline. It does not prove
alpha, satisfy a future strategy-selection threshold or grant trading readiness.
Synthetic examples establish software properties; final permitted-source
acceptance is a separate requirement. P2 fitting/sweeps, P3 venue fidelity and
P4 operation remain outside this sequence unless the selected baseline requires
a specific dependency.

## What main already supplies

| Boundary inspected | Existing capability | Remaining P1 work |
| --- | --- | --- |
| [C01](../architecture/instrument-identity.md), [C02](../architecture/venue-calendar.md), [C03](../architecture/financial-units.md) | Canonical IDs, temporal symbology, bounded calendars, exact `Currency`, `Money`, `Price`, `Quantity`, tick/lot arithmetic | Compose these contracts; do not recreate identifiers, clocks or money in notebooks. C01 valid-time mapping alone is not a knowledge-time universe selector. |
| [serialization.py](../../src/alpha_research/serialization.py) | Cached typed JSON codecs and exact financial values, including currency quantum | Reuse for actual new records; add their constructor/invariant checks and schema versions with their consumers. |
| [core/events.py](../../src/alpha_research/core/events.py) | `EventProvenance`, UTC normalization, source revision/sequence, knowledge/valid times, deterministic ordering and `is_available` | Cross-object ordering, correction admission and dataset-level as-of selection. No replacement provenance framework. |
| [reference_data.py](../../src/alpha_research/reference_data.py), [authored catalog](../../configs/reference/binance-spot.json) | Strict `SpotInstrument`/`CatalogSnapshot`, canonical snapshot hash and complete-interval resolution | Load run selections; add evidence-backed historical eligibility and required quantity rules. The catalog covers BTCUSDT/ETHUSDT for 2024-06-01 only and explicitly records research assumptions. |
| [data contracts](../data/contracts.md), [decoder context](../../src/alpha_research/data/decoders.py) | Frozen trade/depth/disconnect records and source lineage; strict canonical codecs | Raw requests, storage, request manifests, checkpoints, dataset identity/publication and quality reports. |
| [Tardis framing](../../src/alpha_research/data/providers/tardis/decoder.py), [Binance composition](../../src/alpha_research/data/providers/tardis/binance.py) | One-line capture parsing, conservative submicrosecond rounding, configured symbols, blank-line disconnect proxies | Actual transport and multi-line streaming. A decoder is not a downloader or completeness check. |
| [pyproject.toml](../../pyproject.toml), [Makefile](../../Makefile), [CI](../../.github/workflows/ci.yml) | CPython 3.14.7, uv 0.12.7, strict source checks and installed runtime wheel checks | Add narrow public imports/runner coverage when introduced. Jupyter tooling is not in the project lock. |

There are no implemented strategy, simulation, accounting or run/report packages
at this revision. New paths below are **proposed**, not current imports or
commands. Create a module only with working behavior, tests and a concrete
consumer; names may change without changing the agreed contracts.

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

Each numbered row is one proposed MR into `main` after its prerequisites have
merged. Branch from that updated `main`; use `codex/p1-XX-<topic>` for subsequent
implementation branches unless another name is requested. `p1-roadmap` contains
this planning change only. Implement in numerical order by default.

Aim for **fewer than 150 changed production code lines per MR**. Estimates below
count added plus deleted code-bearing physical lines, excluding blank lines,
tests/fixtures, docstrings and comments. Imports, annotations, validators, codec
setup, public exports and executable tooling count. Report additions and deletions
separately, plus their sum, against the actual MR base; do not use net growth as
the review size. Report declarative configuration and dependency changes
separately so large behavioral changes cannot hide in excluded files.

The ranges are planning estimates, not measured implementation sizes. If a slice
exceeds the target, split at a useful boundary such as validated file reading
versus publication, with a usable/tested outcome on each side. Do not compress
code, remove validation, manufacture forwarding layers or commit a stub to hit
the count. A cohesive change slightly above the preference may be justified in
the MR description with its actual count and the reason a split hurts review.

Every MR carries focused tests and documentation for the behavior it introduces,
the local notebook exercise below, and validation in the existing PR
template. Tests need not fit the production-line budget. The notebook does not
replace retained regression tests. New event/economic records follow the existing
frozen `msgspec.Struct`, cached codec and explicit validation requirements;
preserve the existing foundation APIs and exact Decimal/Fraction rules.

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
MR at a time. MR 00 still stops for review before MR 01 begins.

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
selection must be retained, including failed/abandoned attempts. Before MR 24
implements the journal, use an append-only text record beside protected research
outputs with the [trial fields](research-program.md#small-records-and-artifacts).

## MR sequence

Dependencies identify required contracts; numerical order is the straightforward
implementation path, not a demand for parallel agents or stacked unmerged MRs.
`NB XX` identifies an MR's learning checkpoint in the relevant activity notebook;
it does not prescribe a separate notebook file. Paths are relative to the
repository root and are proposed unless linked in the current-state table.

### A. Fix the experiment and acquire immutable inputs

| MR | Depends on | Proposed change and production-line estimate | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **00 — Freeze the bounded P1 case** | Current foundations | **0 code.** Add `docs/research/p1-baseline.md` as the owning experiment specification. Record the decisions below and a hand ledger before any comparison. | **NB 00:** decode a synthetic trade and disconnect, inspect all clocks and exact units, then show catalog interval rejection. Completion is an explicit selected scope and unresolved-access status, not a research result. |
| **01 — Load a bounded source request** | 00 | **80–130.** `data/requests.py`: strict request record/reader for the chosen provider, stream, instrument, half-open range and deterministic partition rule. Bind catalog identity and rights-record reference; resolve the whole requested interval using `CatalogSnapshot`. | Wrong symbols, empty/reversed intervals, unsupported streams and insufficient catalog coverage fail before I/O. Equivalent requests have stable identity. **NB 01:** load the selected request and inspect exact partitions; reject a range crossing catalog coverage. |
| **02 — Describe and verify a raw object** | 01 | **80–130.** `data/raw_objects.py`: immutable object descriptor with SHA-256, byte size, request/partition identity, retrieval reference and original receipt/ingestion times; callable verifier for an existing saved file. | Hash the exact retained bytes, including compression where present. Mutation, truncation and a descriptor for another request fail. **NB 02:** verify a tiny local object, change one byte and observe identity failure. |
| **03 — Publish raw bytes durably** | 02 | **100–140.** `data/raw_store.py`: content-addressed write/read boundary, staging on the destination filesystem, durable completion and atomic publication. Reuse the verifier; preserve immutable existing objects. | Readers see complete verified objects only. Repeating the same write reuses bytes; a conflicting object is rejected. Interrupt before/after publication and reconcile the observable files. **NB 03:** inspect staging versus published state after injected failure. |
| **04 — Fetch one provider partition** | 01–03 | **100–140.** `data/providers/tardis/acquisition.py` if Tardis is selected: one bounded transport call into the raw store, explicit timeout and narrow injected transport/clock. Validate request construction and response framing against current primary provider documentation during implementation. | Fake transport covers success, malformed/truncated response, auth failure and timeout. A smallest permitted source probe confirms actual endpoint/framing, retention and timestamp assumptions; a fake cannot close that boundary. **NB 04:** inspect a saved response through the existing decoder. Do not print credentials. |
| **05 — Resume the acquisition manifest** | 04 | **100–140.** `data/acquisition.py`: sequential partition driver, append-only completion entries, restart checkpoint and bounded transient retry/backoff. Advance only after verified raw publication. | Restart skips verified completed partitions; missing/mutated completed objects fail. Failure after object publication but before checkpoint does not lose or duplicate observations. Auth/schema errors are terminal; exhausted transient retries leave an incomplete run. **NB 05:** interrupt a three-partition fake run and compare the resumed manifest with uninterrupted acquisition. |
| **06 — Stream raw lines with explicit gaps** | 05 | **90–140.** `data/providers/tardis/lines.py`: bounded decompression/UTF-8 line iteration over verified objects, stable zero-based source positions, blank-line lookahead and terminal interval-end proxy. Record missing expected partitions and disconnect intervals. | Preserve source bytes and line order, including repeated captures and trailing blanks. A quiet interval is distinct from a missing object; a missing object is not an empty market. Truncation/invalid encoding fails. **NB 06:** inspect blanks at beginning/middle/end and an absent partition without inventing timestamps or padding prices. |

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

MR 04 is the early source feasibility checkpoint. Source access is not assumed
by this roadmap. If it is unavailable, retain the exact unproven boundary and
continue synthetic/storage/accounting work that does not depend on it. Do not
mark permitted-source acquisition or P1 complete, purchase access, or substitute
an unapproved provider to obtain a pass.

### B. Build a causal, versioned dataset

| MR | Depends on | Proposed change and production-line estimate | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **07 — Bind decoded events to raw occurrences** | 06 | **100–140.** `data/normalization.py`: compose the existing cached decoder with a persisted occurrence envelope identifying request partition, raw digest and line position. Retain exact canonical event bytes and original acquisition provenance. | Two files starting at sequence zero cannot collide. Rebuild from saved objects and identical retries reproduce the same occurrence identities. Keep occurrence identity separate from the venue trade key used for economic deduplication in MR 08. **NB 07:** decode two colliding local sequences and trace each event back to its raw bytes. |
| **08 — Admit duplicates and corrections explicitly** | 07 | **100–140.** `data/revisions.py`: resolve economic duplicates by source/venue/instrument/stream/trade ID for the selected trade representation; record conflicting payloads, revision linkage and correction publication/availability beside original occurrences. | Exact duplicates retain all lineage and contribute once. Conflicts without justified revision ordering/availability fail publication. Known corrections append versions; effective knowledge is no earlier than original capture and correction availability. **NB 08:** add a late correction and show the earlier version remains reconstructible. Positional IDs alone cannot match revisions after inserted lines. |
| **09 — Read historical eligibility assertions** | 00–01 | **90–130.** `data/eligibility.py`: strict file-backed assertions for canonical instrument, valid interval, knowledge time, included/excluded state, reason and evidence identity. Validate linkage to the selected catalog/units without changing its authored meaning. | Reject missing evidence, overlapping contradictory assertions and invented knowledge dates. Preserve excluded/delisted members. Synthetic assertions are labeled as such. **NB 09:** compare a 2026-authored assumption with an assertion actually evidenced as known during the sample. |
| **10 — Select the universe as of a decision** | 09 | **70–120.** Extend `data/eligibility.py` with pure bitemporal selection and explicit unknown/unsupported outcomes. Use validity and knowledge independently; append corrections rather than rewriting history. | A later listing correction/exclusion cannot change an earlier universe. Unknown membership cannot silently become eligible. **NB 10:** display inclusion before/at/after both knowledge and validity boundaries, including the half-open endpoint. |
| **11 — Validate a canonical partition** | 07–10 | **100–140.** `data/quality.py`: consume normalized occurrences and policies; check declared coverage, units/identity, revisions, missing partitions, duplicate disposition and ordering. Produce canonical partition bytes plus a compact accepted/rejected quality result. | Invalid records and unresolved required coverage never become accepted data. Retain exclusion and rejection reasons; no silent row drops, zero fill or forward fill. Same retained inputs/policies produce the same canonical partition. **NB 11:** inspect counts and exact lineage while injecting a duplicate, gap and wrong instrument. |
| **12 — Validate and identify a dataset manifest** | 11 | **90–140.** `data/datasets.py`: versioned manifest reader and identity over ordered partition digests, raw manifests, request/catalog/eligibility identities, normalization code/schema and quality/correction policy. Verify referenced files. | Equivalent saved inputs rebuild the same identity; a policy/schema/reference change changes identity; missing bytes and unknown versions fail. Keep build wall-clock/path metadata outside semantic identity. **NB 12:** rebuild twice, then change one policy and compare hashes. |
| **13 — Publish and reopen one snapshot atomically** | 12 | **90–140.** `data/snapshots.py`: stage verified partitions/manifest, publish the immutable snapshot as one visibility boundary, and reopen by explicit snapshot ID. Use existing raw-publication primitives only where semantics match. | An interrupted build exposes no partial snapshot. Prior snapshots remain readable after failure and publication of a new one. Never silently resolve a mutable latest tag in a run. **NB 13:** fail before publication, inspect reader behavior, then reopen the completed snapshot. |
| **14 — Read point events as of a cutoff** | 08, 10, 13 | **90–140.** `data/asof.py`: select known revisions and eligible events from a saved snapshot with an explicit decision cutoff and business window. Define total ordering from effective knowledge, stable partition identity and source order with deterministic final tie-breaks. | Filter knowledge before selecting the latest revision. Never sort only on exchange time or take today's corrected projection. Future payload, correction and universe perturbations leave earlier selected records unchanged. **NB 14:** compare equal captures across objects, UTC offsets, late publication and future corrections at a fixed cutoff. |
| **15 — Build completed observations at a fixed cadence** | 14 | **100–140.** `research/observations.py`: derive the selected trade-price observations and preceding return from explicit half-open windows. Carry input lineage, availability and staleness; emit missing/invalid status where required. | A decision sees only completed, then-available observations. Newer-but-late events are unavailable; later changes cannot revise an already emitted decision input. Require enough valid observations for the return; no future/backfill imputation. **NB 15:** plot a tiny observation timeline and show warm-up, a late trade and a stale/disconnected interval. |

Persisted event revisions may wrap the current decoder output instead of widening
every public event type. Whichever representation is implemented, all dataset
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

| MR | Depends on | Proposed change and production-line estimate | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **16 — Load the frozen baseline specification** | 00–01 | **90–140.** `strategies/baseline_config.py`: typed immutable strategy/version, cadence/horizon, quantity, capital and execution/cost configuration with exact units and cached serialization. Bind the owning experiment and relevant reference identities. | Reject unsupported leverage/shorting/currencies, invalid periods and unsafe numeric values. Config bytes have stable identity; changed behavior cannot replace an old configuration under the same identity. **NB 16:** inspect dimensions and show that a fee or cadence change produces a new configuration identity. |
| **17 — Define decision context and typed targets** | 15–16 | **90–140.** `strategies/contracts.py`: immutable context binding strategy/version, dataset/config, explicit decision clock and seed; output target quantity, decision time, horizon and input lineage. Validate all boundaries. | Context cannot select a different dataset silently. Target units belong to the selected instrument; expiration and decision time are explicit. Seed is recorded even when unused by this deterministic baseline. **NB 17:** round-trip a context/target and reject a quantity for the other instrument. |
| **18 — Implement no-trade and the transparent rule** | 17 | **60–110.** `strategies/baseline.py`: pure decision functions over the selected valid completed observations. Produce zero or the predeclared fixed quantity; no fitting, parameter search or notebook-owned signal calculation. | No-trade always stays flat. Hand examples cover positive/zero/negative return, warm-up and invalid/stale observations using the frozen policy. Same context reproduces decisions, independent of invocation order. **NB 18:** display inputs beside targets and perturb future observations. |
| **19 — Select a causally delayed simulated fill** | 14, 16–18 | **100–140.** `simulation/fills.py`: exact immutable simulated fill record and the selected full-fill price rule. A target delta uses the first eligible subsequent trade after the declared positive delay, within its horizon; retain decision and price-event identities. | No same-observation fill. Price event and its effective availability meet the delay; source quantity does not imply available liquidity. Missing/stale/gapped prices expire or reject according to the frozen policy. **NB 19:** show decision, earliest-fill and actual-fill times, including equal-time and no-price cases. |
| **20 — Compute fees and adverse price costs** | 19 | **70–120.** `simulation/costs.py`: versioned quote-currency fee and declared adverse slippage rules using C03 arithmetic/rounding. Preserve reference and effective fill prices and signed trade quantity. | Buy and sell fees reduce NAV; adverse slippage worsens both sides. Zero cost gives exact gross parity. Wrong currency, negative unsupported fee and nonfinite values fail. **NB 20:** hand-calculate one buy and one sell with nonzero costs and inspect rounding. |
| **21 — Establish bounded ledger state** | 16, 19 | **70–120.** `accounting/state.py`: immutable validated single-instrument cash/position/cost-basis state, initialized from explicit cash and zero holdings. Use existing `Money`/`Quantity` values and expose working initialization/validation. | Reject inconsistent instruments/currencies, unsupported negative cash/holdings and unsafe copies. This is an economic position, not a portfolio weight. **NB 21:** inspect initialized balances and show a unit-mismatched state fails. |
| **22 — Apply a costed fill exactly once per run** | 20–21 | **100–140.** `accounting/ledger.py`: pure ledger transition for buys/sells, exact fee cashflows, cost basis and realized P&L; retain applied fill identity in the bounded run state. | Repeated fill ID cannot change cash/position twice. Buy, partial sell, full sell, oversell and insufficient-cash cases follow explicit rejection rules. No external deposits are invented. **NB 22:** reconcile each step of the hand ledger below, then repeat a fill. Durable account recovery remains P3 work. |
| **23 — Mark NAV and reconcile gross to net** | 14, 20, 22 | **90–140.** `accounting/valuation.py`: exact point-in-time marking, unrealized P&L and attribution for the same accepted quantities against reference/effective prices. Record fees, slippage and applicable financing separately. | Ending NAV equals cash plus marked position and reconciles to initial NAV plus net P&L. No double subtraction of slippage already embedded in fills. Stale/missing marks invalidate the valuation; terminal open holdings are marked, not magically liquidated. **NB 23:** reconcile flat and open-position cases and zero-trade/zero-cost variants. |

The baseline runner will own a single outstanding target intent. MR 00 must fix
the policy for another decision before fill/expiry; the proposed minimal rule is
to skip new intents while one is pending. Derive quantity deltas from actual
holdings, apply no-trade and rejection policies consistently, and test this
interaction when composing the runner. Do not add partial-fill, margin or OMS
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

| MR | Depends on | Proposed change and production-line estimate | Acceptance and notebook checkpoint |
| --- | --- | --- | --- |
| **24 — Persist append-only trial attempts** | 12, 16–17 | **100–140.** `research/trials.py`: semantic run identity from source commit, lock/environment, data/config/strategy identities and seed; distinct attempt ID; append-only start/completion/failure records under an explicit single-writer local policy. | Repeating the same inputs retains semantic identity but creates another attempt. Changed config/data/code cannot overwrite history. A crash leaves a visible incomplete attempt; startup identifies it, and a truncated tail is reported without erasing prior records. **NB 24:** append success, failure and interrupted attempts and inspect retained history. |
| **25 — Compose the callable causal runner** | 13–24 | **100–140.** `research/runner.py`: compose saved snapshot reading, cadence/decision clock, targets, delayed fills, costs, ledger and valuations. Journal start before computation and terminal outcome afterward; return a typed result with trace and coverage status. | Compare no-trade and baseline through the same economic path. No mutable state leaks between invocations. Pin event/decision/fill/mark tie order; exercise pending-intent policy and a terminal expiry. A failed or incomplete valuation cannot become a successful net report. **NB 25:** inspect the complete synthetic raw-to-NAV trace, then rerun after a failed attempt. |
| **26 — Save the net report and durable references** | 23–25 | **90–140.** `research/reports.py`: versioned exact report serialization and atomic output persistence with digest references in the trial record. Include initial/final cash, positions/NAV, gross/net P&L, fees/slippage/financing, turnover, fill/decision counts, coverage, assumptions and identities. | Report totals match the retained ledger/trace. Refuse clobbering another result; incomplete output is never a completed trial. Missing bytes or digest mismatch fail reproduction. **NB 26:** reopen a saved report and reconcile totals; tamper with an output and show rejection. |
| **27 — Add the reproducible command and installed consumer** | 26 | **60–120**, plus explicit entry-point metadata. `research/__main__.py` or one narrow configured script: load explicit config/snapshot/output paths and call the runner. Save the actual command and identities. Extend the existing wheel smoke only for the new public consumer. | From a fresh process outside the checkout, install the candidate wheel and reproduce the synthetic report from saved inputs, without notebooks, editable imports, hidden working-directory files or a network fetch. Unsupported/missing inputs produce a nonzero exit. **NB 27:** compare fresh-process output with the earlier callable result; execute the command independently as the retained acceptance proof. |
| **28 — Close P1 with a permitted saved sample** | 04–27 | **0–50** for necessary wiring only; otherwise tests/docs/evidence. Run the frozen case on the permitted source and retain the request/raw/canonical/report identities and protected retrievable bytes. Update the owning experiment, this status and the roadmap after acceptance. | Resume actual acquisition, rebuild the snapshot and reproduce the report in another process using saved inputs. Hand-reconcile a bounded ledger excerpt; audit the selected source availability/eligibility assumptions and keep failures/limits. **NB 28:** explain the end-to-end trace and cost attribution, keeping the notebook under ignored `examples/`. Any product defect is fixed in its owning small MR before claiming completion. |

Run identity excludes attempt timestamps and local output paths. Report comparison
uses canonical economic bytes/values; operational attempt metadata may differ.
Retain the lock, interpreter/platform, code and input bytes needed to recreate the
environment. A hash with missing or inaccessible content is not reproduction.
Do not hash the final output into an input identity or make a trial ID depend on
its own serialized completion record.

The planned CLI has no current verified invocation. MR 27 must add its tested
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
- Raw transport: injected failures plus the bounded real source probe in MR 04.
  Persistence: interrupt at the specific publication/checkpoint boundaries in
  MRs 03/05/13. These catch behaviors that a prebuilt fixture bypasses.
- Final composition: one synthetic fresh-process installed-wheel reproduction in
  MR 27 and one permitted saved-input acceptance in MR 28. No universal network,
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
| Time and event identity | `EventProvenance`, decoder capture/sequence semantics | 06–08, 10, 14–15 | Late publication/corrections, equal timestamps, UTC boundaries and future-universe changes cannot alter earlier decisions. |
| Raw ingestion | Tardis/Binance decoding | 00–06 | Permitted source probe plus interrupted/resumed acquisition and mutated-object rejection. |
| Canonical dataset | Exact events, authored catalog, codecs | 07–15 | Repeatable atomic snapshot with raw lineage, historical eligibility, explicit exclusions and as-of revision selection. |
| Strategy input/output | Canonical IDs and units | 16–18 | Same immutable context gives the same unit-bearing target; changed configuration gives another identity. |
| Baseline accounting | C03 exact values/rounding | 19–23, 25 | Buy/sell/open/no-trade goldens and exact gross-to-net cash/position/NAV reconciliation. |
| Run and report | Frozen build and installed imports | 24–28 | Retained attempts and retrievable inputs reproduce the net report through the saved command in another process. |

Mark P1 complete only when all six rows have actual passing evidence for the
assembled candidate and selected permitted source. Preserve the reported source,
capture, universe and simulated-fill limitations. If historical eligibility or
source revision availability cannot be established, the engineering path may be
complete while the empirical causal baseline remains incomplete.

## Planning verification record

This record describes preparation of the roadmap, not execution of its MRs.

- Inspected `main` at the commit above after `git fetch origin`; the checkout was
  clean before creating `p1-roadmap`. Reviewed the owning roadmap, engineering
  guide, workflow, data contracts, runtime boundaries, tests and build/CI inputs.
- `uv run --frozen --no-editable pytest -q tests/unit/core/test_event_provenance.py
  tests/unit/test_reference_data.py tests/unit/test_serialization.py tests/unit/data`
  passed: **78 tests in 10.05s**, no skips reported. These are foundation tests,
  not acquisition, strategy or P1 acceptance results.
- The initial `uv run --frozen alpha-governance-architecture` found a link in
  `docs/architecture/financial-units.md` to the deleted `p1-commit-sequence.md`.
  Direct inspection found the same stale target in the component data README,
  which the default checker does not discover. This change repairs those
  references without treating historical Currency evidence as a new P1 result.
- No source implementation, data acquisition, dependency change, research run or
  notebook was created by this planning task. No runtime behavior changed, so a
  new full suite or installed-wheel run was not needed for these prose edits;
  hosted merge gates remain required.
- Final `uv run --frozen alpha-governance-architecture` passed for **22 documents**.
  An explicit `ArchitectureGovernanceService.validate_local_links` call passed
  for all **4 changed documents**, including `src/alpha_research/data/README.md`.
  `git diff --check` passed; no tracked or untracked notebook paths were found.
  The historical Currency record's Git object was verified with
  `git cat-file -e 664e501:docs/roadmap/p1-commit-sequence.md`.
