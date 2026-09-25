# Prediction and event-contract data

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
for the limits of imported claims.

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Prediction / event-contract markets

Data access and permission to trade are separate. Binary YES/NO representations require normalization; a private account order feed does not provide market-wide L3.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Polymarket — market WebSocket | Free | Binary event contracts | L1; L2; Trade only | **Imported; not rechecked.** Public aggregated-book and market-event stream; not individual resting-order identities. | [Real-time data](https://docs.polymarket.com/market-data/realtime-data) |
| Polymarket — market metadata / history | Free | Event-contract outcomes | Bars / price history; Reference | **Imported; not rechecked.** Public API products for market definitions and sampled history; not a historical full-book replay. | [Documentation](https://docs.polymarket.com/) |
| Kalshi — public market history | Free | Event contracts | Trade only; Bars; Reference | **Imported; not rechecked.** REST market/trade/candlestick resources; inspect retention and archived-market endpoints. | [API documentation](https://docs.kalshi.com/) |
| Kalshi — market orderbook | Free (account/auth for WS) | Event contracts | L2 | **Imported; not rechecked.** Authenticated WS snapshot/delta price levels; normalize YES/NO-side representation. | [Orderbook updates](https://docs.kalshi.com/websockets/orderbook-updates) |
