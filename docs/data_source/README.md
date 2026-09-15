# Data sources

Use this directory to find external datasets by asset class and data type, compare
historical coverage and access, and see what has actually been verified.

## Source summary

**Last checked: 2026-09-15.** Rows describe individual provider/market/dataset
combinations. Free sources come first, followed by limited free tiers, free sample
days and paid access. This is the surveyed shortlist, not an exhaustive inventory
of every provider's products. All assets below are crypto; the Asset column names
the market type. “Futures” includes perpetual contracts where explicitly stated.

Quality of Data records useful fidelity, observed evidence and limitations, not
an untested quality score. Historical sources are distinguished from current or
recent-only APIs. The [crypto guide](crypto/README.md) and
[sample evidence](crypto/verification-2026-09-15.md) contain the supporting detail.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Binance History Data — `trades` | Free | Spot | Trade only | **Integrated/sample verified.** Individual fills with maker-side flag; publisher checksum checked. Spot timestamp units change in 2025. | [Archive/schema](https://github.com/binance/binance-public-data#trades) |
| Binance History Data — `aggTrades` | Free | Spot | Trade only (aggregated) | **Documented.** Combines fills; aggregate rows are not individual executions. Maker-side flag retained. | [Archive/schema](https://github.com/binance/binance-public-data#aggtrades) |
| Binance History Data — `trades` | Free | USD-M futures, including perpetuals | Trade only | **Documented.** Individual fills and maker-side flag; selected symbol/date completeness untested. | [Futures schemas](https://github.com/binance/binance-public-data#futures) |
| Binance History Data — `aggTrades` | Free | USD-M futures, including perpetuals | Trade only (aggregated) | **Documented.** Aggregated executions; preserve first/last trade IDs and product-specific aggregation semantics. | [Futures schemas](https://github.com/binance/binance-public-data#futures) |
| Binance History Data — `trades` | Free | COIN-M futures, including perpetuals | Trade only | **Documented.** Individual executions; contract quantity and base quantity need distinct units. | [Futures schemas](https://github.com/binance/binance-public-data#futures) |
| Binance History Data — `aggTrades` | Free | COIN-M futures, including perpetuals | Trade only (aggregated) | **Documented.** Aggregation loses individual-fill detail; symbol/date coverage untested. | [Futures schemas](https://github.com/binance/binance-public-data#futures) |
| Binance History Data — `bookDepth` | Free | USD-M futures; BTCUSDT perpetual sampled | N/A — percentage-depth summary | **Sample verified.** Ten ±1–5% band rows per timestamp; median 30-second spacing on 2024-06-01. Cannot reconstruct L2. | [Depth archives](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/BTCUSDT/) |
| Binance History Data — `metrics` | Free | USD-M futures; BTCUSDT perpetual sampled | N/A — OI and positioning metrics | **Sample verified.** 288 rows at exact five-minute intervals on 2024-06-01; broader history untested. | [Metrics archives](https://data.binance.vision/?prefix=data/futures/um/daily/metrics/BTCUSDT/) |
| Binance native funding data | Free | USD-M perpetual futures | N/A — funding | **Documented.** Settlement intervals can change; current interval metadata does not establish historical schedules. | [Funding documentation / `fundingInfo`](https://www.binance.com/en/support/faq/detail/360033525031) |
| Bybit History Data — public trades | Free | Spot | Trade only | **Documented.** Historical archive available; verify archive side conventions and timestamp units before ingestion. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| Bybit History Data — public trades | Free | Linear futures/perpetuals, USDT/USDC | Trade only | **Documented.** Contract trade archives; selected instrument/day untested. Recent-trades REST is not a historical backfill API. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| Bybit History Data — public trades | Free | Inverse futures/perpetuals | Trade only | **Documented.** Preserve inverse-contract units; verify symbol/date archive coverage and taker-side representation. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| Bybit History Data — order book | Free | Spot | L2 | **Portal/schema observed.** Snapshots, deltas and sequence fields; actual depth, gaps and replay untested. | [Historical OrderBook downloads](https://www.bybit.com/en/derivative-activity/history-data) |
| Bybit History Data — order book | Free | Futures/perpetuals — portal “Contract” category | L2 | **Portal category observed.** Contract-specific coverage and depth still need a file probe; no reconstruction evidence. | [Historical OrderBook downloads](https://www.bybit.com/en/derivative-activity/history-data) |
| Bybit REST — funding history | Free | Linear/inverse perpetual futures | N/A — funding | **Documented.** Actual settlement rates; variable symbol intervals, up to 200 records per page. Endpoint untested. | [`/v5/market/funding/history`](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) |
| Bybit REST — open-interest history | Free | Linear futures/perpetuals | N/A — OI | **Documented.** 5-minute through daily choices; BTCUSDT OI in BTC. Check both-side versus single-side convention. | [`/v5/market/open-interest`](https://bybit-exchange.github.io/docs/v5/market/open-interest) |
| Bybit REST — open-interest history | Free | Inverse futures/perpetuals | N/A — OI | **Documented.** 5-minute through daily choices; BTCUSD OI in USD. Pagination and historical completeness untested. | [`/v5/market/open-interest`](https://bybit-exchange.github.io/docs/v5/market/open-interest) |
| Deribit REST — DVOL history | Free | Options-derived volatility index | N/A — volatility index | **Documented.** Implied-volatility OHLC, including hourly/daily intervals; not an option-chain or basis dataset. | [`public/get_volatility_index_data`](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data) |
| Kraken History Data — time and sales | Free | Spot | Trade only | **Documented.** Time, price, volume; quarterly archive updates. Check actual cutoff and aggressor-field availability. | [Historical CSV downloads](https://support.kraken.com/articles/360047543791-downloadable-historical-market-data-time-and-sales-) |
| OKX History Data — order book | Free | Spot | L2 | **Listing/schema observed.** BTC-USDT 400-level file listed for 2026-09-12; snapshot/update schema. File and replay untested. | [Historical order-book downloads](https://www.okx.com/historical-data) |
| Coinalyze API — funding history | Free (key and limits) | Perpetual futures, supported venues | N/A — funding | **Documented.** Sampled rates; 40 calls/minute, roughly 1,500–2,000 intraday points retained. Not automatically a settlement ledger. | [API / funding-rate-history](https://api.coinalyze.net/v1/doc/) |
| Coinalyze API — open-interest history | Free (key and limits) | Futures/perpetuals, supported venues | N/A — OI | **Documented.** Rolling intraday history; daily history retained. Verify units, symbols and aggregation. | [API / open-interest-history](https://api.coinalyze.net/v1/doc/) |
| Alpaca Historical Data — trades, Alpaca venue | Free (limited tier) | Spot — Alpaca `us` | Trade only | **Documented.** Venue-specific history; date coverage and free-tier behavior untested. Not Binance data. | [Historical trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — trades, Kraken venue | Free (limited tier) | Spot — Kraken `us-1` / `eu-1` | Trade only | **Documented.** Kraken routing; inspect location and historical provider identity. 2024 sample coverage unverified. | [Historical trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — quotes, Alpaca venue | Free (limited tier) | Spot — Alpaca `us` | L1 | **Documented.** Historical best quotes, not a depth archive; selected date/access untested. | [Historical quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Alpaca Historical Data — quotes, Kraken venue | Free (limited tier) | Spot — Kraken `us-1` / `eu-1` | L1 | **Documented.** `us-1` history starts 2025-10-14 UTC; `eu-1` coverage untested. Best quotes only. | [Historical quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Tardis History Data — Binance quotes | Free (first-of-month samples) | Spot — Binance | L1 | **Documented.** `quotes` derived from the book; distinguish native `bookTicker`. File untested. | [Binance coverage](https://docs.tardis.dev/historical-data-details/binance) |
| Tardis History Data — Binance order book | Free (first-of-month samples) | Spot — Binance | L2 | **Documented.** Snapshots/deltas with recorder timestamps; captured depth/cadence limits apply. Replay untested. | [Binance coverage](https://docs.tardis.dev/historical-data-details/binance) |
| Tardis History Data — Deribit order book | Free (first-of-month samples) | Perpetual futures — Deribit | L2 | **Documented.** Recorded book updates; symbol/day replay untested. | [Deribit coverage](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis History Data — Deribit order book | Free (first-of-month samples) | Options — Deribit | L2 | **Documented.** Option book capture; selected expiry/strike depth and replay untested. | [Deribit coverage](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis History Data — Deribit options chain | Free (first-of-month samples) | Options — Deribit | N/A — chain/ticker dataset | **Documented.** Historical `options_chain` sample offered; fields and chosen date not locally verified. | [Deribit datasets](https://docs.tardis.dev/historical-data-details/deribit) |
| Alpaca Historical Data — trades | Paid | Spot — Alpaca/Kraken, selected location | Trade only | **Documented paid tier.** Same venue distinction; paid access is not a completeness guarantee. Entitlement untested. | [Plans](https://docs.alpaca.markets/us/docs/crypto-pricing-data), [trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — quotes | Paid | Spot — Alpaca/Kraken, selected location | L1 | **Documented paid tier.** Best quotes; `us-1` history still starts 2025-10-14 UTC. Workload entitlement untested. | [Plans](https://docs.alpaca.markets/us/docs/crypto-pricing-data), [quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Tardis History Data — Binance order book | Paid | Spot — Binance | L2 | **Documented.** History beyond sample days under selected plan; retained incidents and replay still need validation. | [Coverage](https://docs.tardis.dev/historical-data-details/binance), [plans](https://tardis.dev/#pricing) |
| Tardis History Data — Deribit order book | Paid | Perpetual futures — Deribit | L2 | **Documented.** Plan/date-dependent access; untested locally. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |
| Tardis History Data — Deribit order book | Paid | Options — Deribit | L2 | **Documented.** Historical option books; per-instrument coverage and reconstruction untested. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |
| Tardis History Data — Deribit options chain | Paid | Options — Deribit | N/A — chain/ticker dataset | **Documented.** Chain history under selected plan; does not provide a predefined option-perpetual basis. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |

### Depth and access labels

- **Trade only:** executed transactions; no resting bid/ask book. Aggregate
  trades can combine several fills.
- **L1:** best bid/ask prices and sizes, without deeper price levels.
- **L2:** quantities aggregated at individual price levels. Historical replay
  also requires snapshots, ordered updates and gap handling.
- **L3:** individual order events/identifiers. No historical L3 offering was
  verified in this survey; L2 does not reveal individual queue positions.
- **N/A:** funding, OI, volatility, chain/ticker datasets and percentage-depth
  summaries do not fit the book-depth classification. In particular, Binance
  `bookDepth` is not being advertised here as full L2.

[Alpaca](https://docs.alpaca.markets/us/docs/crypto-pricing-data) documents a
limited free tier and a paid unlimited plan; exact workload entitlements were not
tested. [Tardis](https://docs.tardis.dev/downloadable-csv-files) free historical
dates are the first day of each month, not a continuous free backfill. Provider
rate limits still apply to other free APIs. The undefined option-perpetual basis
remains a [research-input gap](crypto/README.md#volatility-and-basis), not a
downloadable dataset entry.

## Asset-class guides

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
