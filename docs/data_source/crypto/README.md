# Crypto data sources

**Status:** source survey checked on 2026-09-15; maintained with the consuming
research work. Primary documentation and the bounded observations below support
the claims. Most sources are candidates, not integrated adapters.

Use the [source summary](../README.md#source-summary) for the provider-by-market
tables, ordered free first, with depth, quality evidence and API links. The
expanded tables include imported candidates whose claims remain unverified;
their labels distinguish them from the checks recorded in this guide.

The new native L3 workflow prioritizes **Bitfinex R0** and **Coinbase Exchange
Level 3**. Start with the [collector commands](../../data/l3-collectors.md#start-here)
and [market-data guide](../../../src/market_data/README.md). Bitfinex has real bounded
capture/replay evidence; Coinbase authenticated source acceptance awaits local
Exchange key/secret/passphrase and account eligibility. This is live recording,
not historical backfill.

The requested [OKX integration](../../data/okx-market-data.md) adds public
BTC-USDT **L2** live books and historical order-book archives with actual bounded
acquisition and replay evidence. Its [source guide](../../data/okx-market-data.md)
keeps aggregate levels, missing historical sequence IDs and prefix coverage explicit.

The installed [archive acquisition command](../../../src/market_data/README.md#binance-public-daily-archive-acquisition)
reads Binance **spot individual trades** through the
[configured job](../../../configs/data-jobs/binance-archive.json). The depth and metrics
probes in this survey do not extend that adapter’s supported streams.

## Verification of the proposed signal list

| Proposed signal/source | Verdict | Corrected granularity and access |
| --- | --- | --- |
| Binance/Bybit spot and perpetual `aggTrades` with aggressor | Partly correct | Binance has aggregates and individual trades; Bybit has its own public trade schema. Timestamp precision varies by source/date. Public historical archives are available. See [trades](#trades-and-aggressor-side). |
| Binance `bookDepth`, ±5% in 1% buckets, every 5 seconds, free L2 | Material correction | Percentage-depth summaries exist in the futures archive. The sampled BTCUSDT day has approximately **30-second** spacing, not 5 seconds. It lacks the price levels needed for L2 replay. See [depth](#order-books-and-depth-summaries). |
| Binance/Bybit native + Coinalyze funding, every 8 hours, free | Qualified | Native settlement intervals vary by contract and time. Coinalyze is free with a key and limited intraday history; its sampled history is not automatically a settlement ledger. See [funding](#funding-rates). |
| Binance metrics + Bybit REST OI, 5 minutes / 1 hour, free | Supported with limits | The sampled Binance metrics file has exact 5-minute spacing. Bybit documents both intervals and other choices, with pagination. Units and historical availability require instrument-specific handling. See [OI](#open-interest). |
| Deribit BVOL / option-perpetual basis, daily / hourly, free | Split and correct | Deribit's index is **DVOL**; its public history supports hourly/daily candles. An option-perpetual basis is a separately defined calculation, not an identified ready-made historical series. See [volatility and basis](#volatility-and-basis). |
| Binance + Kraken spot tape via Alpaca, per trade, free | Correct the routing | Alpaca documents Alpaca and Kraken feeds, not Binance. Combine Binance directly with Kraken directly or via Alpaca; Alpaca's free tier is limited. See [cross-venue tape](#cross-venue-spot-tape). |

## Trades and aggressor side

**Binance — documented; individual spot trades integrated.**
[Public archives](https://github.com/binance/binance-public-data) contain both
`trades` and `aggTrades` for spot and futures. `isBuyerMaker=true` means the
aggressor sold; `false` means the aggressor bought. Spot archive timestamps from
2025-01-01 onward use microseconds; the current 2024 sample uses milliseconds.
An [aggregate spot trade](https://developers.binance.com/en/docs/products/spot/faqs/spot_glossary)
can combine multiple fills from one taker order at the same time and price. Do not
count aggregate rows as individual executions or assume identical aggregation
rules across products. Choose `trades` when individual fills matter.

**Bybit — documented, not integrated.**
[Recent public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)
use `/v5/market/recent-trade`, with explicit taker `side`, execution ID and
millisecond `time`. This is not Binance's `aggTrades` interface. The documentation
links to downloadable historical archives; the recent-trades endpoint itself is
not a date-range backfill API. Inspect archive timestamp units and field names
separately rather than copying the REST schema into an archive decoder.

## Order books and depth summaries

### Binance percentage-depth summary

**Observed, not integrated.** The public
[USD-M futures `bookDepth` directory](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/BTCUSDT/)
contains a different product from the notebook's spot trade archive. In the
checksum-verified 2024-06-01 BTCUSDT file:

- Columns are `timestamp`, `percentage`, `depth`, `notional`.
- Each of 2,880 timestamps has ten rows: -5 through -1 and +1 through +5.
- Timestamp gaps are 24–36 seconds, with median 30 seconds.
- Depth and notional increase monotonically as the absolute band widens, on
  both sides at every sampled timestamp. This is consistent with cumulative
  depth, not disjoint 1% buckets; the exact reference-price/band construction
  was not established from primary documentation in this check.

These are coarse liquidity summaries derived from a book. They do not contain
individual bid/ask prices, best quotes or update sequences, so they cannot support
book reconstruction, exact spread measurement or execution replay. Avoid naming
this source simply “L2”. See the [sample evidence](verification-2026-09-15.md).

### Historical L2 candidates

L2 here means quantities aggregated at individual bid/ask price levels.

| Source | Documented or observed offering | Verification limit |
| --- | --- | --- |
| [OKX historical data](https://www.okx.com/historical-data) | Public order-book archives advertised from March 2023. The unauthenticated portal listed BTC-USDT spot, 400 levels, 2026-09-12, 31.07 MB; its schema includes snapshots and updates. | Listing/schema inspected on 2026-09-15; file not downloaded or replayed. Depth, cadence and continuity must be checked for the selected archive. |
| [Bybit historical data](https://www.bybit.com/en/derivative-activity/history-data) | Public spot and contract order-book download choices. The spot schema includes bid/ask prices and sizes, `snapshot`/`delta`, `ts`, `u` and `seq`. | Portal/schema inspected on 2026-09-15; selected symbol/date depth and complete replay remain unverified. |
| [Tardis CSV datasets](https://docs.tardis.dev/downloadable-csv-files) | Incremental L2 and reconstructed 5-/25-level snapshots. First-of-month dates are downloadable without an API key. | Free sampled days, not continuous free daily history. Venue coverage/depth follows the captured feed; no L2 sample was fetched here. |

The existing June 1, 2024 date falls within Tardis's documented free-date rule;
that observation does not establish file coverage or amend the selected P1 source.
For L2 replay, start from a complete snapshot, respect update ordering and resets,
and stop or resynchronize after an unresolved sequence gap. A shallow snapshot
cannot establish liquidity beyond its captured levels.

## Funding rates

**Native sources — documented, not integrated.**
[Binance](https://www.binance.com/en/support/faq/detail/360033525031) describes an
eight-hour default and adjustable intervals; `fundingInfo` identifies adjustments.
[Bybit funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)
likewise says intervals differ by symbol, with up to 200 records per response;
its [instrument metadata](https://bybit-exchange.github.io/docs/v5/market/instrument)
contains `fundingInterval` in minutes. These are perpetual-contract data, not spot
funding. Use actual historical settlement timestamps and rate units; today's
interval metadata does not prove the schedule in an earlier period.

**Coinalyze — documented, not integrated.** Its
[free API](https://api.coinalyze.net/v1/doc/) requires an API key, permits 40 calls
per minute, and counts each requested symbol against the allowance. Intraday
history retains approximately 1,500–2,000 points, with older points deleted
daily; daily history is not deleted under the documented policy. Funding and OI
history offer selected intervals from one minute to daily. Actual/predicted
funding endpoints are distinct. Sampling a rate hourly does not mean funding
settles hourly; retain this distinction when calculating cash flows. No account
was created or authenticated history retrieved for this survey.

## Open interest

**Binance archive — observed, not integrated.** The
[BTCUSDT USD-M metrics archive](https://data.binance.vision/?prefix=data/futures/um/daily/metrics/BTCUSDT/)
sample contains 288 rows from 00:00 to 23:55 UTC on 2024-06-01, all 300 seconds
apart. It includes `sum_open_interest` and `sum_open_interest_value` alongside
long/short and taker-volume ratios. This proves one old daily partition is
available, not a complete multi-year history. Archive coverage and REST history
windows are separate; for example, Binance's
[COIN-M OI statistics](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Info)
document a 30-day REST window.

**Bybit REST — documented, not integrated.**
[`/v5/market/open-interest`](https://bybit-exchange.github.io/docs/v5/market/open-interest)
supports `5min`, `15min`, `30min`, `1h`, `4h`, `1d`, and up to 200 records per page
with a continuation cursor. Its documented history is bounded by instrument
launch. Preserve units: inverse BTCUSD OI is in USD, while linear BTCUSDT OI is in
BTC. Do not add contract counts, base quantities and quote notionals together.
The current response also distinguishes `openInterest` summed over both sides
from `singleOpenInterest`; verify that convention before comparing venues or
historical revisions.
Completeness and delays were not tested against the live endpoint.

## Volatility and basis

**Deribit DVOL — documented, not integrated.**
[DVOL](https://insights.deribit.com/exchange-updates/deribit-launches-volatility-index/)
measures 30-day annualized implied volatility. “BVOL” is not the name of this
Deribit index and should not silently identify a different provider's index.
The public
[`get_volatility_index_data`](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data)
method returns OHLC candles, supports `1`, `60`, `3600`, `43200` seconds and `1D`,
and uses millisecond request timestamps plus a continuation field. Hourly/daily
history is documented; no endpoint sample or full history was verified here.

**Option-perpetual basis — definition and historical inputs unresolved.**
Deribit's [options collection guide](https://docs.deribit.com/articles/options-data-collection-best-practices)
documents current option marks, quotes, IV and Greeks. That does not establish
a free historical option-chain archive or a published “option-perp basis” series.
Separately, [Tardis's Deribit catalog](https://docs.tardis.dev/historical-data-details/deribit)
documents an `options_chain` archive with free first-of-month samples and paid
history. This is a candidate for historical inputs, not a verified local sample
or a substitute for defining the signal.
Specify whether the signal means an option-implied forward versus a perpetual,
a futures/perpetual spread, or implied versus realized volatility. Those are
different quantities. A derived basis needs matched timestamps, expiry/strike,
settlement currency and a price convention. Do not label it available at a fixed
daily/hourly cadence until the formula and retained historical inputs are verified.

## Cross-venue spot tape

**Alpaca — documented, not integrated.** The current
[trade history endpoint](https://docs.alpaca.markets/us/reference/cryptotrades-1)
documents `us` for Alpaca, `us-1` for Kraken US and `eu-1` for Kraken EU. The
[streaming guide](https://docs.alpaca.markets/us/docs/real-time-crypto-pricing-data)
also identifies Alpaca/Kraken and warns that providers can change. There is no
documented Binance feed in these sources. Retain the location and provider
identity with each observation; an Alpaca endpoint name alone is insufficient.

[Crypto access](https://docs.alpaca.markets/us/docs/crypto-pricing-data) has a
limited free tier and a paid unlimited plan. The
[authentication guide](https://docs.alpaca.markets/us/docs/about-market-data-api)
exempts historical crypto data from its general authentication requirement;
streaming/latest access is separate. Kraken routing was
[announced in October 2025](https://docs.alpaca.markets/us/changelog/add-support-for-us-1-crypto-market-data-location).
That announcement does not prove an earlier backfill starts on that date, or
that our 2024 trade sample is available. Separately, the
[historical quotes endpoint](https://docs.alpaca.markets/us/reference/cryptoquotes-1)
explicitly starts `us-1` quote history at 2025-10-14 00:00 UTC; those quotes
cannot cover the 2024 sample. This cutoff does not establish trade or `eu-1`
coverage. No Alpaca request/entitlement was tested here.

**Kraken directly — documented, not integrated.**
[Trade CSV downloads](https://support.kraken.com/articles/360047543791-downloadable-historical-market-data-time-and-sales-)
contain time, price and volume, with quarterly updates. The
[public REST example](https://support.kraken.com/articles/360029077772-python-code-to-retrieve-historical-time-and-sales-trading-history-)
describes pagination through trade history. Check the actual file cutoff and
whether aggressor side is present in the selected representation. A trade-only
CSV is not a historical quote feed.

A cross-venue workflow can therefore combine Binance directly with Kraken
directly or via Alpaca. Keep each venue separate, account for USD versus USDT,
and use same-venue/same-product books when relating trades to available liquidity.

## Crypto.com access and history

**Documented on 2026-09-15; not integrated or endpoint-tested.** Crypto.com's
[Exchange API](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/reference-and-market-data)
provides public, unauthenticated market data. The catalog separates spot and
perpetual products; it does not infer option or US prediction-market access from
this API's generic instrument schema.

- [Public trades](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-trades)
  allow at most 150 records per request and a seven-day maximum query window.
  That window is not proof of seven-day retention or a complete historical
  backfill. The documented response distinguishes millisecond and nanosecond
  trade timestamps.
- [Public books](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-book)
  return current price-level snapshots up to 50 levels. Order counts at a price
  do not expose individual orders, so this is L2. The
  [WebSocket reference](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/)
  documents live snapshots/deltas and ticker bid/ask sizes. Neither is a native
  historical book archive.
- [Candles](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-candlestick)
  are historical OHLCV, with earliest dates and pagination still untested.
  [Valuations](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-valuations)
  distinguish hourly settled funding from current/estimated rates and minute
  mark/index values. Current ticker OI does not establish an OI archive.

For recorded history, [Tardis's Crypto.com catalog](https://docs.tardis.dev/historical-data-details/crypto-com)
advertises coverage from 2022-06-01 and free first-of-month CSV samples. It lists
book, trade and derivative-ticker products; specific symbols, dates and continuity
remain untested. The table separates free sample days from paid access. No native
free continuous L2 archive was established by this documentation check.

The expanded survey also rechecked live L3 documentation for
[Kraken](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/level3)
and [Bitfinex](https://docs.bitfinex.com/reference/ws-public-raw-books), plus
[Coinbase's batched L2 channel](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels).
Those checks establish documented feed structure, not a collected history or
successful local replay. Other newly imported rows remain labeled for rechecking.

## Evidence and next use

The [2026-09-15 verification record](verification-2026-09-15.md) retains the
sample identities, actual commands, results and remaining limits. Downloads are
private working copies under the existing ignored `data/binance-archives/`
directory. Free retrieval does not establish unrestricted redistribution rights.

For a future historical research consumer, the source choices supported by this
survey are individual trade archives for tape, native settlement history for
funding, native metrics/OI for positioning, and actual L2 archives for book replay.
The [roadmap](../../roadmap/README.md) still owns when those consumers are built;
this documentation adds no runtime source, notebook stream or research result.
