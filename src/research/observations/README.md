# Named decision observations

Owner: quant development. Implemented research contracts, 2026-09-24.
The existing completed trade observations and native `BookFeatures` remain
supported. This page owns the generalized `DecisionSource` boundary used by
[features](../features/README.md#generalized-feature-lifecycle) and decisions.

`InputRequirement` names the source, family, field, units, explicit clock
(`event`, `receipt`, `valid`, or `authored`) and maximum age in integer microseconds.
`NamedObservation` retains entity, value, event/availability times, missing reason
and source lineage. Numeric values use canonical exact rational pairs; units live
in the field signature. There is no implicit normalization, currency conversion,
forward fill or shared mutable active instrument.

`DecisionInputs` freezes ordered projections for one entity and cutoff. Known
availability and event time must not exceed that cutoff. Age equality is accepted;
stale values cannot enter the feature kernel. `ObservationHistory` selects the
latest known event/revision, preserves missing/stale states and rejects ambiguous
simultaneous observations. An unknown entity or unavailable history returns explicit
missing values. Later corrections cannot revise an already emitted vector.

`NumericHistorySource` admits immutable numeric datasets, including non-book
indicators, through this contract. It pins the actual values and projection to a
digest. A fresh `DecisionSource` can support a different source protocol without
changing feature/model/decision orchestration. It must admit source quality,
revisions and membership itself; a scalar record cannot establish those facts.

`LiveBookDecisionSource` binds one capture configuration, implementation,
universe selection, named dimensionless imbalance and finite recent-history
capacity before the first message. Its identity is stable across new recording
IDs; every new instance starts empty until a fresh synchronized snapshot. The
shared `CaptureRunner` durably appends each `CaptureRecord`, applies the existing
native `CaptureReplay`, and delivers a `BookProjection.capture` row to its
observer. The live observer calls `accept(record, row, available_at=...)` with
the actual UTC delivery time after durable apply. Omission of `available_at`
uses receipt only for explicit deterministic reconstruction. Each lineage binds
the actual recording, original receipt, delivery, optional exchange milliseconds,
native sequence, book identity, quality state and raw-frame digest. Exact old
decisions require retained delivery times alongside the original journal.

OKX `books` supports event or receipt age; Bitfinex R0 has no exchange event
clock and supports receipt age. Both use exact visible L2/L3 sizes, require
uncrossed two-sided state, and expose only descriptive imbalance. A heartbeat
can carry the last valid market value but cannot refresh its age. Gaps, session
changes and invalid books clear it until a new validated snapshot. A read
freezes one UTC cutoff, retaining missing and stale reasons; earlier cutoffs
cannot be reopened in the same live source. `book_at(entity, at)` returns the
canonical market row only when the frozen named decision admits it, so paper
prices use the same causal cutoff. `current_book(entity, at)` checks the newest
delivered state without freezing a decision, so a collector can process two
market messages within one rounded microsecond. `latest_book` serves raw
current-state inspection and does not check freshness.

`research.exploration.SavedDecisionSource` composes the existing MR01
`ResearchReader`. Every decision reopens the pinned selection with its own
knowledge cutoff, within the selection's observation envelope:

- Public trade `price` and `quantity` use exchange event time and **local durable
  availability**, preserving unknown original historical receipt. Latest event
  wins; equal event/knowledge times use retained request ordinal and native row
  position. Distinct same-millisecond trades are not mistaken for conflicting revisions.
- Book `imbalance` accepts L2 bid/ask levels or native visible orders. It calculates
  `(bid_size - ask_size) / (bid_size + ask_size)` exactly. Missing/crossed sides and
  later invalidation controls stay missing. It does not infer queues or fills.
  Receipt projections explicitly use receipt age; event projections require a
  native source timestamp. Bitfinex R0 has no source timestamp and therefore uses
  the declared receipt clock. Integer nanoseconds round **up** to UTC microseconds
  at this boundary, so values never become available early.
- Reference `minimum_quantity` resolves valid time and knowledge time separately,
  retains the specification identity, and leaves unknown history explicit.

Outputs retain source/query/revision identity. The original MR01 datasets remain
authoritative for complete source quality and coverage evidence. This is bounded
saved-input research; repeated verified reads make no production throughput claim.
Historical Binance/Tardis window consumers retain their old APIs and identities.
They are not a source dependency of the new reference workloads.

Independent examples live in
[public-data tests](../../../tests/unit/data/test_public_data.py) and
[decision tests](../../../tests/unit/research/test_decision_contracts.py).
The [saved-source consumer](../../../tests/integration/consumers/research/decision_sources.py)
reopens both declared venues using the actual saved MR01 bytes. Missingness and
local clocks remain visible; source reopening is not execution conformance.
