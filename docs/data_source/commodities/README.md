# Physical commodity and energy data

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
and the [incorporation record](../catalog-incorporation-2026-09-15.md).

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Physical commodities, energy and agriculture fundamentals

Physical spot assessments, inventories, production and weather variables are not exchange futures trades. Preserve units, geography, delivery period, survey reference period and publication availability.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| World Bank — Commodity Price Data / Pink Sheet | Free | Energy / metals / agriculture benchmarks | Reference prices / monthly-annual series | **Imported; not rechecked.** Historical commodity reference data; not executable intraday prices or futures tick data. | [Commodity data](https://www.worldbank.org/en/research/commodity-markets) |
| Dukascopy — commodity / index instrument history | Free | Broker commodity / index instruments, often CFDs | L1; Bars | **Imported; not rechecked.** Broker instrument prices; never substitute for the underlying exchange-listed futures book. | [Historical data](https://www.dukascopy.com/swiss/english/marketwatch/historical/) |
| EIA — petroleum / natural-gas data | Free (API key) | Oil / products / natural gas | Physical prices; inventories; flows | **Imported; not rechecked.** Official energy API; stock, flow and price series have distinct units and release calendars. | [Open Data API](https://www.eia.gov/opendata/) |
| EIA — electricity / other energy | Free (API key) | Power / coal / energy demand and supply | Physical prices; generation; statistics | **Imported; not rechecked.** Official energy series; regional frequency/availability differs by dataset. | [Open Data API](https://www.eia.gov/opendata/) |
| USDA NASS — Quick Stats | Free (API key) | Agricultural production / acreage / yields / prices | Physical-market statistics | **Imported; not rechecked.** Official agricultural survey/census data; geographic level, unit and revisions are essential. | [Quick Stats API](https://quickstats.nass.usda.gov/api) |
