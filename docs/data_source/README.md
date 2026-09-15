# Data sources

Use this directory to find external datasets by asset class and data type, compare
historical coverage and access, and see what has actually been verified.

| Asset class | Data types covered | Last checked |
| --- | --- | --- |
| [Crypto](crypto/README.md) | Executed trades, quotes/order books, percentage-depth summaries, funding, open interest, volatility and cross-venue prices | 2026-09-15 |

Each asset-class guide groups sources by data type. Add other asset classes when
there is a concrete source to document; extract a type-specific page when its
details outgrow the guide.

## Reading the records

- **Documented:** supported by a linked primary provider document, checked on the
  stated date. The endpoint and full historical coverage may still be untested.
- **Observed:** a specific response, download listing or retained sample was
  inspected. The record identifies the scope; a single sample is not a coverage
  or quality guarantee.
- **Integrated:** an existing repository consumer and its acceptance evidence are
  linked. An available external source does not imply implemented support.

Prices describe provider access fees at the stated verification date. Free access
can have rate limits, limited history or account requirements; storage and compute
are separate. Record access conditions separately from permission to retain or
redistribute data. Keep raw downloads and mutable observations outside Git under
the [development workflow](../governance/workflow.md).

The [roadmap](../roadmap/README.md) owns implementation scope and acceptance. The
[P1 specification](../research/p1-baseline.md) owns its selected source contract.
This directory is a source reference, not a change to either. Shared event and
clock semantics remain in [data contracts](../data/contracts.md) and
[point-in-time semantics](../data/point-in-time-semantics.md).
