# Local dataset versions and retention

Owner: repository founder. Updated 2026-09-20. **Synthetic local research only.**
The `market_data.storage` public API provides `VersionedObject`, `DatasetVersion`
and `LakeFSStorage`. It wraps the pinned lakeFS SDK 1.86.0, without adding a
library command, replacing dataset manifests or changing market knowledge time.
The first consumer is the installed `alpha-backtest` workflow.

## Pin and consume

`LakeFSStorage.resolve(repository, reference, kind=..., objects=...)` resolves an
explicit branch, tag or commit and verifies each expected object at that immutable
commit. Retain the resulting `DatasetVersion` through `DomainCodec`. Its SHA-256
belongs in `BacktestRun.versioned_inputs_sha256`. The inventory must cover existing
`raw/`, `snapshots/` and derived `features/` bytes. The first derived artifact is
`features/diagnostics.json`: the exact encoded tuple from the existing causal
`ResearchInputs.collect(...).features` computation. No model or label is required.

Pass the manifest with `alpha-backtest run --dataset-version ...
--lakefs-endpoint http://127.0.0.1:18000/api/v1 --lakefs-credentials ...` alongside
the normal configured-run options. The private credentials JSON has
`access_key_id` and `secret_access_key`; it is never an artifact or semantic input.
Choose sibling `raw/` and `snapshots/` under one explicit, resolved cache root.
The adapter checks all remote lengths/digests, rejects changed cache bytes and
symlinks, enforces the total byte budget and atomically materializes files. Existing
reader admission revalidates raw/snapshot content and original availability clocks.
The derived feature bytes must match causal recomputation. Retained attempts and
ClearML artifacts include the version manifest, paths and content digests.

For a pipeline, supply the same `--dataset-version` and `--lakefs-endpoint`;
set the worker's `ALPHA_LAKEFS_CREDENTIALS` privately. Resolve mutable names before
execution, retain a branch HEAD containing referenced research inputs, and back up
metadata **and** object storage. A commit ID or tag alone is not retention policy.
Model/report artifact storage stays in ClearML; this does not create a second
catalog in ClearML Data or change existing query APIs.

## Local services

[compose.yaml](compose.yaml) pins lakeFS Community 1.86.0 (Apache-2.0), serves only
`127.0.0.1:18000`, and retains local metadata and object files in one named volume.
Create a mode-600 file outside Git containing a fresh `LAKEFS_LOCAL_ENCRYPTION_KEY`.
Start with `docker compose --env-file "$PRIVATE_ENV" -f
configs/development/lakefs/compose.yaml up -d`. Perform first-user setup through
`POST /api/v1/setup_lakefs` with an explicit local username; save its credentials
privately. No upstream public example credentials are supplied.

The local-file backend does not support the Community Spark sweep. The separate
[gc-compose.yaml](gc-compose.yaml) is the first working S3 retention fixture:
loopback lakeFS at port 18002, an internal MinIO object store with no host listener,
and an opt-in Spark collector. Versions and immutable image digests are pinned.
MinIO `RELEASE.2025-09-07T16-13-09Z` is AGPL-3.0; Spark 4.0.1 is Apache-2.0.
These are disposable synthetic acceptance tools, not a shared-service or deployment
recommendation. Image pinning does not establish vulnerability qualification or
source-to-image provenance. MR 11 retains those operating responsibilities.

Its private environment file also sets `S3_LOCAL_ACCESS_KEY`,
`S3_LOCAL_SECRET_KEY`, `LAKEFS_GC_FILES` (absolute private directory) and
`LAKEFS_GC_REPOSITORY` (the explicit disposable repository). The bucket initializer
creates only the synthetic `research` bucket. Start using the same Compose command
with `gc-compose.yaml`. The collector profile is never started automatically.

The collector directory contains the following pinned downloads, plus a private
`spark.properties`. Verify SHA-256 before execution:

| File | SHA-256 |
| --- | --- |
| `lakefs-spark-client_2.13-assembly-0.22.0.jar` | `1eb7f51bb01389aaaa7764d3317d819798e150d2b0c4a66f6c7d8cf83005802f` |
| `aws-java-sdk-bundle-1.12.797.jar` | `251115656f2b66ad644b6fc69152db5275ed26d8747fecabe59ac59bc1a4b42b` |
| `hadoop-aws-3.4.1.jar` | `01334a07e179cae2b7e251f24857f11e3759108c9d6a79dcbe362a4295227da2` |
| `bundle-2.24.6.jar` | `890bf9f2a80488f7a8aa8277d64d13a9ea3a3cdff8607ef3b63a878d8b467b41` |

The lakeFS jar comes from the versioned [official Spark client bucket](https://treeverse-clients-us-east.s3.amazonaws.com/lakefs-spark-client/0.22.0/lakefs-spark-client_2.13-assembly-0.22.0.jar).
Hadoop AWS and AWS SDK bundle are from their exact version directories at
`repo.maven.apache.org/maven2/org/apache/hadoop/hadoop-aws/3.4.1/` and
`repo.maven.apache.org/maven2/software/amazon/awssdk/bundle/2.24.6/`.
The v1 SDK bundle comes from `com/amazonaws/aws-java-sdk-bundle/1.12.797/`
at the same Maven origin: lakeFS's bulk remover requires v1 while Hadoop 3.4.1
uses v2. The client, Hadoop and AWS SDKs are Apache-2.0. These jars never enter the Python
runtime wheel or lock.

Set `spark.hadoop.lakefs.api.url=http://lakefs:8000/api/v1` and the selected
lakeFS access/secret keys in the private properties file. Set the S3 endpoint to
`http://minio:9000`, region `us-east-1`, path-style access true, SSL false, and the
fixture's S3 keys through `spark.hadoop.fs.s3a.*`. The fixture uses `local[1]`,
`do_sweep=true`, one shuffle partition and disabled Spark UI. Synthetic acceptance sets
`spark.hadoop.lakefs.debug.gc.uncommitted_min_age_seconds=1` so the disposable
control is eligible; zero restores the upstream one-day default. Never use this
test-only age for retained real data. The
[upstream collector contract](https://docs.lakefs.io/admin/garbage-collection/)
owns mark/sweep and minimum-age semantics. Run explicitly:

```sh
docker compose --env-file "$PRIVATE_ENV" \
  -f configs/development/lakefs/gc-compose.yaml run --rm collector
```

The [installed storage consumer](../../../tests/integration/consumers/datasets/versioned_storage.py)
accepts a retained configured-run directory and a new output directory. Set
`ALPHA_LAKEFS_CREDENTIALS`, optional `ALPHA_LAKEFS_ENDPOINT`, and, for the S3
fixture, `ALPHA_LAKEFS_NAMESPACE=s3://research/`. It publishes actual saved source,
snapshot and feature bytes, resolves branch/tag identity, creates a corrected data
branch, and proves the pinned reader/feature results are unchanged. It creates a
`retained` branch, sets default retention to zero days and that branch to 365 days,
and includes a disposable retired object. A third argument reopens the retained
manifest into that named subdirectory, allowing independent post-GC/restore checks.
Add the fourth argument `verify-collection` to require HTTP 410 for the expired
control while the complete pinned inventory still reopens. Do not use the
destructive zero-day fixture policy for valuable research.

## Backup and reversal

Stop lakeFS and MinIO before backing up both volumes. Restore complete metadata
and object tar archives into **new** named volumes under a separate Compose project,
using the same image pins, encryption key and credentials. Stop the original
listeners before starting the restored stack. Reopen every manifest object and
compare exact bytes, then use the existing dataset reader; metadata-only recovery
is insufficient. Never remove a retained branch or sweep valuable data to test
recovery. Retain the wheel, configuration, manifests, attempts and backups together.

`docker compose ... down` preserves volumes; do not add `--volumes`. Reversal stops
these local services and restores the previous wheel/lock while preserving their
records. Existing raw stores and snapshot schemas are unchanged. Shared operation,
long-duration deletion policy, object-store disaster recovery and hostile concurrent
mutation remain unqualified. No deployment or trading authority is granted.
