# OKX market-data implementation record

Owner: repository founder. Date: 2026-09-16 (Singapore).
Branch: `codex/crypto-l3-collectors`, extending the existing reviewed L3 slices.
Scope: bounded public BTC-USDT spot L2 recording, one-day historical L2 archive
acquisition and deterministic visible-level replay. No M3 closure is claimed.

## Integration and ownership

The maintained [market-data notebook](../../examples/market-data-capture.ipynb)
now covers Bitfinex R0, Coinbase Exchange Level 3 and explicitly labeled OKX L2.
It uses the same connection/capture/persistence/replay sequence and presents a
common evidence table. Historical OKX orchestration lives in the existing
`pipelines/acquisition.py`, exposed as `alpha-acquire archive index/fetch/replay`.
Live OKX uses `pipelines/live.py` and `alpha-collect`; there is no additional
pipeline file or installed command. Venue-specific formats remain in
`data/venues/okx/`. See the [source contract and commands](../data/okx-market-data.md).

| Existing owner | Added responsibility | Acceptance retained |
| --- | --- | --- |
| MR 22 | Official native spot discovery, public `books` connection, acknowledgement, application ping/pong and exact L2 schema | Other products, authenticated VIP channels and regional access require their own evidence |
| MR 23; historical MRs 03–07 | Existing journal/raw-store publication; archive request binds original index, UTC day, URL, limits and local download clocks | Normalized dataset publication and canonical metadata remain with MRs 10–15 |
| MR 24 | Finite live retries and new epochs; bounded historical download retry; incomplete files stay unadmitted | Archive sequence absence cannot prove continuity or automatically repair live gaps |
| MR 25 | Absolute price-level updates, bounded depth, linked sequence reset/no-change rules; archive snapshot/update reader | Aggregate order counts establish neither individual order lifecycle nor queue priority |
| MR 26 | Existing foreground bounded queue, idle/overload/persistence failure reporting | No external supervisor, alerting service or unattended deployment |
| MR 27 | Exact retained input, installed consumers and message-boundary replay parity | General MR 20 replay, broader quality/publication and R1 deployment gates remain |

The request authorizes this additional source; it does not replace the L3 focus.
BTC-USDT has a distinct canonical listing identity and explicit quote currency.
The original Binance configuration, provider adapter, historical notebooks and
`docs/research/p1-baseline.md` remain unchanged. Existing acquisition command
arguments and checkpoint behavior are preserved and covered by regression tests.

## Review boundaries

Review the extension in dependency order: bounded L2 state and source identity;
live transport/replay integration; historical request/raw-store binding; archive
transport and integrity/row reader; existing acquisition-command composition;
notebook and evidence. No dependency, enforcement rule or scanner scope changed.
Historical state limits and missing clocks are separate from live journal receipt
semantics. Publication uses the existing immutable raw store rather than another
storage engine. The archive's staging copy remains available for interrupted-work
inspection; only a verified completion manifest admits replay.

## Verification commands

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/live tests/unit/data/venues/okx tests/unit/data/venues/bitfinex tests/unit/data/venues/coinbase tests/unit/data/test_raw_objects.py tests/unit/data/test_raw_store.py tests/unit/pipelines/test_acquisition.py tests/unit/pipelines/test_acquisition_command.py tests/unit/pipelines/test_acquisition_resume.py tests/unit/pipelines/test_binance_archive.py
uv run --frozen --no-editable mypy --strict src/alpha_research/data/live src/alpha_research/data/venues/okx src/alpha_research/data/raw_objects.py src/alpha_research/data/raw_store.py src/alpha_research/pipelines/live.py src/alpha_research/pipelines/acquisition.py tests/unit/data/venues/okx
uv run --frozen --no-editable ruff check src/alpha_research/data/live src/alpha_research/data/venues/okx src/alpha_research/data/raw_objects.py src/alpha_research/data/raw_store.py src/alpha_research/pipelines/live.py src/alpha_research/pipelines/acquisition.py tests/unit/data/venues/okx
uv run --frozen --no-editable alpha-governance-engineering-standards
uv run --frozen --no-editable alpha-governance-architecture
uv run --frozen --no-editable alpha-governance-ci scan-secrets --all
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
```

Focused cases include price-scale identity, exact decimals, initial snapshots,
wrong predecessors, valid sequence jumps, linked resets, empty updates, malformed
levels, native product mismatch, absent source clocks, disconnect/recovery,
application ping budget, missing history, public HTTP access/redirect/size errors,
truncated gzip and rows, expansion limits, unsafe tar members, bounded prefixes,
retry and failed raw publication. Existing raw-store process-interruption and
Binance/Tardis command/resume tests exercise unchanged historical consumers.

Full hosted CI remains a merge gate; no unrun full `make check` is claimed.
Coinbase live authentication still depends on the local Exchange credentials
and eligibility; OKX is public and needs no credential file.

## Final candidate results

The expanded focused suite passed **209 tests in 29.86 seconds**, with no skips
or deselections. Strict mypy passed 19 files. Changed-path Ruff lint and format,
engineering standards, Bandit, architecture links (40 documents) and dependency
admission (73 locked packages) passed. No dependency or lock change was needed.

Runtime source SHA-256: `e00f84a13948b3cf89ed8308a83e8ca2a5ded54fb836331c5d07d6098b46ee53`.
Candidate wheel SHA-256: `802ddf381679c48ac8de94b96abfa2cb98e7aef8f56ab14a2d60a2a9d4cdc829`. The existing development-only
QuantLib artifact restriction remains unchanged.

Fresh-kernel attempt `e332e7de-a068-4a69-9e32-afe51a7e3c05`
completed all **11 code cells** of the unified notebook. Source-cell SHA-256:
`c3416eb568a99c5243ca06654eedacd7f642e19b6fbb21c8a1ffa03f1d0c95c8`.

The final kernel used the clean installed wheel outside the checkout:

```sh
uv run --frozen --no-editable uv pip install --python /private/tmp/crypto-l3-verification/consumer/bin/python 'nbclient==0.10.4' 'ipykernel==7.2.0' 'nbformat==5.10.4'
/private/tmp/crypto-l3-verification/consumer/bin/python examples/run_notebook.py examples/market-data-capture.ipynb --kernel-python /private/tmp/crypto-l3-verification/consumer/bin/python
```

Earlier uv-kernel runs passed behaviorally but included duplicate non-imported
`.py` files in the existing local virtual environment's package fingerprint.
The clean kernel's recorded implementation identity matches the candidate wheel
and isolated CLI consumer. No source path or scanner exclusion was added.
The final secret scan passed all **200 tracked governed paths**, including new
source files and maintained notebook outputs.

| Real recording | Messages | Snapshots | Updates | Visible state | Detected gaps |
| --- | ---: | ---: | ---: | --- | ---: |
| bitfinex `tBTCUSD` | 382 | 1 | 376 | 50 orders | 0 |
| okx `BTC-USDT` | 186 | 1 | 184 | 800 levels | 0 |

Both live recordings reproduced the entire saved message-boundary state trace
offline. Their saved-input identities and directories are:

- bitfinex: `data/bitfinex/613b3e58-f654-4420-87b3-601554977213`;
  `bdad61d34dd3311d444701e6b71b31cedc991b8d5052629f2e71364603cebb0b` (53,192 bytes).
- okx: `data/okx/live/abd73044-5bf9-4c6a-88ce-e06342ef467c`;
  `c3df4896f45eadaab1810dbbe8c9254bcb9e0feb1c487d9051cec809c5d3928e` (215,552 bytes).

Historical input: `data/okx/history/f9174b1f-343e-4254-98ff-c91c261deee5`.
The complete UTC-day archive is **109,423,187 compressed bytes**,
with 764,149,760 expanded tar bytes. Raw SHA-256:
`fef59b343d1972c32f67583edc538c5d2f7350e6f3a0059e6f87896d7e8bf676`.
Its first 10,000 records comprise 1 snapshot and 9,999 updates,
ending with 800 aggregate levels. Source interval:
2026-09-08 00:00:00.004–00:03:44.624 UTC. The request stops at the record limit;
full-day semantic reconstruction is not claimed. The source supplies no sequence
IDs or original per-record receipt times; gaps remain unknown. Offline prefix
trace identity matched:
`e8c58ef9bc585227184ea43f5ced9ded45ba451ea91b0251544056ef5c5e6811`.

Coinbase credential loading reported the local Exchange key, base64 secret and
passphrase as unfilled; authenticated capture remains access-blocked. Synthetic
schema/snapshot/lifecycle verification passed in the same notebook.

### Installed consumer outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir dist
uv run --frozen --no-editable uv pip install --python /private/tmp/crypto-l3-verification/consumer/bin/python --no-deps --reinstall dist/alpha_research_lab-0.1.0-py3-none-any.whl
# Working directory: /private/tmp/crypto-l3-verification
consumer/bin/python installed_okx_consumer.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private'
```

The retained script and `installed-okx-result.json` verified imports from the
isolated environment's `site-packages`, `alpha-collect` and `alpha-acquire archive`
help, native product discovery, a four-second real OKX capture, live replay
parity, public history discovery, saved archive replay parity and missing-archive
exit 2. No standalone OKX command exists in the installed candidate.

The installed capture recorded 37 messages, 800 levels and zero gaps:
`data/okx/live/f0fb4b75-98db-451e-8372-b73cfa18723a`; raw SHA-256
`e3b1ee16cba1e882eb10ba5a5a2525bc945cb9a81fbd61cedd98d3b534dc25bc`.

The preserved Binance config/transport, original historical notebooks and
`docs/research/p1-baseline.md` passed `git diff --exit-code main -- <paths>`
without changes. All network runs ended; no orders or service activation occurred.

## Review commit sizes

Production code-bearing physical lines against each parent, excluding blank
lines, comments, docstrings and tests:

| Commit | Slice | Added | Deleted | Total |
| --- | --- | ---: | ---: | ---: |
| `863369c` | Decode bounded OKX L2 state with native sequence rules | 140 | 12 | 152 |
| `02ceb58` | Integrate OKX books into the shared live collector and replay | 64 | 12 | 76 |
| `e8854e5` | Bind OKX historical archive selection to existing raw storage | 128 | 8 | 136 |
| `c4a7f58` | Fetch bounded public OKX archive bytes from verified discovery | 86 | 0 | 86 |
| `116294b` | Verify native OKX archives and replay explicit L2 prefixes | 104 | 0 | 104 |
| `53c0f11` | Route durable OKX history through the existing acquisition pipeline | 177 | 2 | 179 |
The 152-line state slice keeps exact L2 reconstruction with its native selection
validation. The 179-line publication/composition slice keeps durable raw
publication, its completion manifest and the existing acquisition entry point
in one tested resource lifetime. These small exceptions to the 150-line review
preference avoid splitting acknowledgement of persisted input across forwarding
layers. Public transport and archive interpretation remain separate smaller
commits. Two maintained JSON selections, tests and the final notebook/documentation
slice are separate from production code-bearing counts.
