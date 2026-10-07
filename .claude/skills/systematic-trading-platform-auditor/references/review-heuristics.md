# Review heuristics

This file covers guidance the repository's documents don't state directly. Use it after
reading the owning contract; it never overrides that contract.

## Contents

- Documented decisions that are not defects
- Evidence words to read literally
- Where defects hide, by domain
- The demonstration standard

## Documented decisions that are not defects

Check this list before reporting.

1. Readers refuse earlier formats with an "unsupported … schema" error, and there are no
   migrations, shims or `_vN` names. See `docs/development/engineering-standards.md`,
   section "Format changes replace in place".
2. Bare module-level functions exist only as orchestrators, behavior lives in classes, and
   nested functions and lambdas are banned. Recommend methods on the owning class.
3. Foundation values (C01 to C03) are strict frozen Pydantic models. Market-data, order
   and simulation records are frozen `msgspec.Struct` values with explicit invariant
   checks.
4. Floats appear only in declared analytical projections:
   - the vectorbt comparison, bounded by a derived `nav_error_bound`;
   - report and QuantStats projections, dashboards and diagnostics;
   - durations in seconds.

   They are defects only where they feed a decision, posting, reservation, risk check or
   reconciliation.
5. Wall-clock sampling is deliberate in these places:
   - orchestrators under `applications/`;
   - receipt stamping (`ReceiptClock`) and venue timing (`VenueClock`);
   - admission-time freshness: protective reduction samples current UTC inside the
     journal transaction.
6. Exact financial reconciliation uses zero tolerance.
7. The topology is trusted and single-user, and no hostile-code sandbox is claimed. Flag
   only a claimed isolation that the code does not provide.
8. Paper fills are modeled: top-of-book, no market impact, no L2 queue position, declared
   delays and adverse prices. Shadow mode never fills. A result or report that hides these
   assumptions is the defect.
9. macOS `fsync` does not flush the drive cache, and `F_FULLFSYNC` is deliberately unused
   (`docs/data/l3-collectors.md`).
10. Separate account journals do not share one atomic firm budget.
11. Byte, message, queue and history caps end runs with explicit reasons.
12. Some limitations are documented, not defects:
    - Coinbase L3 is unverified by decision;
    - Bitfinex `SEQ_ALL` is beta server-order evidence;
    - OKX archives carry no sequence IDs;
    - the Binance and Tardis paths are legacy.

## Evidence words to read literally

- **Qualification:**
  - `qualification == "fixture"` means authored grids, used for modeled paper work only.
  - `"referenced"` means a selected reference identity whose venue-rule freshness the
    caller still owns.
  - Neither grants trading authority.
- **Dataset scopes:** `exploratory_degraded`, `causal_witnessed`, `causal_qualified` and
  `rejected`. Strict causal use needs qualified evidence.
- **Labelled assumptions** (`exchange-time-only`, `event-time-assumption`,
  `receipt-clock-as-availability`) belong to declared scenarios. They never establish
  historical availability.
- **Engineering qualification:** a candidate with `qualification="engineering"` is a
  reference workload, not empirical evidence.
- **Unknown as a value:** `None` availability, `gaps=null`,
  `continuity=unproven_no_source_sequences`, `not_measured` and `not_tested` are values.
  Code that turns them into numbers is the defect.
- **Overclaiming** is its own finding class: code, reports or documents that upgrade scope.
  Examples are treating exploratory data as causal, fixture grids as venue rules, or
  modeled fills as executable.

## Where defects hide, by domain

### Architecture and interfaces

- **The same rule enforced in two paths that drift.** Typical pairs are constructor and
  incremental update, fresh run and resume, dedicated and shared journal, batch and
  incremental feature, replay and paper. Diff them line by line; an earlier review found
  incremental checkpoints that bypassed `__post_init__` checks.
- **Options dropped between layers.** An option is accepted at the top but never forwarded
  through a reader or adapter. An earlier review found a recovery opt-in that never reached
  the query reader, which changed a feature's value.
- **Defaults that change semantics.** A keyword default selects a different clock, policy
  or implementation, or a runner falls back to a built-in implementation.
- **Misplaced logic:** domain logic written inline in `applications/`, or environment reads
  in libraries.

### Identity, units, venue/calendar

- Dicts keyed by native symbol strings, or symbols normalized outside adapters.
- Currency compared by code without its minor unit, or USD treated as USDT.
- Current tick or lot rules used for a historical decision, or a specification cached
  without its knowledge time.
- Catalog or universe membership used as an authorization check.

### Temporal/PIT

- **Boundary comparisons.** Check each `<`, `<=`, `>` and `>=` on a time against its rule:
  cutoffs are inclusive, window ends and expiry exclusive, age limits inclusive.
- **Wrong clock.** Event time used where knowledge or delivery time is required.
- **Fallback chains** such as `known or event` or `available_at or received`; they
  manufacture availability.
- **Rounding and representation:**
  - floor rounding where the contract rounds up;
  - float epoch seconds;
  - naive datetimes, and conversion through the host timezone.
- **Stale views:**
  - "latest" caches serving historical queries;
  - projections that drop instrument-less controls;
  - window edges that differ between the research and runtime implementations.
- **Dataframe time operations:** as-of join direction and exact matches, resample edges,
  centred windows, forward fills and negative shifts.
- **Asynchronous inputs.** A served feature snapshot, a published file or any input that
  arrives after its nominal instant is known only when the runtime first reads it.
  Dating the decision at the instant, or at an earlier delivery, lets the book that
  revealed the input fill it.
- **Clocks within one processing step.** Decisions made while handling one event need
  strictly increasing clocks. With equal or reversed clocks, the first decision's effects
  make the next look stale, and it is refused or reordered.

### Ingestion and books

- Continuity checks written as `>` or `>=` instead of exact succession, or skipped for
  heartbeats.
- State not reset on a new epoch.
- Updates applied before snapshot synchronization, or a half-applied message left after an
  exception.
- Level maps keyed by price strings, best prices computed over zero-size levels, or crossed
  or one-sided books used for pricing.
- Freshness taken from the latest record of any kind instead of the latest market boundary.
- Carry-forward rules comparing a state identity that includes a transport sequence: a
  heartbeat that only advances the sequence changes the identity but not the book, so a
  valid market is dropped.
- `except` blocks in receive or decode loops that drop a frame without a gap record.
- Writes acknowledged before fsync, or renames without a directory fsync.

### Research and features

- Statistics, thresholds or feature selection fitted on full samples before the split.
- Holdout values read without `consume_holdout`.
- Labels reaching features, forward fills, or centred windows.
- Hidden nondeterminism: default seeds, set iteration, `hash()`, or time-dependent
  identities.

### Simulation

- Fill eligibility on event time alone, or a fill on the decision's own quote.
- Execution at the mid or the last trade.
- Fees computed on the reference price instead of the execution price, or rounded per order
  instead of per fill.
- Slippage charged twice.
- Liquidity consumption keyed or reset incorrectly.
- Terminal marks that are stale, crossed or invented.
- Results that change with batch size or with where a checkpoint was taken.

### Orders, portfolios and controls

- **"None means approved" APIs.** Where an evaluation returns a rejection reason or `None`,
  any exception path, early return or default that yields `None` approves the order. Trace
  every path to that return.
- **Implicit allowance:** `if limit is None: allow`, `.get(key, 0)` for a missing
  commitment, or a `try`/`except` around evaluation that returns no reason.
- **Limit arithmetic:** `>` versus `>=` at a limit, gross and net confused, or a reservation
  computed at the decision quote instead of the limit price.
- **Fee cap:** a reservation that leaves out the fee cap.
- **Executable limits.** Check the limit that lowering or a default assigns on each side
  against the matching rule. An immediate sell priced at the ask never crosses, so
  positions can be entered but not exited.
- **Caps after a market move.** Marks alone can push a total over its cap. The breach
  should refuse only new risk: risk-reducing sells, cancels and restarts still pass, and
  one owner's breach does not freeze another owner's in-limit trades.
- **All-or-nothing checks over shared state.** A check that loops over every waiting
  order in an account and raises on the first failure lets one owner's stale, drifted
  or over-limit leftover refuse every other owner's decision, restart or send. Look for
  each such loop on the path, not only the one a fix touched; holding the failing item
  back is usually the correct shape.
- **Uncertain outcomes.** A local action such as a cancel request or a stop must not
  overwrite an unknown order outcome. Only reconciliation resolves it, and gates keyed on
  "unknown" must hold until then.
- **Status handling:** transitions that allow terminal → non-terminal, or that treat
  `cancel_ack` as terminal when releasing reservations.
- **False freshness:** ages computed from heartbeat or control records.
- **Split evaluation:** risk evaluated outside the journal transaction and persisted later.
  More generally, check-then-act sequences outside the serialized transaction.
- **Unsafe retries:**
  - idempotency keyed on an ID without comparing bytes;
  - exceptions after a send classified as unsent;
  - HTTP retries or redirects on order endpoints.

### Accounting

- `float`, `Decimal(<float>)` or the builtin `round` on money.
- `quantize` used for increments that are not powers of ten.
- Results that depend on the ambient `Decimal` context, or proportional splits not done in
  `Fraction`.
- Sums across currencies or instruments that bypass the typed operations.
- Reconciliation with a tolerance where the contract is exact.
- Mutable running totals kept beside the posting history.

### Recovery and risk

- **Swallowed failures:** an `except` that logs and continues inside a loop over economic
  events.
- **Early release:** a `finally` block that releases a lease before the protected write is
  durable.
- **Divergent restart:** restart paths that rebuild state differently from the live path,
  or that trust a stale snapshot.
- **Unsafe retries:** retries that are unbounded or not idempotent.
- **Side-effect recovery:** recovery that clears blocks or releases reservations as a side
  effect.
- **Shared fate:** stop or kill paths that share the strategy's process, queue or telemetry
  channel.

### Performance and concurrency

Back every performance finding with a measurement or a complexity argument. Common causes:

- **Quadratic growth** from immutable updates, such as `state = state + (item,)` in a loop.
- **Whole-state re-encoding per event.** An earlier review measured a round trip that grew
  from 18 ms at 100 orders to 79 ms at 1,000.
- **Linear lookups by identity** in growing histories.
- **Codecs constructed per call** instead of once.
- **Unbounded materialization** where the contract promises a bounded stream.

### Testing

- Oracles that reuse the production formula.
- Tests that mock the unit under test, or patch away the clock the invariant depends on.
- Fixtures with one instrument or one currency, which cannot expose dimension bugs.
- Integration- or performance-marked tests cited as evidence but never run.
- Fixed defects with no regression test that fails before the fix.

## The demonstration standard

Earlier reviews here demonstrated each serious finding with exact inputs. One deliberately
added a validation rule that the incremental path then skipped. Another measured a vectorbt
NAV error against its tolerance through the real engine. They offered lettered options only
for a genuine design choice. Match that standard.
