# Isolated Feast offline worker

This environment is a local development worker for the Feast offline bridge. It
is separate from the core research runtime because the core runtime pins
`pandas==3.0.5`, while Feast 0.66.0 requires a pandas 2 release. The worker
lock therefore carries its own CPython 3.14 environment:

| component | worker pin |
| --- | --- |
| Python | 3.14.7 (the lock requires `==3.14.*`) |
| Feast | 0.66.0 |
| pandas | 2.3.3 |
| NumPy | 2.5.3 |
| PyArrow | 25.0.1 |

DuckDB 1.5.5 and Polars 1.44.2 belong to the core runtime and are not installed
into this worker. Feast is not added to the core dependency set. Keep both
locks independent; never resolve Feast by weakening the core pandas pin.

## Setup and lock audit

From the repository root, create or refresh only this worker environment with
the checked-in lock:

```sh
UV_CACHE_DIR=/private/tmp/uv-cache-research-worker \
  uv sync --frozen --project configs/development/research-worker
```

The worker lock and environment can be checked without touching the core
environment:

```sh
UV_CACHE_DIR=/private/tmp/uv-cache-research-worker \
  uv lock --check --project configs/development/research-worker

configs/development/research-worker/.venv/bin/python -c \
  'import feast, numpy, pandas, pyarrow; print(feast.__version__, pandas.__version__, numpy.__version__, pyarrow.__version__)'
```

For an independent vulnerability audit, export the fully hashed lock and run
`pip-audit` from the core tooling environment. The worker environment is a uv
environment and intentionally has no `pip` executable:

```sh
UV_CACHE_DIR=/private/tmp/uv-cache-research-worker \
  uv export --frozen --project configs/development/research-worker \
  --no-emit-project --output-file /private/tmp/research-worker-requirements.txt

.venv/bin/pip-audit \
  --requirement /private/tmp/research-worker-requirements.txt \
  --disable-pip --no-deps --format json \
  > /private/tmp/research-worker-audit.json
```

The lock audit is independent of the core dependency admission graph. The
development audit recorded all locked packages with an empty vulnerability list.
The audit command requires access to the configured package advisory service;
failure to reach it is not a clean audit result.

## Minimal installed worker handoff

The repository has one installed `alpha-explore` application entry point. The
worker command module intentionally has no `__main__` guard, so that the core
application does not create a second installed command. The core caller passes
the absolute path of the installed `applications/explore/command.py` to the
separately locked interpreter and invokes its `main(["feast-worker"])` through
the standard-library `runpy` handoff:

```sh
WORKER_PY=/absolute/checkout/configs/development/research-worker/.venv/bin/python
INSTALLED_COMMAND=/absolute/installed/site-packages/applications/explore/command.py

"$WORKER_PY" -c \
  'from runpy import run_path; raise SystemExit(run_path("/absolute/installed/site-packages/applications/explore/command.py")["main"](["feast-worker"]))' \
  < /absolute/request.json > /absolute/result.json
```

`request.json` is the bounded `offline-feature-request-v1` payload produced by
the core bridge. The worker reads at most 16 MiB from stdin, imports Feast only
inside the worker process, and writes one `offline-feature-result-v1` JSON
payload. A nonzero exit or malformed result is a bridge failure. Do not invoke
the source file as a script; use the handoff above with the installed file so
the worker executes the exact installed application bytes selected by the core
consumer.

## What the worker admits

The worker is deliberately limited to a local Feast `FileSource` and an
offline `FeatureView`. Before the SDK call it:

1. checks the requested Feast version against the installed `feast.__version__`;
2. decodes and hashes the retained registry bytes, resolves the registry path
   from `FeatureStore.config`, and requires byte-for-byte equality;
3. resolves the registered feature view and its local batch-source path, then
   requires the source SHA-256 to match the retained source snapshot;
4. builds the requested entity/decision grid and calls
   `get_historical_features(..., filter_by_created_timestamp=True)`; and
5. requires a complete entity/decision alignment and preserves the SDK's exact
   feature string values.

Feast's ordinary event-time join does not prove revision knowledge. The bridge
therefore requires `eligibility="immutable-source"`; the source snapshot,
source digest, registry bytes and source version are part of the request and
result identity. A worker cannot substitute a mutable or unverified source.

The source event and availability clocks must be registered feature fields. The
worker recognizes event fields named `feature_event_timestamp`, `event_at` or
`feature_timestamp`, and availability fields named `created_timestamp`,
`available_at` or `created_at`. It never substitutes the entity decision clock
for either field. If a matched non-null row does not carry both clocks, the
worker fails closed. `filter_by_created_timestamp=True` is the Feast created-time
eligibility check. The current fixture's `FeatureView` omits a registered
revision metadata field, so its SDK rows carry `revision_identity=null`. Feast
can expose a registered revision field when a view includes one; a future worker
schema must explicitly map that field and never infer or synthesize an identity.
The immutable source digest remains the retained snapshot identity. The MR3
converter retains per-point revision identities when those are present in its
verified source payload and never invents one for Feast.

The core adapter applies the remaining causal contract after the worker result
is decoded:

- entity type and full entity key are retained on every row;
- `ttl_us` is explicit and positive; a non-null value is rejected when its
  event clock is unavailable at the decision or when the elapsed age is greater
  than the declared TTL;
- values remain canonical reduced `numerator/denominator` strings, including
  `0/1`; no decimal or float conversion is allowed; and
- missing entities and ineligible rows remain explicit nullable observations
  with a missing reason. No imputation or online-store fallback is performed.

## Synthetic SDK evidence

The maintained [installed consumer](../../../tests/integration/consumers/research/offline_features.py)
passed against the real Feast 0.66.0 worker on 2026-09-21. It creates a local
Parquet source and registry from a verified MR 3 feature attempt, then invokes
the command module from the installed core wheel in the separate interpreter.
The [test guide](../../../tests/README.md) owns the reproducible invocation.

Baseline retrieval matched two exact MR 3 values and one explicit missing entity.
A late correction remains unavailable before its declared availability at
`2024-06-01T00:00:10.250000Z` and returns exact `9/10` afterward; a one-second
TTL request returns an explicit expired value. The source and registry digests
for the final fixture are:

```text
registry SHA-256: 2aa0fa0d9147cb4322e597709c2776d0803b4a2989610b4d475837dffb32c46c
source SHA-256:   5d26433546c43f61a7a60c98fc376eb5019e8a99ba74664aacf94beb1f6f2349
```

The formal application retained the request, MR 3 source, causal reference, SDK
result and comparison in attempt `b3d1b68c75d0423dba90182d7abd0aa0`. ClearML task
`1c58dfe1bf194ad4b5322a384000af3b` published all five artifacts, and downloaded
bytes matched their manifest hashes. The complete all-marker worker lock audit
covered 64 external packages without findings; the current platform installs 63.
Core tests separately cover malformed metadata, noncanonical exact values,
missing clocks and rejected formal comparisons.

The fixture's local paths and generated registry identity are acceptance
evidence, not release inputs. Retained owner-only output is under the primary
checkout's ignored `logs/research-comparison-acceptance/2026-09-21/` directory.

## Scope and limitations

This worker is local-only synthetic research infrastructure. It does not start
Feast servers, materialize an online store, read an online feature API, acquire
remote sources, or authorize deployment or trading. Local file sources with
retained bytes are the only admitted source class. Remote/object-store paths,
missing registry/source evidence, absent source clocks and SDK-version drift
fail closed. The worker lock is an environment for the bounded consumer, not a
core release dependency or a release qualification record.
