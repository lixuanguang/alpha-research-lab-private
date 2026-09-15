# Company fundamentals and reference data

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
and the [incorporation record](../catalog-incorporation-2026-09-15.md).

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Company fundamentals, filings, corporate actions and identifiers

These are not market-depth products. For point-in-time research preserve filing acceptance/publication timestamps, revision lineage, fiscal period, currency/units and the original document. As-reported and later-restated statements are not interchangeable.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| SEC EDGAR — submissions / filing index | Free | US-reporting companies / funds | Filings / reference | **Imported; not rechecked.** Official filing metadata and source documents; acceptance/publication time is the availability anchor, not fiscal period-end. | [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| SEC EDGAR — Company Facts / XBRL | Free | US-reporting companies | Fundamental time series | **Imported; not rechecked.** Structured reported facts; units, taxonomies and repeated/restated facts need normalization. | [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| SEC — Financial Statement Data Sets | Free | US-reporting company financial statements | Fundamentals — bulk | **Imported; not rechecked.** Official flattened quarterly files; preserve source filing links and update/reprocessing versions. | [Bulk datasets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets) |
| GLEIF — LEI entity data | Free | Global legal entities | Reference / entity relationships | **Imported; not rechecked.** Official LEI records and relationship data; LEI identifies entities, not an exchange listing. | [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api) |
| BaoStock — company financial data | Free | Mainland China listed companies | Fundamentals / reference | **Imported; not rechecked.** Selected financial reports/indicators via Python service; verify reporting and announcement dates. | [Knowledge base](https://www.baostock.com/helpDocsHome) |
| OpenFIGI — security identifier mapping | Free; API key for higher limits | Global financial instruments | Reference / identifiers | **Imported; not rechecked.** FIGI mapping service; not price data or a complete point-in-time security master by itself. | [Mapping API](https://www.openfigi.com/api/overview) |
| JPX J-Quants — financial summaries | Free (account; delayed subset) | Japanese listed companies | Fundamentals / reference | **Imported; not rechecked.** Official retail API subset; plan governs history/delay and corporate-use rights. | [J-Quants / plans](https://jpx-jquants.com/) |
| Financial Modeling Prep — company APIs | Free tier; paid expansion | US / global listed companies — endpoint coverage | Fundamentals; corporate actions | **Imported; not rechecked.** Normalized and as-reported products differ; endpoint access/history depends on subscription. | [API catalogue](https://site.financialmodelingprep.com/developer/docs) |
| Alpha Vantage — fundamental endpoints | Free tier; premium endpoints | Supported listed companies | Fundamentals; corporate actions | **Imported; not rechecked.** API statement/company data; quota and per-endpoint paid restrictions apply. | [API documentation](https://www.alphavantage.co/documentation/) |
| Tushare Pro — financial statements | Paid/points entitlement | Mainland China listed companies | Fundamentals; corporate actions | **Imported; not rechecked.** Statements and financial indicators need endpoint-specific permission; preserve announcement dates and report versions. | [Entitlements](https://tushare.pro/document/1?doc_id=108) |
| EODHD — fundamentals / actions | Paid | Global equities / ETFs — coverage-specific | Fundamentals; corporate actions | **Imported; not rechecked.** Normalized company/actions products; audit delisted coverage and point-in-time availability separately. | [API catalogue](https://eodhd.com/financial-apis/) |
| Nasdaq Data Link — Sharadar SF1 | Paid | US company fundamentals | Fundamentals — as-reported/restated dimensions | **Imported; not rechecked.** Specify dimensions and availability fields in sample/schema review; this is not a quotes dataset. | [SF1 product](https://data.nasdaq.com/databases/SF1) |
| JPX — J-Quants Pro / corporate delivery | Paid | Japanese securities / companies | Fundamentals; reference; prices by product | **Imported; not rechecked.** Corporate API/SFTP route; distinct license and products from individual J-Quants. | [JPX distribution comparison](https://www.jpx.co.jp/english/markets/paid-info-equities/historical/index.html) |
| CRSP — corporate actions / security histories | Paid (institutional / academic license) | US listed securities | Reference; returns; corporate actions | **Imported; not rechecked.** Permanent identifiers and historical security records support survivorship-aware research; package scope matters. | [CRSP US Stock Database](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases) |
| S&P Global — Compustat Financials | Paid | North American / global company financials | Fundamentals; point-in-time products | **Imported; not rechecked.** Standardized company data; historical snapshot coverage is product/region-specific. Request point dates, not just restated history. | [Fundamental-data products](https://www.spglobal.com/market-intelligence/en/solutions/products/fundamental-data) |
| S&P Global — Capital IQ As Reported Financials | Paid | Global reported company financials | Fundamentals — as reported | **Imported; not rechecked.** Company-reported statements with standardized mappings; retain document lineage and disclosure timing. | [Fundamental-data products](https://www.spglobal.com/market-intelligence/en/solutions/products/fundamental-data) |
| S&P Global — Capital IQ Estimates Snapshot | Paid | Analyst earnings / financial forecasts | Estimates / point-in-time snapshots | **Imported; not rechecked.** Historical feed snapshots and availability timestamps; do not substitute current consensus for historical expectations. | [Fundamental-data products](https://www.spglobal.com/market-intelligence/en/solutions/products/fundamental-data) |
