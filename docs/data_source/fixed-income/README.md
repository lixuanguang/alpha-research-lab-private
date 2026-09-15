# Fixed-income, credit and money-market data

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
and the [incorporation record](../catalog-incorporation-2026-09-15.md).

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Fixed income, credit and money markets

Reported bond transactions, executable bid/ask quotes, evaluated prices, benchmark fixings and fitted yield curves are separate data types. Transaction reports can contain delays, corrections and size caps.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| US Treasury — daily interest-rate curves | Free | US Treasury nominal / real yields | Reference / yield curves | **Imported; not rechecked.** Official daily curve/rate series; not per-bond executable quotes or order books. | [Treasury data](https://home.treasury.gov/resource-center-data-chart-center/interest-rates) |
| New York Fed — reference rates | Free | SOFR / EFFR and related money-market series | Reference / fixings | **Imported; not rechecked.** Official published rates, volumes and related statistics; publication time differs from observation date. | [Markets API](https://markets.newyorkfed.org/static/docs/markets-api.html) |
| Federal Reserve — H.15 / rate data | Free | US interest rates | Reference / time series | **Imported; not rechecked.** Official statistical rate series; inspect frequency and revision metadata. | [Data releases](https://www.federalreserve.gov/data.htm) |
| Bank of England — yield curves | Free | UK nominal / real / inflation curves | Reference / fitted curves | **Imported; not rechecked.** Official estimated term structures; model outputs, not individual bond-order liquidity. | [Database / curves](https://www.bankofengland.co.uk/boeapps/database/) |
| FRED — yields / credit-spread series | Free (API key) | Rates / selected credit indices | Reference / time series | **Imported; not rechecked.** Convenient redistributed series; underlying index-owner usage terms still apply. | [FRED API](https://fred.stlouisfed.org/docs/api/fred/) |
| FINRA — public fixed-income lookup | Free (public portal) | US corporate / agency and covered bonds | Trade only; Reference | **Imported; not rechecked.** Public bond information and reported transactions; not the bulk TRACE feed entitlement. | [Fixed-income portal](https://www.finra.org/finra-data/fixed-income) |
| MSRB EMMA — public municipal trades | Free (public portal) | US municipal bonds | Trade only; Reference / disclosures | **Imported; not rechecked.** Official reported muni trades and disclosure documents; public access differs from bulk subscription. | [Free versus subscription access](https://www.msrb.org/Market-Data-and-Research/Data-Subscription-Services-and-Products) |
| MSRB — academic trade data | Free (qualifying academic access) | US municipal bonds | Trade only | **Imported; not rechecked.** Eligibility-specific academic access; not a blanket commercial-use license. | [Access rules](https://www.msrb.org/Market-Data-and-Research/Data-Subscription-Services-and-Products) |
| FINRA TRACE — corporate / agency history | Paid | US corporate / agency bonds | Trade only | **Imported; not rechecked.** Historical reported transactions; choose standard/enhanced product, correction handling and applicable size treatment. | [TRACE products](https://www.finra.org/finra-data/fixed-income) |
| FINRA TRACE — structured-product data | Paid | Securitized fixed income — product coverage | Trade only | **Imported; not rechecked.** Separate TRACE products and dissemination rules; not an OTC order book. | [TRACE product catalogue](https://www.finra.org/finra-data/fixed-income) |
| FINRA TRACE — live dissemination | Paid | TRACE-eligible fixed income | Trade only | **Imported; not rechecked.** Regulatory transaction reports in real time after processing; reporting latency is not exchange matching latency. | [TRACE](https://www.finra.org/filing-reporting/trace) |
| MSRB — municipal trade subscriptions | Paid | US municipal bonds | Trade only | **Imported; not rechecked.** Real-time, comprehensive and historical subscription products; no resting-order queues. | [Trade subscriptions](https://www.msrb.org/Market-Data-and-Research/Trade-Data-Subscriptions) |
| LSEG Tick History — fixed income | Paid | Bonds / fixed-income venue instruments | L1; Trades; L2 where supported | **Imported; not rechecked.** Source- and instrument-specific historical quotes/trades; distinguish contributor prices from execution data. | [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history) |
