# Data sources

Find market, reference and macroeconomic data by asset class and product.
This catalog incorporates all **283 supplied entries across 19 tables**, merges
the earlier crypto survey and adds **21 Crypto.com entries**. The result has
**331 rows** after overlapping entries are combined or split by product.
Counts describe catalog entries, including vendor bundles, not unique datasets
or integrated adapters. Coverage is broader, but not an exhaustive venue census.

**Updated: 2026-09-15.** The six columns are Source, Free/Paid, Asset, Depth,
Quality of Data and URL/API. Each table puts free access before limited free
tiers, infrastructure-cost archives, free sample days and paid products.
Quality describes fidelity and evidence; this ordering is not a quality rank.

## Reading the records

- **Imported; not rechecked:** a claim from the supplied catalog. Its stated
  review date is not independent verification by this repository. Price, depth,
  coverage and URL remain candidates for checking.
- **Documented:** primary provider documentation was reviewed on 2026-09-15;
  no endpoint, full-history or entitlement test is implied.
- **Observed / sample verified:** a stated listing, schema or actual file was
  inspected. Read the [crypto sample evidence](crypto/verification-2026-09-15.md)
  for its exact scope.
- **Integrated:** a repository consumer and acceptance evidence exist. The
  [crypto guide](crypto/README.md) links the current Binance spot-trade consumer.

The [incorporation record](catalog-incorporation-2026-09-15.md) identifies the
supplied files, overlap handling, new checks and limitations. The tables retain
the supplied product claims as candidates; the attachments' proposed acceptance
and ingestion procedures do not replace repository policy.

## Asset-class guides

| Asset / data class | Entries | Summary table |
| --- | ---: | --- |
| Cryptocurrency — spot | 51 | [Sources](#cryptocurrency--spot) |
| Cryptocurrency — perpetuals and dated futures | 44 | [Sources](#cryptocurrency--perpetuals-and-dated-futures) |
| Cryptocurrency — options | 14 | [Sources](#cryptocurrency--options) |
| Cryptocurrency — funding, positioning and on-chain fundamentals | 24 | [Sources](#cryptocurrency--funding-positioning-and-on-chain-fundamentals) |
| Prediction / event-contract markets | 4 | [Sources](prediction/README.md#prediction--event-contract-markets) |
| Equities and ETFs — United States | 19 | [Sources](equities/README.md#equities-and-etfs--united-states) |
| Equities and ETFs — Europe and multi-region low-frequency data | 10 | [Sources](equities/README.md#equities-and-etfs--europe-and-multi-region-low-frequency-data) |
| Equities and ETFs — Asia-Pacific | 22 | [Sources](equities/README.md#equities-and-etfs--asia-pacific) |
| Listed futures — equity index, rates, FX, commodity and volatility | 19 | [Sources](listed-derivatives/README.md#listed-futures--equity-index-rates-fx-commodity-and-volatility) |
| Listed options and volatility — equity, index and options on futures | 20 | [Sources](listed-derivatives/README.md#listed-options-and-volatility--equity-index-and-options-on-futures) |
| Foreign exchange — spot, NDFs and reference rates | 14 | [Sources](fx/README.md#foreign-exchange--spot-ndfs-and-reference-rates) |
| Fixed income, credit and money markets | 13 | [Sources](fixed-income/README.md#fixed-income-credit-and-money-markets) |
| Company fundamentals, filings, corporate actions and identifiers | 17 | [Sources](fundamentals/README.md#company-fundamentals-filings-corporate-actions-and-identifiers) |
| Positioning, holdings, short interest and research factors | 9 | [Sources](positioning/README.md#positioning-holdings-short-interest-and-research-factors) |
| Macroeconomic data — United States | 13 | [Sources](macro/README.md#macroeconomic-data--united-states) |
| Macroeconomic data — international and cross-country | 17 | [Sources](macro/README.md#macroeconomic-data--international-and-cross-country) |
| Macroeconomic data — Asia-Pacific | 11 | [Sources](macro/README.md#macroeconomic-data--asia-pacific) |
| Physical commodities, energy and agriculture fundamentals | 5 | [Sources](commodities/README.md#physical-commodities-energy-and-agriculture-fundamentals) |
| Institutional multi-asset delivery and raw packet archives | 5 | [Sources](multi-asset/README.md#institutional-multi-asset-delivery-and-raw-packet-archives) |
| **Total** | **331** | |

## Depth and access labels

- **Trade only:** executed transactions; aggregates can combine multiple fills.
- **L1:** best bid/ask prices and sizes where supplied. A last price, mark or
  indicative valuation is not automatically an executable quote.
- **L2:** quantities at price levels; depth may be capped. Replay needs the
  feed's snapshot/update ordering, reset and gap semantics.
- **L3 / MBO:** visible individual-order identity and lifecycle, subject to the
  stated depth and feed exclusions. This does not reveal hidden liquidity.
  The expanded catalog includes live and vendor historical L3 candidates;
  no L3 stream or historical reconstruction has been tested here.
- **Bars / OHLCV:** time-aggregated prices/volume, insufficient for intrabar or
  queue reconstruction. **N/A / reference / statistics / macro / fundamentals**
  are other data types, not L1–L3. Binance percentage-depth summaries remain N/A.

“Free” describes the stated data-access route; keys, account eligibility, delays,
geography, rate limits and storage/transfer costs can still apply. Imported
access labels remain unverified claims. Free sample days do not establish a
continuous free archive. Paid access does not guarantee complete history.
Provider coverage bundles can overlap the venue-specific rows.

## Source summary

### Crypto coverage

These four tables cover spot, futures, options and metrics. Other asset tables
are linked above. Historical archives, current snapshots, live streams and
recent-only endpoints are identified in each Quality of Data cell. Retain venue
and contract identity when comparing sources.

See the [crypto guide](crypto/README.md) for the earlier signal verification,
and [Crypto.com details](crypto/README.md#cryptocom-access-and-history) for the
new native/API versus recorded-history distinction.

### Cryptocurrency — spot

Centralized-exchange feeds describe that venue only. A live subscription is not a historical order-book archive. Margin trading normally uses the corresponding spot book, not a separate asset-price feed.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Binance History Data — `trades` | Free | Spot | Trade only | **Integrated/sample verified.** Individual fills with maker-side flag; publisher checksum checked. Spot timestamp units change in 2025. | [Archive/schema](https://github.com/binance/binance-public-data#trades), [Archive](https://data.binance.vision/) |
| Binance History Data — `aggTrades` | Free | Spot | Trade only (aggregated) | **Documented.** Combines fills; aggregate rows are not individual executions. Maker-side flag retained. | [Archive/schema](https://github.com/binance/binance-public-data#aggtrades), [Archive](https://data.binance.vision/) |
| Binance Historical Data — klines | Free | Spot | Bars / OHLCV | **Imported; not rechecked.** Historical candles; useful for bars research, not queue or within-bar execution replay. | [Archive](https://data.binance.vision/) · [Archive schema](https://github.com/binance/binance-public-data) |
| Binance API — executions | Free | Spot | Trade only | **Imported; not rechecked.** Live `trade` / `aggTrade` streams; distinguish individual from aggregated prints. | [Spot streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md) |
| Binance API — best quotes | Free | Spot | L1 | **Imported; not rechecked.** Live `bookTicker`; top-of-book only. Record locally for prospective history. | [Spot streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md) |
| Binance API — price-level book | Free | Spot | L2 | **Imported; not rechecked.** Live diff-depth plus REST snapshot; sequence synchronization required. Not L3. | [Spot streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md) |
| Bybit History Data — public trades | Free | Spot | Trade only | **Documented.** Historical archive available; verify archive side conventions and timestamp units before ingestion. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade), [Spot archive](https://public.bybit.com/spot/) |
| Bybit API — executions | Free | Spot | Trade only | **Imported; not rechecked.** Live public-trade stream and bounded recent-trade REST results; not an unlimited REST archive. | [V5 public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| Bybit API — best quotes | Free | Spot | L1 | **Imported; not rechecked.** Live depth-1 snapshots; sequence/update metadata available. | [V5 orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) |
| Bybit API — price-level book | Free | Spot | L2 | **Imported; not rechecked.** Live snapshots/deltas; published depth tiers; standard feed excludes RPI orders. | [V5 orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) |
| OKX API — spot market | Free | Spot | L1; L2; Trade only | **Imported; not rechecked.** Live standard public channels and recent REST history; faster depth tiers may require eligibility. | [V5 REST/WS](https://www.okx.com/docs-v5/en/) |
| Kraken History Data — time and sales | Free | Spot | Trade only | **Documented.** Time, price, volume; quarterly archive updates. Check actual cutoff and aggressor-field availability. | [Historical CSV downloads](https://support.kraken.com/articles/360047543791-downloadable-historical-market-data-time-and-sales-) |
| Kraken Historical Data — candles | Free | Spot | Bars / OHLCVT | **Imported; not rechecked.** Exchange bar files include trade counts; do not interpret missing intervals as zero returns without checking. | [Official OHLCVT downloads](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data) |
| Kraken Spot API — book | Free | Spot | L2 | **Imported; not rechecked.** Live aggregated book with checksum; subscribed depth is bounded. | [Spot WS book](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book) |
| Coinbase Exchange — ticker / matches | Free | Spot | L1; Trade only | **Imported; not rechecked.** Live venue-specific ticker and public matches; not a consolidated crypto tape. | [Exchange channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels) |
| Coinbase Exchange — batched book | Free | Spot | L2 | **Documented.** Unauthenticated live level2_batch delivers 50 ms batches. Historical storage and replay untested. | [Exchange channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels) |
| Bitfinex — raw book | Free | Spot | L3 — depth bounded | **Documented.** Live R0 has order IDs; the length limit counts orders, not price levels. Snapshot/update handling and replay untested. | [Raw books R0](https://docs.bitfinex.com/reference/ws-public-raw-books) |
| Bitstamp — live orders | Free | Spot | L3 | **Imported; not rechecked.** Live order events; initial-book synchronization needs separate handling. | [WebSocket](https://www.bitstamp.net/websocket/v2/) · [Bitstamp capture](https://docs.tardis.dev/historical-data-details/bitstamp) |
| Gate — spot API | Free | Spot | L1; L2; Trade only; Bars | **Imported; not rechecked.** Public live/recent-history endpoints; L2 quantities are aggregated by price. | [API v4](https://www.gate.com/docs/developers/apiv4/en/) |
| Hyperliquid — spot API | Free | Spot | L1; L2; Trade only | **Imported; not rechecked.** Live market streams; do not assume the separate S3 book archive covers spot. | [Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) · [Historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) |
| CryptoDataDownload — spot bars | Free | Spot — selected venues/pairs | Bars / OHLCV | **Imported; not rechecked.** Third-party downloadable candles; validate exchange provenance, timestamps and missing files. | [CSV downloads](https://www.cryptodatadownload.com/data/) |
| OKX History Data — order book | Free | Spot | L2 | **Listing/schema observed.** BTC-USDT 400-level file listed for 2026-09-12; snapshot/update schema. File and replay untested. | [Historical order-book downloads](https://www.okx.com/historical-data) |
| Bybit History Data — order book | Free | Spot | L2 | **Portal/schema observed.** Snapshots, deltas and sequence fields; actual depth, gaps and replay untested. | [Historical OrderBook downloads](https://www.bybit.com/en/derivative-activity/history-data) |
| Crypto.com Exchange — executions | Free (public API) | Spot | Trade only | **Documented.** Recent REST trades: at most 150/request, seven-day query window; full historical coverage untested. | [public/get-trades](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-trades) |
| Crypto.com Exchange — best quotes | Free (public API) | Spot | L1 | **Documented.** Live ticker bid/ask prices and sizes; sizes are WebSocket fields. No native quote archive verified. | [ticker subscription](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/) |
| Crypto.com Exchange — price-level book | Free (public API) | Spot | L2 | **Documented.** Current REST snapshot up to 50 levels; live WS snapshots/deltas. Sequence recovery and replay untested. | [public/get-book](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-book), [book subscription](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/) |
| Crypto.com Exchange — candles | Free (public API) | Spot | Bars / OHLCV | **Documented.** Historical candles by instrument/timeframe; earliest coverage and pagination untested. | [public/get-candlestick](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-candlestick) |
| OKX Historical Data — executions | Free (portal access conditions) | Spot — available archive instruments | Trade only | **Imported; not rechecked.** Official tick-history downloads; verify selected instrument/date availability. | [Official archive](https://www.okx.com/historical-data) |
| Coinbase Exchange — full / level3 | Free (account + authentication) | Spot | L3 | **Imported; not rechecked.** Live order lifecycle; synchronize the initial snapshot. Authentication currently required. | [Exchange channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels) · [Authentication](https://docs.cdp.coinbase.com/exchange/websocket-feed/authentication) |
| Kraken Spot API — level3 | Free (account + authentication) | Spot | L3 — depth bounded | **Documented.** Authenticated live visible-order feed; 10/100/1,000 price-level choices. Hidden iceberg quantity excluded; no archive or replay tested. | [Spot WS level3](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/level3) |
| CoinGecko Demo API | Free tier; paid expansion | Aggregated crypto spot prices | Reference prices; Bars | **Imported; not rechecked.** Cross-venue aggregates and historical charts, not executable exchange BBO or an order book. | [Demo API](https://docs.coingecko.com/docs/setting-up-your-api-key) |
| Alpaca Historical Data — trades, Alpaca venue | Free (limited tier) | Spot — Alpaca `us` | Trade only | **Documented.** Venue-specific history; date coverage and free-tier behavior untested. Not Binance data. | [Historical trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — trades, Kraken venue | Free (limited tier) | Spot — Kraken `us-1` / `eu-1` | Trade only | **Documented.** Kraken routing; inspect location and historical provider identity. 2024 sample coverage unverified. | [Historical trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — quotes, Alpaca venue | Free (limited tier) | Spot — Alpaca `us` | L1 | **Documented.** Historical best quotes, not a depth archive; selected date/access untested. | [Historical quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Alpaca Historical Data — quotes, Kraken venue | Free (limited tier) | Spot — Kraken `us-1` / `eu-1` | L1 | **Documented.** `us-1` history starts 2025-10-14 UTC; `eu-1` coverage untested. Best quotes only. | [Historical quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Tardis History Data — Binance quotes | Free (first-of-month samples) | Spot — Binance | L1 | **Documented.** `quotes` derived from the book; distinguish native `bookTicker`. File untested. | [Binance coverage](https://docs.tardis.dev/historical-data-details/binance) |
| Tardis History Data — Binance order book | Free (first-of-month samples) | Spot — Binance | L2 | **Documented.** Snapshots/deltas with recorder timestamps; captured depth/cadence limits apply. Replay untested. | [Binance coverage](https://docs.tardis.dev/historical-data-details/binance) |
| Tardis — Crypto.com order book | Free (first-of-month samples) | Spot | L2 | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — Crypto.com trades | Free (first-of-month samples) | Spot | Trade only | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — historical spot books | Paid | Spot — supported exchanges | L2; Trade only | **Imported; not rechecked.** Historical native WS replay or normalized files; coverage/channel dates vary by venue. | [Coverage](https://docs.tardis.dev/historical-data-details/overview) · [Data semantics](https://docs.tardis.dev/faq/data) |
| Tardis — Coinbase order history | Paid | Coinbase Exchange spot | L3 | **Imported; not rechecked.** Historical native order events plus snapshots; choose raw-message access, not only L2 CSV. | [Coinbase capture](https://docs.tardis.dev/historical-data-details/coinbase) |
| Tardis — Bitfinex raw history | Paid | Bitfinex spot | L3 — depth bounded | **Imported; not rechecked.** Historical R0 capture; documented `len=100` constraint, not unrestricted full-book history. | [Bitfinex capture](https://docs.tardis.dev/historical-data-details/bitfinex) |
| Tardis — Bitstamp order history | Paid | Bitstamp spot | L3 | **Imported; not rechecked.** Historical `live_orders`; REST-derived snapshots supplement the native stream. | [Bitstamp capture](https://docs.tardis.dev/historical-data-details/bitstamp) |
| Kaiko — spot market data | Paid | Spot — contracted venues | L1; L2; Trade only; Bars | **Imported; not rechecked.** Normalized historical/live products; snapshot frequency and event-level access depend on product. | [Market-data feeds](https://docs.kaiko.com/rest-api/data-feeds) |
| Amberdata — spot market data | Paid | Spot — contracted venues | L1; L2; Trade only | **Imported; not rechecked.** Historical/live market endpoints; validate the precise exchange, sampling and reconstruction contract. | [Product/API documentation](https://docs.amberdata.io/) |
| CoinAPI — spot market data | Paid | Spot — supported venues | L1; L2; Trade only; Bars | **Imported; not rechecked.** Normalized API/stream; depth and retention depend on exchange and plan. No blanket L3 claim. | [Market Data API](https://www.coinapi.io/products/market-data-api/docs) |
| Alpaca Historical Data — trades | Paid | Spot — Alpaca/Kraken, selected location | Trade only | **Documented paid tier.** Same venue distinction; paid access is not a completeness guarantee. Entitlement untested. | [Plans](https://docs.alpaca.markets/us/docs/crypto-pricing-data), [trades API](https://docs.alpaca.markets/us/reference/cryptotrades-1) |
| Alpaca Historical Data — quotes | Paid | Spot — Alpaca/Kraken, selected location | L1 | **Documented paid tier.** Best quotes; `us-1` history still starts 2025-10-14 UTC. Workload entitlement untested. | [Plans](https://docs.alpaca.markets/us/docs/crypto-pricing-data), [quotes API](https://docs.alpaca.markets/us/reference/cryptoquotes-1) |
| Tardis History Data — Binance order book | Paid | Spot — Binance | L2 | **Documented.** History beyond sample days under selected plan; retained incidents and replay still need validation. | [Coverage](https://docs.tardis.dev/historical-data-details/binance), [plans](https://tardis.dev/#pricing) |
| Tardis — Crypto.com order book | Paid | Spot | L2 | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — Crypto.com trades | Paid | Spot | Trade only | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |

### Cryptocurrency — perpetuals and dated futures

Separate linear, inverse and quanto contracts in storage. Contract size, settlement asset, expiry and funding rules belong in instrument metadata. Endpoint hosts can change during exchange migrations; use the linked current documentation.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Binance History Data — `trades` | Free | USD-M futures, including perpetuals | Trade only | **Documented.** Individual fills and maker-side flag; selected symbol/date completeness untested. | [Futures schemas](https://github.com/binance/binance-public-data#futures), [Archive](https://data.binance.vision/) |
| Binance History Data — `aggTrades` | Free | USD-M futures, including perpetuals | Trade only (aggregated) | **Documented.** Aggregated executions; preserve first/last trade IDs and product-specific aggregation semantics. | [Futures schemas](https://github.com/binance/binance-public-data#futures), [Archive](https://data.binance.vision/) |
| Binance Historical Data — USD-M klines | Free | Linear perpetuals / listed dated futures | Bars / OHLCV | **Imported; not rechecked.** Historical contract bars; not a replayable price-level book. | [Archive](https://data.binance.vision/) · [Archive schema](https://github.com/binance/binance-public-data) |
| Binance History Data — `trades` | Free | COIN-M futures, including perpetuals | Trade only | **Documented.** Individual executions; contract quantity and base quantity need distinct units. | [Futures schemas](https://github.com/binance/binance-public-data#futures), [Archive](https://data.binance.vision/) |
| Binance History Data — `aggTrades` | Free | COIN-M futures, including perpetuals | Trade only (aggregated) | **Documented.** Aggregation loses individual-fill detail; symbol/date coverage untested. | [Futures schemas](https://github.com/binance/binance-public-data#futures), [Archive](https://data.binance.vision/) |
| Binance Historical Data — COIN-M klines | Free | Inverse perpetuals / delivery futures | Bars / OHLCV | **Imported; not rechecked.** Historical inverse-contract candles; preserve contract identity and expiry. | [Archive](https://data.binance.vision/) · [Archive schema](https://github.com/binance/binance-public-data) |
| Binance Futures API — linear quotes | Free | USD-M perpetuals / futures | L1 | **Imported; not rechecked.** Live individual-symbol book ticker; verify current host and merged-market identifiers. | [Futures streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public) · [Futures changelog](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log) |
| Binance Futures API — linear book | Free | USD-M perpetuals / futures | L2 | **Imported; not rechecked.** Live price-level updates plus snapshot; not market-wide individual orders. | [Futures streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public) · [Futures changelog](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log) |
| Binance Futures API — inverse market | Free | COIN-M perpetuals / delivery futures | L1; L2; Trade only | **Imported; not rechecked.** Public live data; current migration/host rules must be read before implementation. | [Futures streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public) · [Futures changelog](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log) |
| Bybit History Data — public trades | Free | Linear futures/perpetuals, USDT/USDC | Trade only | **Documented.** Contract trade archives; selected instrument/day untested. Recent-trades REST is not a historical backfill API. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade), [Trading archive](https://public.bybit.com/trading/) |
| Bybit History Data — public trades | Free | Inverse futures/perpetuals | Trade only | **Documented.** Preserve inverse-contract units; verify symbol/date archive coverage and taker-side representation. | [Trade API and archive link](https://bybit-exchange.github.io/docs/v5/market/recent-trade), [Trading archive](https://public.bybit.com/trading/) |
| Bybit API — linear book | Free | Linear perpetuals / futures | L1; L2 | **Imported; not rechecked.** Live snapshot/delta price levels; depth-dependent publication cadence; RPI excluded from standard book. | [V5 orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) |
| Bybit API — inverse book | Free | Inverse perpetuals / delivery futures | L1; L2 | **Imported; not rechecked.** Live price-level book; order counts/price-level IDs are not individual order identities. | [V5 orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) |
| Bybit API — derivatives trades | Free | Linear / inverse perpetuals and futures | Trade only | **Imported; not rechecked.** Public execution stream and recent-history REST; separate block/RPI flags where provided. | [V5 public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| OKX API — swaps | Free | Linear / inverse perpetual swaps | L1; L2; Trade only | **Imported; not rechecked.** Standard public live streams; low-latency depth channels have additional access rules. | [V5 REST/WS](https://www.okx.com/docs-v5/en/) |
| OKX API — dated futures | Free | Linear / inverse dated futures | L1; L2; Trade only | **Imported; not rechecked.** Public live market feeds; retain expiry, settlement currency and contract multiplier. | [V5 REST/WS](https://www.okx.com/docs-v5/en/) |
| BitMEX API — derivatives | Free | Perpetuals / dated futures | L1; L2; Trade only | **Imported; not rechecked.** `orderBookL2` IDs identify price levels, not individual orders. | [API explorer](https://www.bitmex.com/api/explorer/) · [Book ID semantics](https://www.bitmex.com/static/md/en-US/apiChangelog) |
| Gate API — perpetual futures | Free | Perpetuals | L1; L2; Trade only; Bars | **Imported; not rechecked.** Public futures book/trade endpoints; validate settlement-specific units. | [API v4](https://www.gate.com/docs/developers/apiv4/en/) |
| Gate API — delivery futures | Free | Dated delivery futures | L1; L2; Trade only | **Imported; not rechecked.** Separate delivery-contract API; archive depth is not implied by live availability. | [API v4](https://www.gate.com/docs/developers/apiv4/en/) |
| Hyperliquid — perpetual market API | Free | Perpetuals | L1; L2; Trade only | **Imported; not rechecked.** Live public subscriptions; retain coin IDs, update cadence and snapshot semantics. | [Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) |
| dYdX — Indexer market streams | Free | Perpetuals | L2; Trade only; Bars | **Imported; not rechecked.** Indexer REST/WS; aggregated off-chain book view, not a market-wide L3 archive. | [Indexer WebSockets](https://docs.dydx.xyz/indexer-client/websockets) |
| Bybit History Data — order book | Free | Futures/perpetuals — portal “Contract” category | L2 | **Portal category observed.** Contract-specific coverage and depth still need a file probe; no reconstruction evidence. | [Historical OrderBook downloads](https://www.bybit.com/en/derivative-activity/history-data) |
| Crypto.com Exchange — executions | Free (public API) | Perpetual futures | Trade only | **Documented.** Recent REST trades: at most 150/request, seven-day query window; full historical coverage untested. | [public/get-trades](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-trades) |
| Crypto.com Exchange — best quotes | Free (public API) | Perpetual futures | L1 | **Documented.** Live ticker bid/ask prices and sizes; sizes are WebSocket fields. No native quote archive verified. | [ticker subscription](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/) |
| Crypto.com Exchange — price-level book | Free (public API) | Perpetual futures | L2 | **Documented.** Current REST snapshot up to 50 levels; live WS snapshots/deltas. Sequence recovery and replay untested. | [public/get-book](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-book), [book subscription](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/) |
| Crypto.com Exchange — candles | Free (public API) | Perpetual futures | Bars / OHLCV | **Documented.** Historical candles by instrument/timeframe; earliest coverage and pagination untested. | [public/get-candlestick](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-candlestick) |
| OKX Historical Data — swap trades | Free (portal access conditions) | Perpetual swaps — archive-covered contracts | Trade only | **Imported; not rechecked.** Official execution downloads; validate linear/inverse instrument availability. | [Official archive](https://www.okx.com/historical-data) |
| OKX Historical Data — swap books | Free (portal access conditions) | Perpetual swaps — archive-covered contracts | L2 | **Imported; not rechecked.** Official historical depth product; selected instrument/date coverage must be checked. Asset/contract availability requires confirmation in the archive selector; not independently enumerated here. | [Official archive](https://www.okx.com/historical-data) |
| OKX Historical Data — dated contracts | Free (portal access conditions) | Dated futures — archive-covered contracts | Trade only; L2 | **Imported; not rechecked.** Separate dated-futures selection; do not infer an expiry archive from a perpetual symbol. Asset/contract availability requires confirmation in the archive selector; not independently enumerated here. | [Official archive](https://www.okx.com/historical-data) |
| Deribit API — perpetuals | Free; raw-channel authentication | Perpetuals | L1; L2; Trade only | **Imported; not rechecked.** Live market data; raw book still aggregates by price. Check channel-specific conflation. | [Book channel](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval) · [Ticker channel](https://docs.deribit.com/subscriptions/market-data/tickerinstrument_nameinterval) |
| Deribit API — dated futures | Free; raw-channel authentication | Dated futures | L1; L2; Trade only | **Imported; not rechecked.** Live contracts and recent/history endpoints; book API is L2, not L3. | [Book channel](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval) |
| Hyperliquid — S3 book archive | Free data; AWS transfer costs | Perpetuals | L2 — snapshots | **Imported; not rechecked.** Historical snapshots; docs warn of missing data and non-guaranteed update timing. Not spot history. | [Historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) |
| Hyperliquid — node fill archive | Free data; AWS transfer costs | Chain-recorded market fills | Trade only | **Imported; not rechecked.** Historical node fills by block; decode format versions and avoid counting both sides twice. | [Historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) |
| Tardis History Data — Deribit order book | Free (first-of-month samples) | Perpetual futures — Deribit | L2 | **Documented.** Recorded book updates; symbol/day replay untested. | [Deribit coverage](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis — Crypto.com order book | Free (first-of-month samples) | Perpetual futures | L2 | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — Crypto.com trades | Free (first-of-month samples) | Perpetual futures | Trade only | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — perpetual history | Paid | Linear / inverse perpetuals — supported venues | L1; L2; Trade only | **Imported; not rechecked.** Native WS capture and normalized replay; published exchange granularity and gaps remain relevant. | [Coverage](https://docs.tardis.dev/historical-data-details/overview) · [Data semantics](https://docs.tardis.dev/faq/data) |
| Tardis — dated-futures history | Paid | Dated futures — supported venues | L1; L2; Trade only | **Imported; not rechecked.** Historical contract-level capture; use expired instrument catalogue, not only today’s universe. | [Coverage](https://docs.tardis.dev/historical-data-details/overview) · [Deribit capture](https://docs.tardis.dev/historical-data-details/deribit) |
| Kaiko — derivatives data | Paid | Perpetuals / futures — licensed coverage | L1; L2; Trade only; Statistics | **Imported; not rechecked.** Normalized historical/live products; funding, contract specs and book products must be specified. | [Market-data feeds](https://docs.kaiko.com/rest-api/data-feeds) |
| Amberdata — derivatives data | Paid | Perpetuals / futures — supported venues | L1; L2; Trade only; Statistics | **Imported; not rechecked.** Market data plus derivatives analytics; request raw versus derived fields separately. | [Product/API documentation](https://docs.amberdata.io/) |
| CoinAPI — derivatives data | Paid | Perpetuals / futures — supported venues | L1; L2; Trade only; Bars | **Imported; not rechecked.** Normalized market feeds; contract coverage and historical book access are plan-specific. | [Market Data API](https://www.coinapi.io/products/market-data-api/docs) |
| Tardis History Data — Deribit order book | Paid | Perpetual futures — Deribit | L2 | **Documented.** Plan/date-dependent access; untested locally. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |
| Tardis — Crypto.com order book | Paid | Perpetual futures | L2 | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |
| Tardis — Crypto.com trades | Paid | Perpetual futures | Trade only | **Documented.** Recorded history; symbol/date continuity untested. | [Coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com) |

### Cryptocurrency — options

Trades/quotes, exchange mark IV, vendor-fitted surfaces and Greeks are different datasets. Preserve call/put, strike, expiry, settlement convention and underlying index. No blanket crypto-options L3 availability is claimed here.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Deribit — option market analytics | Free | Crypto options | Reference / statistics | **Imported; not rechecked.** Live ticker exposes derivatives fields; mark IV/Greeks are exchange calculations, not traded observations. | [Ticker channel](https://docs.deribit.com/subscriptions/market-data/tickerinstrument_nameinterval) |
| Bybit — option trades | Free | Crypto options | Trade only | **Imported; not rechecked.** Public executions/recent trades with option-specific fields; distinguish block trades. | [V5 public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade) |
| Bybit — option books | Free | Crypto options | L2 | **Imported; not rechecked.** Live depth-25 or depth-100 price-level books; publication cadence differs by depth. | [V5 orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) |
| OKX — option market API | Free | Crypto options | L1; L2; Trade only | **Imported; not rechecked.** Public options market channels; historical retention is endpoint-specific. | [V5 REST/WS](https://www.okx.com/docs-v5/en/) |
| Gate — options API | Free | Crypto options — listed contracts | L1; L2; Trade only | **Imported; not rechecked.** Separate options endpoints; listing coverage and liquidity are contract-specific. | [API v4](https://www.gate.com/docs/developers/apiv4/en/) |
| Deribit REST — DVOL history | Free | Options-derived volatility index | N/A — volatility index | **Documented.** Implied-volatility OHLC, including hourly/daily intervals; not an option-chain or basis dataset. | [`public/get_volatility_index_data`](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data) |
| Deribit — option books | Free; raw-channel authentication | Crypto options | L1; L2 | **Imported; not rechecked.** Live price-level option books. Even raw is not individual-order L3. | [Book channel](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval) |
| Tardis History Data — Deribit order book | Free (first-of-month samples) | Options — Deribit | L2 | **Documented.** Option book capture; selected expiry/strike depth and replay untested. | [Deribit coverage](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis History Data — Deribit options chain | Free (first-of-month samples) | Options — Deribit | N/A — chain/ticker dataset | **Documented.** Historical `options_chain` sample offered; fields and chosen date not locally verified. | [Deribit datasets](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis — Deribit options history | Paid | Deribit options | L1; L2; Trade only; Statistics | **Imported; not rechecked.** Native market history and option summaries; retain expiry/strike/underlying definitions. | [Deribit capture](https://docs.tardis.dev/historical-data-details/deribit) |
| Tardis — other option venues | Paid | Bybit / OKX options — covered dates | L1; L2; Trade only; Statistics | **Imported; not rechecked.** Check each options-specific exchange ID and collection start; spot coverage is not options coverage. | [Coverage](https://docs.tardis.dev/historical-data-details/overview) |
| Amberdata — options / volatility | Paid | Crypto options | L1; L2; Trade only; Analytics | **Imported; not rechecked.** Historical/live options data and derived volatility analytics; distinguish raw quotes from fitted surfaces. | [Product/API documentation](https://docs.amberdata.io/) |
| Tardis History Data — Deribit order book | Paid | Options — Deribit | L2 | **Documented.** Historical option books; per-instrument coverage and reconstruction untested. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |
| Tardis History Data — Deribit options chain | Paid | Options — Deribit | N/A — chain/ticker dataset | **Documented.** Chain history under selected plan; does not provide a predefined option-perpetual basis. | [Coverage](https://docs.tardis.dev/historical-data-details/deribit), [plans](https://tardis.dev/#pricing) |

### Cryptocurrency — funding, positioning and on-chain fundamentals

Funding and open interest are statistics, not order-book depth. Exchange liquidation streams need not enumerate every liquidation event; do not label them a complete global liquidation tape.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Binance — funding / mark / index | Free | Perpetuals | Reference / statistics | **Imported; not rechecked.** Public funding, mark/index and premium series; finalized funding differs from an indicative next rate. | [Futures streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public) · [Futures changelog](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log) |
| Bybit REST — funding history | Free | Linear/inverse perpetual futures | N/A — funding | **Documented.** Actual settlement rates; variable symbol intervals, up to 200 records per page. Endpoint untested. | [`/v5/market/funding/history`](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate), [Market API](https://bybit-exchange.github.io/docs/v5/market/open-interest) |
| Bybit REST — open-interest history | Free | Linear futures/perpetuals | N/A — OI | **Documented.** 5-minute through daily choices; BTCUSDT OI in BTC. Check both-side versus single-side convention. | [`/v5/market/open-interest`](https://bybit-exchange.github.io/docs/v5/market/open-interest) |
| Bybit REST — open-interest history | Free | Inverse futures/perpetuals | N/A — OI | **Documented.** 5-minute through daily choices; BTCUSD OI in USD. Pagination and historical completeness untested. | [`/v5/market/open-interest`](https://bybit-exchange.github.io/docs/v5/market/open-interest) |
| DefiLlama — TVL / protocol fundamentals | Free | DeFi protocols / chains | Reference / statistics | **Imported; not rechecked.** Aggregated TVL, fees and DEX activity; methodology and double counting require review. | [Free and Pro API](https://api-docs.defillama.com/) |
| DefiLlama — stablecoins / yields | Free | Stablecoins / DeFi pools | Reference / statistics | **Imported; not rechecked.** Supply, chain distribution and pool APY; reported yield is not a guaranteed realized return. | [API](https://api-docs.defillama.com/) |
| Coin Metrics — Community API | Free | Crypto network / market metrics | Reference / statistics | **Imported; not rechecked.** Selected community metrics; coverage is narrower than commercial products. | [Community resources](https://www.talos.com/our-solutions/data/community-resources) |
| Binance History Data — `bookDepth` | Free | USD-M futures; BTCUSDT perpetual sampled | N/A — percentage-depth summary | **Sample verified.** Ten ±1–5% band rows per timestamp; median 30-second spacing on 2024-06-01. Cannot reconstruct L2. | [Depth archives](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/BTCUSDT/) |
| Binance History Data — `metrics` | Free | USD-M futures; BTCUSDT perpetual sampled | N/A — OI and positioning metrics | **Sample verified.** 288 rows at exact five-minute intervals on 2024-06-01; broader history untested. | [Metrics archives](https://data.binance.vision/?prefix=data/futures/um/daily/metrics/BTCUSDT/) |
| Binance native funding data | Free | USD-M perpetual futures | N/A — funding | **Documented.** Settlement intervals can change; current interval metadata does not establish historical schedules. | [Funding documentation / `fundingInfo`](https://www.binance.com/en/support/faq/detail/360033525031) |
| Crypto.com Exchange — funding history | Free (public API) | Perpetual futures | N/A — funding | **Documented.** funding_hist reports settled hourly rates; current/estimated funding are separate types. History completeness untested. | [public/get-valuations](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-valuations) |
| Crypto.com Exchange — mark / index history | Free (public API) | Perpetual futures | N/A — reference prices | **Documented.** Minute mark/index values; reference prices are not executable quotes. Historical coverage untested. | [public/get-valuations](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-valuations) |
| Crypto.com Exchange — open interest | Free (public API) | Perpetual futures | N/A — OI | **Documented.** Current ticker oi field; a historical OI series is not established by this endpoint. | [public/get-tickers](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/public-get-tickers) |
| OKX — historical funding | Free (portal access conditions) | Perpetual swaps | Reference / statistics | **Imported; not rechecked.** Official funding-rate downloads; not a price or trade series. | [Official archive](https://www.okx.com/historical-data) |
| Coinalyze API — funding history | Free (key and limits) | Perpetual futures, supported venues | N/A — funding | **Documented.** Sampled rates; 40 calls/minute, roughly 1,500–2,000 intraday points retained. Not automatically a settlement ledger. | [API / funding-rate-history](https://api.coinalyze.net/v1/doc/) |
| Coinalyze API — open-interest history | Free (key and limits) | Futures/perpetuals, supported venues | N/A — OI | **Documented.** Rolling intraday history; daily history retained. Verify units, symbols and aggregation. | [API / open-interest-history](https://api.coinalyze.net/v1/doc/) |
| CoinGecko Demo — market aggregates | Free tier; paid expansion | Crypto assets | Reference / statistics | **Imported; not rechecked.** Aggregate prices, market caps and volumes; source/constituent changes affect historical comparability. | [Demo API](https://docs.coingecko.com/docs/setting-up-your-api-key) |
| Dune — query API | Free tier; paid compute/credits | On-chain swaps / transfers / protocol activity | On-chain events; Statistics | **Imported; not rechecked.** SQL over indexed chain tables; ingestion lag, reorgs and community query logic require validation. | [API](https://docs.dune.com/api-reference/overview/introduction) |
| Hyperliquid — asset context / funding | Free; archive transfer costs | Perpetuals | Reference / statistics | **Imported; not rechecked.** Current streams and selected archived contexts; S3 history may have gaps. | [Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) · [Historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) |
| Tardis — Crypto.com derivative ticker | Free (first-of-month samples) | Perpetual futures | N/A — derivatives statistics | **Documented.** Historical derivative_ticker; fields and gaps untested. | [Dataset and sample](https://docs.tardis.dev/historical-data-details/crypto-com) |
| DefiLlama Pro — extended analytics | Paid | DeFi / stablecoins / token flows | Reference / analytics | **Imported; not rechecked.** Separate authenticated API for exclusive products and higher limits; not order-level exchange data. | [Pro API](https://api-docs.defillama.com/) |
| Amberdata — blockchain / DeFi data | Paid | On-chain assets / protocols | On-chain events; Reference / analytics | **Imported; not rechecked.** Decoded blockchain data and derived metrics; preserve block hash, event index and finality assumptions. | [Product/API documentation](https://docs.amberdata.io/) |
| Tardis — derivatives statistics history | Paid | Perpetuals / futures / options | Reference / statistics | **Imported; not rechecked.** Historical captured funding, mark/index, open interest and available liquidation channels; some fields use REST polling. | [Data semantics](https://docs.tardis.dev/faq/data) |
| Tardis — Crypto.com derivative ticker | Paid | Perpetual futures | N/A — derivatives statistics | **Documented.** Historical derivative_ticker; fields and gaps untested. | [Dataset and sample](https://docs.tardis.dev/historical-data-details/crypto-com) |

## Ownership and maintenance

Maintain these Markdown tables as the source reference. The JSON and HTML
attachments were import inputs; no parallel generated catalog or active source
configuration is introduced. Update a row's evidence label when its primary
documentation or selected sample is actually checked, retaining earlier results.

The [roadmap](../roadmap/README.md) owns implementation scope and acceptance;
the [P1 specification](../research/p1-baseline.md) owns its selected source
contract. Shared event and clock semantics remain in
[data contracts](../data/contracts.md) and
[point-in-time semantics](../data/point-in-time-semantics.md). This catalog adds
no acquisition adapter, live collector or notebook stream.

Keep raw downloads and mutable observations outside Git under the
[development workflow](../governance/workflow.md). Access fees and permission to
retain or redistribute data are separate facts. Reverting this documentation
change does not affect the existing acquisition workflow.
