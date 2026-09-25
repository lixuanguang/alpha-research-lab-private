# Paper and shadow application

`run_paper` composes an admitted candidate, independent exact spot limits,
`PaperOrderJournal` and `PaperCandidateRuntime` over a finite iterable of
`PaperMarket`, `PaperTimer` and normalized `OrderEvent` records. Callers supply
registered component factories, capability registry, configuration, source or
feature feed, journal path, opening time and owner. The result contains the
durable checkpoint, ledger, orders and `submission_attempted=False`. Completing
an event prefix releases ownership without canceling orders. A later invocation
restores that same journal and its unresolved reservations.

`run_live_paper` is an asynchronous bounded public-book workflow. It accepts the
same candidate/configuration plus a `CaptureRequest`, capture output and journal
path. It injects native adapters and transport into `market_data.collection.CaptureRunner`
and runs the collector beside the UTC candidate scheduler. Either task's failure
cancels its peer; persisted capture and OMS records survive. The capture's existing
queue, byte, message, retry and duration bounds remain active. A fresh process
uses a fresh recording and waits for synchronized market input before resuming
decisions. It does not reuse a stale book from a previous connection.

`PaperCaptureObserver` requires the explicit `books` registry and admits the
selected venue through `BookRegistry.lookup` and `LiveBookDecisionSource.current_quote`, using
the shared [book quote contract](../../market_data/README.md#shared-book-quotes).
Displayed quantity at the best native price includes every visible order at that
price. The existing source cutoff, missing-side, crossed-book and freshness gates
remain active before paper matching. Receipt and actual post-persistence delivery
stay separate in the unchanged journal envelope; replay retains both clocks.
`run_live_paper` constructs the default per-source registry from native reference
and capability data. Callers may supply a broader `books` registry with explicit
equivalence mappings; only the candidate's selected venue supplies modeled fills.
The result includes `book_registry` configuration and its content identity for
retention. Original delivery replay rebuilds registry state and checks identical
paper effects. Consolidated BBO inspection does not authorize cross-venue routing.

Use the maintained installed reference consumers in the
[test guide](../../../tests/README.md#paper-and-live-input-acceptance). They build
real candidate bundles through completed engineering studies, supply extension
factories through existing public APIs and retain original source/availability
clocks. Their synthetic historical study, paper economics and current native
feed observations are separately labeled. They are infrastructure acceptance
workloads and supply no empirical strategy evidence.

The independent [`alpha-execute paper`](../execute/README.md) command operates the
portable OMS without loading research, training, notebook or serving dependencies.
It accepts explicit durable step, event, matching, cancel, replace and inspection
requests. Candidate/model supervision belongs to this full research application;
the execution wheel owns only the portable order/account boundary.

All modes are local and non-executable. Native input supports declared OKX/Bitfinex
spot books; other named sources use `run_paper` and must satisfy the candidate's
admitted signatures. Dedicated one-instrument cash-funded accounts are the current
economic envelope. Venue order/account conformance, shared account portfolios and
production activation are separate roadmap outcomes.
