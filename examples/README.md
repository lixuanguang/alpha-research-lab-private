# Research an implementable edge

The first question is whether an observable market state can improve a trading
decision after costs, delay and risk. Organize the work around that decision:

**Observable state → future price and execution outcomes → trading policy → net economics.**

This agenda follows the founder's September 23, 2026 notes. The studies below
are proposed experiments, with no empirical findings yet. A useful outcome can
be a well-supported rejection. Predictability alone is a signal result; a trading
result also specifies entry, sizing, exit, execution and inventory.

**This research begins only after the complete infrastructure passes MR17/G5.**
All research milestones are planned, not started. The
[research program](../docs/roadmap/research-program.md#post-infrastructure-research-milestones)
owns the three milestones and QR-01–QR-18 deliverables. Earlier engineering
increments and the current worksheets do not complete any QR milestone.

## Before every research session

Before starting or resuming any research, notebook analysis or study, start
Docker Desktop and run these commands from the repository root:

```sh
make local-services-up
make local-services-status
```

`make local-services-up` is a required researcher-workflow prerequisite. It
starts lakeFS and ClearML using the ignored `secrets/local-services.env`; follow
the [local service setup](../configs/development/lakefs/README.md#local-services)
to provision the private keys and select the retained Compose projects first.
Keep the environment file and `secrets/lakefs-credentials.json` owner-readable
only; never put their values in notebooks or research records.

Container startup can precede application readiness. Confirm access to
[lakeFS](http://127.0.0.1:18000) and [ClearML](http://127.0.0.1:18080) before
beginning work; resolve startup or access failures before proceeding. This
prerequisite also applies to researcher-run studies using local or deferred
publication. Their existing publication behavior and the MR17/G5 onboarding
gate remain unchanged. Services stay running for the research session;
`make local-services-down` stops them afterward while retaining their volumes.

## Start here

Work on one execution venue, one or two instruments, and one product initially.
BTC and ETH are candidates to evaluate, not a fixed trading universe. The initial
handoff and research MVP use spot with long/flat or explicit inventory constraints.
Perpetuals and borrowing require later capability extensions and validation.
Start with L2 and instrument metadata. Add public trades when
they resolve a specific question.

| Order | Study | Decision it should support |
| --- | --- | --- |
| 1 | [Opportunity map](opportunity-map.ipynb), A1–A6 | Which venue, instrument, horizon, size and delay combinations justify a strategy experiment? |
| 2 | [Selective liquidity-taking](liquidity-taking.ipynb), B1/B2/B4/B7 | Can persistent pressure pay for a complete aggressive round trip with a meaningful no-trade region? |
| 3 | [Liquidity shocks and replenishment](liquidity-shocks.ipynb), B5–B8 | Does replenishment observed before entry distinguish reversal from continued repricing? |
| 4 | [Cross-venue information](research-agenda.md#p1p2-does-another-market-add-incremental-value), D1–D3 | Does the other venue add value beyond the local-only baseline while executing on one venue? |
| Later | [Selective liquidity provision](liquidity-provision.ipynb), B8/C1–C8 | Can filtering, quote skew and inventory control improve fill-conditioned economics with credible execution evidence? |

Run the first strategy as the economic baseline and the second as a focused
alternative on the same sample. The third candidate adds another venue's
information to a single execution venue, with credible receipt-time alignment
and comparable instruments. Passive strategies follow when trade data and
execution calibration support the claim. Two-venue execution (D4) is later scope.
The four existing workbooks are analysis aids, not a requirement to implement all
four strategies or a complete set of executable prototypes.

The [ranked research agenda](research-agenda.md) retains the full A1–F8 question
set, including model validation and expansion. Combine these questions into a
few studies; they are not independent projects or platform modules for a
researcher to implement.

## How to use the workbooks

Each notebook contains a research design and a small analysis worksheet. Read
the mechanism and competing explanation, specify the sample and policy, then
populate its explicitly empty results table from a retained study. Running an
empty workbook displays **awaiting evidence**. There is no automatic market
download, synthetic strategy result, fitted model or backtest behind that table.
The worksheets summarize supplied study outputs; they do not qualify the source
data or implement an execution simulator.

Before using real results, freeze comparisons, chronological periods, costs,
delay scenarios and rejection criteria in the [study protocol](study-protocol.md).
Keep all variants and failed attempts. Use the same eligible opportunities,
capital and constraints when comparing policies; count abstention and missed
fills, not just successful trades. Review daily P&L and exposure with uncertainty
that respects dependence between observations.

[Notebook operations](notebook-operations.md) covers setup, execution and output
retention. The [research program](../docs/roadmap/research-program.md) owns the
repository's formal evaluation and trial-record requirements.

## Expected research output

| Deliverable | What a reader should learn |
| --- | --- |
| Opportunity map | Where accessible data, costs, latency and capacity make further work plausible |
| Hypothesis register | Mechanism, competing explanation, required observations and falsification criterion |
| Baseline comparison | Incremental value over no-trade, recent returns, simple imbalance and a simple model |
| Trading-policy evaluation | Entry, exit, sizing, execution, inventory, costs, tail losses and sensitivity |
| Research implementations | Versioned dataset recipes, causal features/labels, rule/model and complete strategy policy using the delivered interfaces, with decisive correctness tests |
| Forward-validation or rejection memo | What the evidence supports, what remains uncertain, and when to stop or revisit; surviving candidates also need the Stage D bundle and forward evidence |

For example: *Following unusually large ask-side depletion, does persistent
bid-side depth predict positive five-second executable returns beyond a
recent-return baseline? Enter only after persistence is observed, apply measured
delay and a capped size, and exit under a fixed rule. Reject if incremental
out-of-sample net value disappears with feasible timing, or is concentrated in
invalid-data episodes.*

## Implementing a study

Use the [market-data interfaces](../src/market_data/README.md),
[simulation contract](../src/simulation/README.md) and
[study/report interfaces](../src/research/studies/README.md) when implementing a
study. The [platform roadmap](../docs/roadmap/README.md) owns missing capabilities
and onboarding status. The researcher owns the hypothesis and economic decision.

The [generalized study API](../src/research/studies/README.md#generalized-decision-studies)
accepts typed or serialized configuration and explicitly supplied compatible
features, transforms, estimators, policies, execution/cost models and reports.
Import only the supported API: the names each package lists in its
`__init__.py` `__all__`, as the
[platform design](../docs/architecture/platform-design.md#functional-apis-and-application-entrypoints)
defines. Deep modules and private names can change without notice.
Quant development maintains the [installed reference consumer](../tests/integration/consumers/research/decision_study.py)
and [captured-source consumer](../tests/integration/consumers/research/captured_study.py)
as executable engineering acceptance. Their losing/no-trade and queue-sensitivity
cases are not QR deliverables or empirical strategy evidence. Formal QR research
still starts only after all infrastructure and MR17/G5 acceptance.

The former infrastructure demonstrations have been removed from the active
examples. Their source remains in Git history; saved data and historical run
records retain their original identities.
