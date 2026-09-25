# Positioning, holdings and research factors

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
for the limits of imported claims.

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Positioning, holdings, short interest and research factors

Short-sale volume is not short interest. Holdings disclosures and positioning reports have publication lags. Portfolio-factor returns are constructed research series, not directly tradeable instruments.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| CFTC — futures-only COT | Free | Listed futures positioning | Positioning / statistics | **Imported; not rechecked.** Official aggregated participant positioning; join on publication availability, not just the position reference date. | [COT](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) |
| CFTC — futures-and-options combined COT | Free | Futures / options positioning | Positioning / statistics | **Imported; not rechecked.** Combined-report methodology differs from futures-only; do not concatenate without a report-type key. | [COT](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) |
| FINRA — short-sale volume | Free | US equities | Volume statistics | **Imported; not rechecked.** Reported short-sale volume from covered facilities; neither market-wide short interest nor net short positioning. | [Daily short volume](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data) |
| SEC — fails-to-deliver data | Free | US equity securities — settlement fails | Settlement statistics | **Imported; not rechecked.** Historical aggregate outstanding fails, not daily new fails; not direct evidence of naked shorting or a borrow-rate series. | [FTD datasets](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data) |
| SEC EDGAR — 13F filings | Free | Disclosed institutional holdings | Holdings / filings | **Imported; not rechecked.** Lagged reported holdings with amendments; not live positions or complete portfolio exposure. | [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Kenneth French Data Library — factors | Free | US / regional / global factor portfolios | Research returns / factors | **Imported; not rechecked.** Constructed daily/monthly factors; save downloaded vintage and methodology version. | [Data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) |
| Kenneth French Data Library — sorted portfolios | Free | Equity style / industry portfolios | Research returns / portfolio statistics | **Imported; not rechecked.** Aggregate research portfolios, not constituent-level execution datasets. | [Data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) |
| FINRA — equity short interest | Free (public product access) | US equities | Positioning / statistics | **Imported; not rechecked.** Periodic reported outstanding short positions; observation and dissemination dates differ. | [Short interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest) |
| NSE — margin / securities-lending reports | Free (public downloads) | Indian equities / securities lending | Positioning / statistics | **Imported; not rechecked.** Official published report subsets; not a universal live borrow availability feed. | [Reports](https://www.nseindia.com/all-reports) |
