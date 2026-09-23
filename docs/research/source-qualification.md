# Reviewed provider evidence: strict admission

Owner: repository founder. Implementation date: 2026-09-23.
Status: implementation delivered; actual frozen P1 source qualification remains
unaccepted, with further Binance/Tardis work deferred by the founder.

The later [MR8 scope amendment](saved-baseline-acceptance.md) replaces that milestone's
target with reproducible saved-OKX simulation. It leaves this strict admission
implementation and P1's own requirements unchanged. Historical verification below
is retained under its original scope.

The missing engineering path now accepts retained, externally reviewed provider
evidence through `SourceQualification` and `DatasetInput`, using the existing
publisher, native decoder, eligibility, revision, query, replay, accounting and
reporting owners. The [contract](../../src/market_data/README.md#reviewed-provider-qualification)
describes the fields and the human review boundary. Hashes establish byte integrity;
they cannot establish document authenticity or prove a provider's statements true.

## What the implementation checks

- The source request binds the exact instrument, catalog/units and selected interval.
  The evidence covers the full interval and enumerates the expected economic trade
  count, every full payload version and every retained archive digest.
- Provider bytes, citation locations, publication/retrieval clocks and review identity
  are retained. Coverage/history records cannot certify a future interval. The
  complete revision history is bounded by an explicit `history_through` cutoff.
- Source-backed eligibility is known at each historical interval start, including
  intrahour withdrawals. Original/revised prices and other fields come from native
  archive decoding, with explicit correction links and matching availability facts.
- Earlier archives remain immutable, independently verified inputs. Unknown original
  receipt/knowledge fields remain unknown. Effective knowledge lives on the revision
  envelope; optional native capture evidence can delay, never accelerate it.
- The entire evidence bundle enters version-3 snapshot identity. Reopening and query
  reproduce admission; evidence failure publishes no partial snapshot. Version-1/2
  bytes retain their old identities when new optional fields are absent.

The [QR notebook](../../examples/research-foundations-live.ipynb) accepts
`ALPHA_P1_ADMISSION_INPUT=/absolute/reviewed/dataset-input.json`, preserves its
frozen primary acquisition and causal policy, copies explicitly selected prior raw
archives, and invokes the shared publisher. It also retains the original payload
inventory to support review. Candidate document attachment alone remains insufficient.

## Verification and results

The new [provider qualification tests](../../tests/unit/data/test_qualification.py)
exercise real saved ZIP decoding, positive strict publication and reopening, unknown
original clocks, duplicate lineage, exact original/correction cutoff selection,
wrong request/archive/interval/count, missing/extra versions, inconsistent correction
clocks/references, late or unbacked eligibility, observed gaps, tampered documents,
future document claims, damaged prior archives and intrahour trading suspension.

The former installed engineering-sample consumer ran both witnessed and qualified
synthetic inputs through both unchanged P1 configurations, reports, complete
checkpoints and fresh-process repeat/resume. That demonstration was retired in the
[scaffolding cleanup](../roadmap/post-mr9a-maintenance-review.md); qualification,
CLI publication, engineering scope and economics remain in maintained tests.
The results below are historical, deliberately fabricated **software fixtures**,
never evidence for the real hour.
The complete source lane passed **1,244 tests, three performance cases deselected,
zero skips**, in 137.59 seconds. Ruff/format, strict mypy (353 files), native stubtest
(1,562 modules), engineering/dependency/architecture checks, Bandit, dependency audit
and secret scanning passed. The final installed CLI fixture also passed lint and
strict typing after its output-decoder correction.

Qualified synthetic results, through the installed `alpha-dataset` and existing
configured backtest path:

| Frozen configuration | Ending cash and NAV (USDT) | Position | Fills | Net P&L (USDT) |
| --- | ---: | ---: | ---: | ---: |
| `p1-btcusdt-return-v1` | 999.992765 | 0 | 2 | -0.007235 |
| `p1-btcusdt-no-trade-v1` | 1000 | 0 | 0 | 0 |

The strategy's gross P&L is `-0.007`, fees `0.000215` and slippage `0.00002`:
`-0.007 - 0.000215 - 0.00002 = -0.007235`, exactly. Complete, fresh-process resumed
and repeated result manifests agree byte for byte for both configurations. The
qualified CLI snapshot is
`3d855b09448bb623a419403eef77c21fa0890823f1f549ed29a0937f2c97c0d9`.
The standalone proof is retained in `/private/tmp/source-qualified-cli-final-proof-qualified/`.

The final runtime identity is
`5f65a1e886f18107957d1fe586c9725bd7fc59abacc38e8aa762d52defafec40`;
the installed wheel SHA-256 is
`f12c7ccddfd119d899fd3f12680bb37fab18b82c0b25e0fe21593e35ccf587b0`.
The hash-locked isolated environment and wheel remain at
`/private/tmp/alpha-research-wheel-smoke-x33ef4xq/`. Source and installed checks are
reported separately: initial combined attempts found and fixed a missing-raw-file
error-classification regression, a test regex lint issue and the CLI test's output
decoder. Those failed attempts are retained, not relabeled as successful.
The complete installed `wheel_layout.py` subsequently passed with fresh inputs in
`/private/tmp/source-qualification-final-wheel-inputs/`, the same final wheel and
the corrected CLI consumer. Its original 60-second consumer limits were preserved.
Logs are in `logs/source-qualification/2026-09-23/`, including `wheel-final.log`.

The real-data notebook completed all **37 cells (20 code cells)** through the
installed final runtime, using saved public responses without network access.
Its 27,480 trades still yield an explicit strict refusal: zero observed invalid rows,
gaps and duplicates do not supply missing historical eligibility and provider
qualification. No snapshot or economic result was created. The executed copy is
`examples/runs/research-foundations-live/31ff0779-6e51-4e0c-964d-1245746c67c2.ipynb`;
the retained report is
`data/notebooks/p1-evidence/5ce14416-8b1c-41f2-83ee-0bb83a365729/handoff.md`.
The fresh-kernel repeat also completed every cell and reproduced all **27 semantic
artifacts byte for byte**, including the full input, payload inventory and strict
refusal. Its executed copy is
`examples/runs/research-foundations-live/d7c516fe-36f0-4673-8d3c-f57046601b6b.ipynb`;
its evidence/report directory is
`data/notebooks/p1-evidence/8f870f89-3f7a-4b64-b7db-8b70818fde92/`.
Maintained notebook outputs and execution metadata are cleared; both executed copies
remain retained. The earlier verification record retained notebook SHA-256:
`714e16ab7faeef5df2ea945fdd282e92e540e7593c985dd25c9544db14c7ee4d`.

Pre-merge verification on 2026-09-23 found all 191 runtime Python files identical
to the installed candidate. The 36 focused qualification/quality tests passed again,
as did scoped Ruff checks, the 36-document link check and diff whitespace validation.
The current maintained notebook bytes have SHA-256
`1a4c6fdd3abbdd140f74aef0e6f5cdd26a95b2d7a28d8189f86daf248cf304e5`;
every cell's type and source matches both retained executions exactly, and outputs
and execution counts are cleared. Notebook envelope/metadata differences do not
change the executed cell evidence. Hosted checks are recorded on the pull request.

## Remaining work and limitations

For actual **BTCUSDT, 2024-06-01 [00:00, 01:00) UTC**, the saved archive/capture still
lack reviewed historical status/reference, positive full-interval completeness and
exhaustive full-field original/correction availability records. The software cannot
create those facts. No provider was contacted, evidence purchased or acceptance
criterion amended in that investigation. P1 therefore remains deferred and unaccepted.

The subsequent [provider-records investigation](provider-records.md) retained an
additional Binance correction file and checked available provider contracts. None
qualifies the frozen hour. The [provider request drafts](provider-requests.md)
remain unsent and the proposed outreach has been withdrawn. The founder has
deprioritised Binance and Tardis; these records are not a required next action or
a prerequisite for independent OKX/Bitfinex research workflows.

If this legacy case is explicitly resumed and suitable records are supplied,
review their authenticity and precise claims,
encode the reviewed bundle and existing eligibility/correction records, and rerun
the notebook. A passing source gate enables both unchanged costed engineering-sample
runs and their exact no-trade/cash/position/NAV reconciliation and fresh-process
repeat/resume. Those actual-source results are still required for P1 acceptance;
they are outside the revised MR8 scope.

Supported admission is bounded saved Binance spot individual-trade archives, one
source request per version history. Mixed scopes, general overlap reconciliation,
corrections moving outside the selected window, repeated identical payload reversion
and absent predecessor values remain unsupported. A capture witness binds a single
archive; multi-archive histories use reviewed full-field availability evidence.
No scalability, profitability, deployment or trading claim follows from these tests.

## Run the evidence notebook

Install the current package with `uv sync --frozen --no-editable`, then run from the
repository root. Saved mode verifies already retained public responses and receipts;
no network request is made. Without a reviewed input the expected result is a
retained refusal, not an empirical backtest.

```sh
ALPHA_P1_PUBLIC_MODE=saved \
ALPHA_P1_PUBLIC_DIRECTORY=data/notebooks/p1-evidence/fa8aec4f-cf2a-4f9d-8f89-cd3dac2ebe4c/public \
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/research-foundations-live.ipynb \
  --kernel-python .venv/bin/python
```

Add `ALPHA_P1_ADMISSION_INPUT=/absolute/reviewed/dataset-input.json` only when that
reviewed input exists. The [operations guide](../../examples/notebook-operations.md#frozen-source-evidence)
explains missing source preparation, output retention and exact fresh-kernel reproduction.
The final cell prints the retained handoff report path. Generated source bytes and
executed notebooks remain ignored; no credentials or provider payloads are committed.
