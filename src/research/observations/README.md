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
