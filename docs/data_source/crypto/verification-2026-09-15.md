# Crypto source verification — 2026-09-15

## Scope and result

This is a source survey for the [crypto guide](README.md), performed against
primary provider documentation and two bounded public Binance archive downloads.
It is separate from the integrated acquisition acceptance. No strategy,
canonical dataset, L2 reconstruction or new runtime adapter was implemented.

The substantive corrections are aggregate fills versus individual trades,
approximately 30-second percentage-depth summaries versus five-second L2,
variable funding schedules, Coinalyze's rolling intraday history, Deribit DVOL
versus an undefined basis series, and Alpaca/Kraken routing versus Binance.
The guide links the primary sources beside each claim. OKX and Bybit L2 portal
observations from the same day's source investigation are recorded there;
neither L2 archive was downloaded or replayed.

## Retained samples

Local-only directory: `data/binance-archives/source-survey-2026-09-15/`.
The existing `.gitignore` excludes this directory through its Binance archive
rule. It contains the ZIPs, publisher checksum sidecars and `observations.json`,
recorded at `2026-09-15T12:56:13.253295+00:00`. These are private working copies
under the existing storage preference, without a new redistribution or retention
entitlement. This document retains small identities and observations, not raw rows.

| UTC partition and source | ZIP bytes | Publisher-verified SHA-256 |
| --- | ---: | --- |
| [BTCUSDT USD-M bookDepth, 2024-06-01](https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2024-06-01.zip) | 456,701 | `ad24f75eec3b8ef38023126a020d4bc1829ca433f1c82cc75414250030606bbb` |
| [BTCUSDT USD-M metrics, 2024-06-01](https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-01.zip) | 10,959 | `f1e27327e1af18eb3aa57663530e3bc7e340237aaca5e6b3ec4384a039dbd6b0` |

The sidecars are published at each ZIP URL plus `.CHECKSUM`. Retrieval used
`curl --fail --location --connect-timeout 10 --max-time 45`, a 2,097,152-byte
limit for each ZIP and a 4,096-byte limit for each checksum. For example, this
exact download command ran from the repository root after creating the directory:

```sh
curl --fail --location --connect-timeout 10 --max-time 45 --max-filesize 2097152 'https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2024-06-01.zip' --output data/binance-archives/source-survey-2026-09-15/BTCUSDT-bookDepth-2024-06-01.zip
```

The first sandbox attempt failed DNS resolution before receiving data; an
approved network retry succeeded. No credentials were supplied. Python's
`hashlib`, `zipfile` and `csv` verified the expected publisher filename/hash,
single matching CSV member, expanded size below 16 MiB and ordered timestamps.
Reading the member to completion also checked its ZIP CRC.

## Cadence evidence

| Check | bookDepth | metrics |
| --- | --- | --- |
| CSV data rows | 28,800 | 288 |
| Distinct timestamps | 2,880 | 288 |
| First UTC timestamp | 2024-06-01 00:00:06 | 2024-06-01 00:00:00 |
| Last UTC timestamp | 2024-06-01 23:59:31 | 2024-06-01 23:55:00 |
| Adjacent timestamp gaps | 24–36 seconds; median 30 | 300 seconds for all 287 gaps |
| Additional structure | Ten percentage rows at every timestamp; ±1, ±2, ±3, ±4, ±5 | Includes OI quantity/value and long/short metrics |

All widening bands in the depth sample had nondecreasing depth and notional on
both sides: zero monotonicity violations. This supports, but does not establish
the publisher's formal definition of, cumulative bands. The band reference price
and rounding remain unresolved. The cadence observations apply to this
instrument/day, not every symbol or future archive revision. A valid checksum
establishes matching publisher bytes, not completeness of market observations.

The following local checks ran from the sample directory:

```sh
shasum -a 256 -c BTCUSDT-bookDepth-2024-06-01.zip.CHECKSUM
shasum -a 256 -c BTCUSDT-metrics-2024-06-01.zip.CHECKSUM
python3 - <<'PY'
import csv
import io
import statistics
import zipfile
from datetime import datetime

for kind, column in [('bookDepth', 'timestamp'), ('metrics', 'create_time')]:
    with zipfile.ZipFile(f'BTCUSDT-{kind}-2024-06-01.zip') as archive:
        with archive.open(f'BTCUSDT-{kind}-2024-06-01.csv') as member:
            rows = list(csv.DictReader(io.TextIOWrapper(member, encoding='utf-8')))
    timestamps = list(dict.fromkeys(row[column] for row in rows))
    times = [datetime.fromisoformat(value) for value in timestamps]
    gaps = [(right - left).total_seconds() for left, right in zip(times, times[1:])]
    print(kind, len(rows), len(times), min(gaps), statistics.median(gaps), max(gaps))
PY
```

Both checksums passed. Cadence output:

```text
bookDepth 28800 2880 24.0 30.0 36.0
metrics 288 288 300.0 300.0 300.0
```

## Repository validation and limits

The change adds a source index, crypto guide and this evidence record, linked
from the documentation map. No runtime code, configuration, notebook, dependency
lock or P1 specification changed. Reversal is removal of these documentation
additions and the index link; it does not affect the current trade acquisition.

From the repository root:

- `uv run --frozen --no-sync alpha-governance-architecture`: passed for 26
  documents. The first attempt could not open uv's existing cache inside the
  sandbox; the approved retry passed.
- `git diff --check`: passed.
- `git check-ignore data/binance-archives/source-survey-2026-09-15/observations.json`:
  confirmed the probe output is ignored.

The link checker covers `docs/**/*.md`, including this entire addition, but skips
external URLs. External facts were reviewed using the linked provider pages; a working
documentation page does not prove endpoint availability or user entitlement.

The documentation index is also the package metadata README. Its navigation
change does not alter runtime behavior; no wheel rebuild, installed-consumer
rerun or fresh notebook execution is needed to verify these source-survey facts.
The crypto guide links the current acquisition interface. Full provider
backfills, historical option-chain availability and L2 replay remain unverified.

## Source-summary follow-up

The source index now separates 37 provider/market/dataset entries into the six
requested columns, with free access before paid access. A one-off table check
confirmed six cells per row and the access ordering. The documentation checker
and `git diff --check` passed again using the commands above.

Additional primary-document checks covered Tardis's Binance and Deribit catalogs,
its free sample dates and paid access, and Alpaca's quotes and pricing pages.
The [Alpaca quote reference](https://docs.alpaca.markets/us/reference/cryptoquotes-1)
sets the Kraken US (`us-1`) quote-history start at 2025-10-14 00:00 UTC.
The [Tardis Deribit catalog](https://docs.tardis.dev/historical-data-details/deribit)
documents historical `options_chain` samples; selected files remain untested.
No additional market-data files or authenticated endpoints were tested for this
table update. The existing sample results above remain the byte-level evidence.
