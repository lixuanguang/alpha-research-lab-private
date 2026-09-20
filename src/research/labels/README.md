# Forward observed-price outcomes

Owner: repository founder. Implemented bounded research contract, 2026-09-20.
`ForwardReturn` generates labels independently of feature calculation. Its first
consumer is the retained [price diagnostic](../features/README.md).

At decision `t`, use the already frozen feature-window final price as the base.
For horizon `h`, query the outcome's own window ending exclusively at `t+h` with
inclusive knowledge cutoff `t+h+availability_delay`. The label is
`future_last_price / frozen_base_price − 1`, a dimensionless exact rational.
The endpoint can be older than the decision under the declared feature window
and processing delay; this is not an executable entry price. Outcome window,
warm-up and business-clock freshness are explicitly configured independently.

Before that extraction cutoff the label is pending and the study does not read
its outcome window. Afterwards it always uses that same fixed cutoff, even when
the study is observed later. Late future corrections therefore cannot silently
revise an already defined outcome. The base is never re-queried at the label cutoff.

Availability is conservatively the horizon plus declared delay for a nonmissing
label. Missing/pending labels have `available_at=None`. `LabelValue` retains the
decision, outcome time, full closed information interval, outcome input/evidence,
missing reason and definition identity. Intervals include both endpoint lookbacks
and the publication delay; overlapping labels remain visible for split purging.
Labels do not enter the feature vector. This diagnostic has no execution delay,
transaction costs, training or claim of economic performance.

The shared window's missing/stale/control rules, exact numerical representation,
configuration, installed example, verification and reversal procedure live in the
[feature contract](../features/README.md). Unsupported label formulas and fitted
evaluation remain conditional on their actual consumers.
