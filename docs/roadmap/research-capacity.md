# Research capacity

Owner: quant development. Status: **accepted by extrapolation** from measured 2-hour
and 6-minute runs. The measured 72-hour run is a
[standing requirement](../research/program.md#measured-research-capacity). It may start
once the counted day run and its replay release the host, and may overlap the rest of
their retention interval ([remaining work](overview.md#remaining-work-before-qr-onboarding)).

This profile covers multi-day historical data, concurrent studies and offline feature
capacity. [Runtime capacity](runtime-capacity.md) is separate. The targets are
engineering targets, not prior achievements. Reference policies qualify infrastructure,
not profitability.

## Profile

**Inputs.**
- 72 consecutive UTC hours of two spot instruments: OKX BTC-USDT and ETH-USDT, books at
  depth 400 and trades, captured at full rate (about 8 million records in 72 hours).
- Original clocks; no time stretching or replicated records.
- All six instrument-days covered.

**Provenance.** Pinned raw bytes, capture and dataset manifests, original event,
receipt and availability clocks, explicit calendars and units, revision and quality
evidence. Unknown historical availability stays unknown.

**Workflow.**
- One-minute decision cadence: 4,320 decisions per instrument and 8,640 feature rows.
- Two independent study families of two costed trials each, on two workers. Exact fees,
  slippage and gas applicability (centralized spot: no gas) are retained. The untouched
  holdout is not consumed.
- Exact completed returns and a stateful reference feature: durable materialization,
  point-in-time retrieval for all 8,640 rows, and two-entity online generation through
  the isolated Feast worker.

**Retention.** Raw and canonical inputs and versions for 30 days; attempts, reports,
configuration and provenance for 90 days; an independent local backup for the same
periods. Forecasts separate measured bytes from extrapolation.

**Correctness.** Zero unexplained failures, missing instruments or days, cross-family
writes, future leakage or exact-value differences. Injected failures are kept
separately. Missing or invalid source data stays explicit.

| Dimension | Limit |
| --- | --- |
| Publication | ≤ 4 h for 72 hours, ≥ 550 positions/s |
| Re-derivation audit | Reported, ≤ 2 h |
| Reopen | ≤ 60 s |
| Feature source initialization | ≤ 60 s |
| Warm scheduled closes | p50/p95/p99 ≤ 50/100/250 ms, at ≥ 1,000 calls per instrument |
| Materialization (8,640 rows, Feast included) | ≤ 1 h, ≥ 2.4 rows/s |
| Point-in-time retrieval | p50/p95/p99 ≤ 10/50/100 ms per entity and cutoff |
| Feast boundary | ≥ 3 immutable offline chunks of ≤ 4,096 cells and 16 MiB, every cell reconciled; online generation and reopen ≤ 60 s each |
| Studies | ≤ 3.5 h total, ≤ 1.75 h per trial; report and result reopen ≤ 30 s each |
| Recovery | Claim and abandon ≤ 60 s; a retry recomputes the trial within the trial limit; backup and restore ≤ 120 s; restored identities and accounting equal an uninterrupted run |
| Memory | Process tree ≤ 8 GiB |
| CPU | ≤ 8 logical |
| Source input | ≤ 2 GiB stored |
| Workspace | ≤ 10 GiB |
| 30-day retained input forecast | ≤ 100 GiB |

The limits scale linearly with corpus length, because every stage is one or more
forward passes over stored rows: books are stored compactly, chains replay once,
reopening does not re-derive, and studies stream their markets.

## Accepted result

Measured on a 2-hour capture (2026-10-06 12:13:43–14:13:43 UTC, 221,240 raw positions,
one explicit `disconnect_unknown_loss` gap) and a 6-minute pilot. Each stage was fitted
as `fixed + per_hour × hours` and evaluated at 72 hours. Two points cannot show
curvature; the structural argument above is why none is expected.

| Dimension | Measured, 2 h | 72 h (extrapolated) |
| --- | --- | --- |
| Publication | 291.0 s, 760 positions/s | 10,521 s (2.9 h) |
| Re-derivation audit | 144.4 s | 5,226 s |
| Reopen | 0.22 s | 7.3 s |
| Feature source initialization | 1.05 s | 16 s |
| Warm closes (5 s cadence, 1,439 per instrument) | 23.3/66.9/81.5 ms, max 198 ms | Unchanged by length |
| Materialization | 80.1 s for 238 rows | 2,606 s for 8,640 rows |
| Point-in-time retrieval | 238 calls, max 15 ms (fewer than 1,000: totals only) | Unchanged by length |
| Feast boundary | 4 chunks, 2.6–2.8 s each; generation 3.7 s | 3 chunks of 2,880 cells; about 20 s |
| Studies | Two waves 245.7 s, per trial ≤ 123.2 s | 8,858 s (2.5 h); about 4,430 s per trial |
| Report and result reopen | ≤ 0.19 s | About 5 s |
| Recovery | Retry 123.2 s; backup 0.33 s, restore 0.20 s | Retry about 1.2 h; backup and restore about 96 s |
| Memory | Tree 473 MB | About 2.3 GB tree, 5.4 GB parent |
| CPU | Peak 3.6 | Not length-driven |
| Source input | 18.7 MB | 0.63 GiB |
| Workspace | 82.2 MB | 2.75 GiB |
| 30-day forecast | 35.6 MB/h | 23.9 GiB; 47.8 GiB with backup |

Correctness held: every point-in-time cell equalled an independent recomputation, every
fee and terminal NAV equalled a recomputation from the fills, a killed worker's retry
equalled an uninterrupted control, and backup and restore matched every result.

Every extrapolated value is inside its limit. The result does not establish 72 hours of
original-clock coverage or all six instrument-days; the measured run does.

**Evidence.** `~/AlphaResearchEvidence.noindex/mr17/r1b/attempts` (`pilot-4` and
`corpus-3`, measurement digests `c7e0df0e…` and `72920b3b…`), with the corpus record in
`~/AlphaResearchEvidence.noindex/mr17/r1b/corpus`. The consumer is
[`native_capacity.py`](../../tests/integration/consumers/research/native_capacity.py).
