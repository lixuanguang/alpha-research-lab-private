# Platform Contracts

## Purpose and implementation rule

These contracts define the semantic boundaries that research, simulation, shadow,
and future asset-class adapters must share. They describe the target model, not a
requirement to implement every variant in the first phase.

The first vertical slice implements only the cash/spot and perpetual-futures
variants required by the crypto baseline. Futures, options, FX, fixed income, and
specialized market-making behavior are added through the extension gates below.
Do not build a speculative universal hierarchy before a real consumer exists.

## Instruments and market events

- `InstrumentId` is internal and stable. Vendor symbols are effective-dated aliases.
- `ContractSpec` is versioned. Its implemented variants declare quantity unit,
  price unit, multiplier, currencies, tick/lot rules, lifecycle, and settlement.
- A derivative references internal underlying identifiers rather than vendor text.
- `MarketEvent` is a versioned typed union. Implemented variants may include bars,
  trades, quotes, books, fixings, settlements, funding, corporate actions, curve
  points, and volatility points.
- Unknown event or schema variants fail explicitly; they are not coerced into a
  convenient existing type.

### Instrument invariants

- Published instrument versions are immutable; corrections append a new recorded
  version.
- Tick size, lot size, multiplier, currency, aliases, and lifecycle state are
  effective-dated.
- Instrument identity does not change when a vendor symbol changes.
- Position quantity uses the instrument's native unit and converts to economic
  exposure through the applicable contract specification.
- A continuous futures series is a derived research instrument and never replaces
  listed contracts.
- Adjusted equity series are derived; raw prices and corporate actions remain
  independently available.

### Time semantics

| Field | Meaning | Example |
| --- | --- | --- |
| `ts_event` | When the source says the event occurred | Exchange trade timestamp |
| `ts_recorded` | When this version first entered the platform | Ingestion receipt time |
| `ts_available` | Earliest time a strategy could use the information | Release plus processing delay |
| `ts_effective` | When the event changes economic state | Split or parameter effective time |

Point-in-time queries use `ts_available <= decision_time` and the latest record
version known at the requested knowledge cutoff. Event time alone is never proof
of availability.

## Data and lineage

- Bronze objects preserve original payloads and checksums and are append-only.
- Silver partitions contain canonical, versioned events and reference data.
- Gold datasets are deterministic products of explicit specifications.
- Corrections create revisions while preserving earlier recorded state.
- Every result identifies raw partitions, dataset specification, code/artifact,
  configuration, component versions, dependencies, and random seeds.
- Publications are atomic. Readers never observe a partial partition or manifest.

### Storage tiers

| Tier | Contents | Mutability | Purpose |
| --- | --- | --- | --- |
| Bronze | Original files/responses/packets and checksums | Append-only | Audit and reprocessing |
| Silver | Canonical events and reference data | Versioned publication | Shared input |
| Gold | Universes, bars, features, labels, curves, model panels | Rebuildable/content-addressed | Reproducible research |

### Dataset specification

A dataset specification declares:

- Instrument or point-in-time universe source and eligibility rule.
- Event types, fields, source priority, and schema versions.
- Interval, decision schedule, timezone, sessions, and calendars.
- Start/end, lookback, warm-up, and permitted source latency.
- Adjustment, roll, missing, stale, correction, and outlier policies.
- Availability and knowledge cutoffs.
- Registered derived transformations.
- Expected partitions and hard/soft quality thresholds.

Resolution produces a manifest of exact partition identities and hashes. Replacing
a file or policy creates a new dataset identity.

### Data-quality states

- **Informational:** retained for audit without blocking publication.
- **Degraded:** may publish with a visible flag, but blocks promotion unless an
  explicit waiver states scope, evidence, owner, and expiry.
- **Hard failure:** does not publish; downstream consumers fail closed.
- **Incident:** a published partition is later found defective; lineage locates
  affected datasets, experiments, candidates, and reports for invalidation.

## Research and model contracts

- Features are time-consistent functions registered by name and version.
- Labels declare horizon, observation interval, overlap, price convention,
  execution delay, and missing policy.
- Scaling, neutralization, imputation, selection, and hyperparameters fit only on
  the applicable training interval.
- Model implementations share dataset, split, training, prediction, artifact,
  seed, and diagnostic contracts.
- Governed experiments include every run admitted to a formal comparison,
  candidate-selection process, or final-OOS decision. Failed and rejected governed
  trials remain append-only; local debugging runs become governed if their result
  influences a decision.
- Final out-of-sample inputs and rules are frozen before evaluation.

### Registry metadata

| Registry | Required metadata |
| --- | --- |
| Dataset | Specification, partition manifest, quality state, owner |
| Feature | Formula, inputs, version, availability, units, range, owner |
| Label | Horizon, price convention, delay, overlap, missing policy |
| Signal | Mechanism, transformation, direction, decay, turnover, risks |
| Model | Implementation, features, hyperparameters, training policy, artifact |
| Risk model | Factors, horizon, estimator, universe, covariance conventions |
| Cost model | Venue, sample, fee, spread, impact, participation, uncertainty |
| Portfolio policy | Objective, constraints, solver, rebalance, fallback |
| Candidate | All component versions, dataset, selection evidence, owner |

### Experiment identity

An experiment identity derives from the dataset manifest, source/artifact revision,
resolved non-secret configuration, environment/toolchain identity, component
versions, and seeds. Wall-clock time is metadata, not deterministic identity.

Corrections append new trial records and preserve the earlier evidence. A governed
trial cannot be deleted or rewritten because its outcome is unfavorable.

## Valuation, accounting, and risk

- Positions are quantities/contracts, not only portfolio weights.
- Cash is tracked by currency; FX translation is explicit.
- Premiums, dividends, coupons, funding, variation margin, exercise, assignment,
  and settlement are typed cashflow events when their instruments are supported.
- `MarketState` contains the point-in-time prices, rates, curves, surfaces, FX,
  fixings, and quality state required by a valuation.
- A valuation implementation returns value, sensitivities, and cashflows under an
  explicit convention and market-state identity.
- Risk outputs carry dimensioned units such as currency amount, delta, gamma,
  vega, DV01, margin, liquidity, or a registered domain unit.
- Covariance risk and full-revaluation scenarios are separate tools; one does not
  silently stand in for the other.

### Accounting identities

- Beginning NAV plus external cashflows plus trading/marking P&L plus financing
  and lifecycle cashflows equals ending NAV within a declared tolerance.
- Signed quantity, multiplier, price, fees, and cashflow conventions reconcile on
  hand-calculated fixtures.
- Realized and unrealized P&L have one authoritative definition.
- A fill changes economic state exactly once; retries and duplicate reports do not.
- Canceled or rejected quantity never becomes a position.
- Multi-currency translation identifies both local and base-currency P&L.

## Strategy, portfolio, and execution

- Strategy output expresses forecasts, scores, target risks, spreads, or quantities
  with horizon, confidence, and validity metadata.
- Portfolio intent converts strategy output into dimensioned desired exposures or
  quantities subject to declared constraints.
- The optimizer consumes forecasts, positions, risk, costs, liquidity, financing,
  and constraints; it does not send orders.
- Fallback behavior for stale risk, missing inputs, or infeasibility is registered,
  deterministic, and conservative.
- Execution converts portfolio intent to canonical order state and venue actions.

### Execution guarantees

- Intent, venue order, acknowledgment, fill, cancel, reject, and correction have
  stable unique identities.
- Retries are idempotent and cannot create duplicate economic orders.
- Partial fills remain explicit, including temporary multi-leg exposure.
- Decision, arrival, and fill prices, fees, opportunity cost, and benchmark
  conventions are retained for transaction-cost analysis.
- Simulation models declare omitted venue behavior and uncertainty.
- Equal-timestamp event ordering is deterministic and documented.

## Data-source adoption

Before adopting a source, document:

1. Legal and entitlement terms.
2. Markets, instruments, fields, conditions, and historical depth.
3. Timestamp origin, precision, timezone, latency, and correction behavior.
4. Identifier, lifecycle, corporate-action, roll, and delisting coverage.
5. Filtering, aggregation, adjustment, and bar-construction rules.
6. Rate limits, retention, outages, and backfill procedure.
7. Known survivorship, revision, coverage, and venue-selection biases.
8. Checksum, reconciliation, and independent comparison procedure.
9. Whether it supports fixtures, exploratory research, candidate evidence, shadow,
   or production claims.

A free source may be adequate for engineering and exploratory research without
being adequate for promotion. The classification stays visible in dataset and
candidate manifests.

### Initial sources

| Purpose | Source | Initial classification | Important limitation |
| --- | --- | --- | --- |
| Crypto spot and USD-M futures history | [Binance public data](https://github.com/binance/binance-public-data) | Engineering and medium-frequency research | Single venue; historical reference metadata must be reconstructed |
| Current crypto metadata/funding | Binance public market-data APIs | Engineering, research, forward snapshots | Current metadata is not a historical instrument master |
| U.S. equity bars/trades/quotes | [Alpaca Market Data](https://docs.alpaca.markets/us/docs/about-market-data-api), after entitlement check | Adapter development and conditional research | Coverage/entitlement must be verified; no universe or borrow history |
| Crypto options state | [Deribit API](https://docs.deribit.com/) plus platform capture | Adapter/portability research | Historical depth and corrections need assessment |
| Exchange/contract rules | Official venue specifications | Authoritative reference | Snapshot versions and effective dates |

Provider field names and identifiers remain inside connectors, normalizers, and
source-reference metadata.

## Asset-class extension gates

Asset support is added only after the core crypto path passes its operational gate
and a concrete research need exists.

### Equities

Require sessions/auctions, historical identifiers, corporate actions, delistings,
point-in-time universes, adjusted and raw series, short-sale rules, borrow
availability/fees/recalls, currencies, and jurisdiction-specific rules.

### Futures and commodities

Require listed expiries, multiplier/tick value, last-trade and delivery dates,
settlement, variation margin, rolls, spreads, delivery risk, and calendars. Derived
continuous series never replace listed-contract history.

### FX

Require base/quote semantics, spot dates, holiday-center combinations, settlement,
forwards/swap points, broken dates, funding curves, currency conversion, and
venue/counterparty conventions.

### Options and volatility

Require complete contract identity, point-in-time chains, underlying/forward
linkage, discounting, exercise/settlement, corporate-action adjustment, volatility
surfaces, Greeks, multi-leg intent, hedging, margin, assignment, and expiration.

The end-to-end portability test must reconstruct a chain/surface, run arbitrage
checks, form and simulate a multi-leg hedged intent, account for premiums and
lifecycle cashflows, attribute Greeks/execution/financing P&L, run full-revaluation
stresses, and reconcile research with shadow or replay. Only environment adapters
may change. An asset-specialized or breaking core change triggers an abstraction
review; an additive genuinely asset-neutral capability may proceed with contract
and regression evidence.

### Fixed income and rates

Require schedules, day count, business-day adjustment, accrued interest,
clean/dirty price, settlement, discount/projection curves, fixings, coupon/reset
state, issuer/seniority, embedded options, financing, and DV01/key-rate/scenario
risk.

### Market making and low latency

Treat L2/L3 reconstruction, queue priority, sequence recovery, cancel/replace,
latency distributions, adverse selection, inventory control, and venue throttles
as a specialized subsystem. Do not force them into the medium-frequency simulator.

### DeFi and on-chain markets

Treat finality, reorgs, gas, nonces, custody, AMM state, oracles, MEV, bridging, and
transaction failure as specialized execution/accounting contracts, not a minor
connector variation.
