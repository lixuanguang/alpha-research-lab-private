# Foreign-exchange data

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
and the [incorporation record](../catalog-incorporation-2026-09-15.md).

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

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
| Cboe FX — top-of-book history | Paid | Institutional spot FX | L1 | **Imported; not rechecked.** Venue-specific historical TOP product; not all dealer/interbank liquidity. | [FX products](https://www.cboe.com/global/fx/spot/) |
| Cboe FX — full-depth snapshots | Paid | Spot FX / NDFs | L2 — snapshots | **Imported; not rechecked.** Historical full-depth snapshots; no guarantee of the events between snapshots. | [DataShop snapshot product](https://datashop.cboe.com/fx-order-book-snapshot-historical-data) |
| Cboe FX — trade prints | Paid | Institutional spot FX | Trade only | **Imported; not rechecked.** Venue trade data with volume; distinct from quote and order-event subscriptions. | [FX products](https://www.cboe.com/global/fx/spot/) |
| Cboe FX — order-event history | Paid | Institutional spot FX | Order-event depth — confirm L3 schema | **Imported; not rechecked.** Potential queue-research route; require sample order identities and priority semantics before classifying as L3. | [Order Book product](https://www.cboe.com/global/fx/spot/) |
| LSEG Tick History — FX | Paid | FX quotes / venue instruments | L1; L2 where contributed; Trades where available | **Imported; not rechecked.** Historical source-specific data; distinguish executable venues, contributor quotes and reference series. | [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history) |
