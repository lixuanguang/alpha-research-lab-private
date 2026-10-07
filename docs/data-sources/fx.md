# Foreign-exchange data

**Status: source catalog updated 2026-09-16.** Rows distinguish earlier imports,
report candidates and primary-document checks. Access, depth and history remain
unverified unless the row states its evidence. See the
[evidence labels](overview.md#reading-the-records).

Tables order free access before conditional and paid routes.
Return to the [complete source index](overview.md#asset-class-guides).

## Foreign exchange — spot, NDFs and reference rates

Spot FX is fragmented. A broker’s ticks or liquidity tiers are not a consolidated interbank book. Official daily reference rates are benchmarks/statistics, not executable L1 quotes.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Dukascopy — historical FX ticks | Free | Spot FX — broker / liquidity-source view | L1 — bid/ask ticks | **Imported; not rechecked.** Downloadable historical quotes; source-specific pricing/size and trading-session conventions. | [Historical data](https://www.dukascopy.com/swiss/english/marketwatch/historical/) |
| Dukascopy — FX candles | Free | Spot FX | Bars / OHLC | **Imported; not rechecked.** Historical bars from the same venue/broker data; distinguish bid, ask and derived mid. | [Historical data](https://www.dukascopy.com/swiss/english/marketwatch/historical/) |
| HistData — FX tick exports | Free | Spot FX — selected pairs | L1 — quote ticks | **Imported; not rechecked.** Third-party historical files; format-dependent resolution and timestamp conventions require validation. | [Downloads](https://www.histdata.com/download-free-forex-data/) |
| HistData — FX minute bars | Free | Spot FX — selected pairs | Bars / OHLC | **Imported; not rechecked.** Downloadable M1 files; no order queue or consolidated traded volume. | [Downloads](https://www.histdata.com/download-free-forex-data/) |
| ECB — euro reference rates | Free | Daily FX reference rates | Reference / time series | **Imported; not rechecked.** Official daily reference values; unsuitable as executable intraday quotes. | [Reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) |
| Bank of England — daily exchange rates | Free | Daily FX reference rates | Reference / time series | **Imported; not rechecked.** Official historical series/downloads; not exchange trades or dealer depth. | [Database](https://www.bankofengland.co.uk/boeapps/database/) |
| Bank of Canada — Valet exchange rates | Free | Daily FX reference rates | Reference / time series | **Imported; not rechecked.** Official observation API; verify series metadata and update schedule. | [Valet API](https://www.bankofcanada.ca/valet/docs) |
| OANDA v20 — account pricing stream | Free with eligible account | Spot FX / broker instruments | L1; broker liquidity tiers | **Imported; not rechecked.** Account-specific prices; stream is not every market tick or an interbank L3 feed. | [Pricing API](https://developer.oanda.com/rest-live-v20/pricing-ep/) |
| Twelve Data — FX price series | Free tier; paid expansion | Spot FX pairs | Bars; quote snapshots | **Imported; not rechecked.** Aggregated/vendor prices; plan coverage and delay matter; no global order-book claim. | [Coverage / plans](https://twelvedata.com/pricing) |
| Alpha Vantage — FX series | Free tier / paid expansion; limits unverified | FX rates / selected pairs | Reference prices; Bars | **Report candidate; not rechecked.** Low-frequency/reference candidate; quote executability and current plan access untested. Not a venue order book. | [API documentation](https://www.alphavantage.co/documentation/) |
| Tiingo — FX pricing | Free tier / paid plans; limits unverified | Spot FX — provider coverage | L1; tick / bar history | **Report candidate; not rechecked.** Report identifies pricing history; determine source venues and aggregation. Not a global FX order book. | [Documentation](https://www.tiingo.com/documentation/) |
| LMAX Global — price-level market data | Conditional — client / data fees | Venue-specific spot FX / metals | L1; L2 | **Documented 2026-09-16.** Live and historical products documented. Provider pages describe different FIX depth caps; exact interface/depth and fees need confirmation. | [Data access](https://www.lmax.com/global/market-data-access), [Trading/API](https://www.lmax.com/global/trading) |
| LMAX Global — disaggregated snapshots | Conditional — client / data fees | Venue-specific spot FX / metals | L3-labelled snapshots; lifecycle unverified | **Documented 2026-09-16.** Provider lists individual-entry snapshots. IDs, event continuity and queue reconstruction were not established. | [Data access](https://www.lmax.com/global/market-data-access) |
| Cboe FX — top-of-book history | Paid | Institutional spot FX | L1 | **Imported; not rechecked.** Venue-specific historical TOP product; not all dealer/interbank liquidity. | [FX products](https://www.cboe.com/global/fx/spot/) |
| Cboe FX — full-depth snapshots | Paid | Spot FX / NDFs | L2 — snapshots | **Imported; not rechecked.** Historical full-depth snapshots; no guarantee of the events between snapshots. | [DataShop snapshot product](https://datashop.cboe.com/fx-order-book-snapshot-historical-data) |
| Cboe FX — trade prints | Paid | Institutional spot FX | Trade only | **Imported; not rechecked.** Venue trade data with volume; distinct from quote and order-event subscriptions. | [FX products](https://www.cboe.com/global/fx/spot/) |
| Cboe FX — order-event history | Paid | Institutional spot FX | Order-event depth — confirm L3 schema | **Imported; not rechecked.** Potential queue-research route; require sample order identities and priority semantics before classifying as L3. | [Order Book product](https://www.cboe.com/global/fx/spot/) |
| LSEG Tick History — FX | Paid | FX quotes / venue instruments | L1; L2 where contributed; Trades where available | **Imported; not rechecked.** Historical source-specific data; distinguish executable venues, contributor quotes and reference series. | [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history) |
| CME EBS — spot market data | Paid | Institutional spot FX | L2 / product-specific depth | **Report candidate; not rechecked.** Venue CLOB candidate; delivery/conflation and any order-level entitlement need confirmation. Not global FX liquidity. | [EBS](https://www.cmegroup.com/markets/ebs.html) |
| CME EBS — NDF market data | Paid | NDFs / selected FX forwards | L2 / product-specific depth | **Report candidate; not rechecked.** Venue CLOB candidate; delivery/conflation and any order-level entitlement need confirmation. Not global FX liquidity. | [EBS](https://www.cmegroup.com/markets/ebs.html) |
| LSEG Matching — spot FX | Paid | Interdealer spot FX | L2 / product-specific depth | **Report candidate; not rechecked.** Report identifies venue-market interfaces. Obtain exact native schema and delivery terms; continuous order-ID history unverified. | [FX products](https://www.lseg.com/en/fx), [API catalog](https://developers.lseg.com/en/api-catalog) |
| LSEG Matching — NDF API | Paid | NDFs / FX forwards | L2 / product-specific depth | **Report candidate; not rechecked.** Report identifies venue-market interfaces. Obtain exact native schema and delivery terms; continuous order-ID history unverified. | [FX products](https://www.lseg.com/en/fx), [API catalog](https://developers.lseg.com/en/api-catalog) |
