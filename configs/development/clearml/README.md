# Local ClearML integration server

Owner: repository founder. Updated 2026-09-20. **Local development only.**
[compose.yaml](compose.yaml) is a bounded self-hosted tracking/artifact consumer
for [model studies](../../../src/research/models/README.md). It exposes API,
web UI and files only on `127.0.0.1:18008`, `127.0.0.1:18080` and
`127.0.0.1:18081`. Databases have no host ports. It creates no workers/agents,
mounts no Docker socket, and has no automatic restart policy. MR 11 still owns
shared-service/deployment qualification, authentication hardening and admission.

Images are pinned to both versions and immutable registry digests in Compose:
ClearML Server 2.4.0 (SSPL-1.0), MongoDB 8.0.15 (SSPL-1.0), Redis 8.2.3
(AGPL-3.0 is an available licensing option), and the Elasticsearch 8.19.9
binary distribution (Elastic License 2.0). The ClearML SDK is separately pinned
to 2.1.12 (Apache-2.0) in the Python lock. Image pinning and this license record
are not vulnerability qualification or source-to-image build attestation.
The ClearML server image uses Linux amd64 emulation on the development arm64 Mac;
this is functional integration evidence, not a throughput or latency benchmark.

## Start and connect

Docker Desktop must be running. Create a private environment file outside Git
containing fresh values for `CLEARML_LOCAL_ACCESS_KEY` and
`CLEARML_LOCAL_SECRET_KEY`; restrict its permissions to the owner. These replace
the upstream public default test-user credentials. Do not use production secrets.
With its absolute path in `CLEARML_LOCAL_ENV_FILE`:

```sh
docker compose --env-file "$CLEARML_LOCAL_ENV_FILE" \
  -f configs/development/clearml/compose.yaml up -d
curl --fail http://127.0.0.1:18008/debug.ping
```

Set the SDK's `CLEARML_API_HOST`, `CLEARML_WEB_HOST` and `CLEARML_FILES_HOST` to
the three localhost URLs. Set `CLEARML_API_ACCESS_KEY` and
`CLEARML_API_SECRET_KEY` to the private local values. Keep secrets out of model
configurations and output manifests. The file service intentionally has
unauthenticated local access; loopback listeners are mandatory. This setup is
unsuitable for a public/shared host or untrusted local users.

The UI is [local ClearML](http://127.0.0.1:18080). The API readiness check does not
prove a model upload; the installed acceptance consumer exercises that boundary.
It uses only synthetic data. `make wheel-smoke` exercises local model behavior
with an explicitly unavailable transport and does not require Docker. For the
actual server acceptance run, set `ALPHA_CLEARML_LOCAL_ENV` to the private file
and invoke the installed feature/model consumer with a fresh output directory
and copied fixture inputs (`binance-archive.json`, `binance-archive-spot.json`,
`membership-corrections.json`). It retains no-fit, fitted, rejected, failed and
abandoned attempts and injects a lost publication receipt before reconciliation.

## Stop, retain and reopen

```sh
docker compose --env-file "$CLEARML_LOCAL_ENV_FILE" \
  -f configs/development/clearml/compose.yaml down
```

Named volumes preserve Mongo metadata, Elasticsearch metrics, Redis and actual
file-server artifacts. Do not add `--volumes` when retaining evidence. Stop the
stack before taking a consistent backup of all four volumes. Retain the Compose
file/image digests, the private credentials separately, and the complete local
attempt/raw/snapshot stores. Restore to a separate local project/volume set and
reopen metadata plus downloaded model/artifact bytes, comparing their SHA-256
against the retained version manifests. A metadata-only export is insufficient.

Changing image versions or enabling a shared service needs its own compatibility,
security, backup and operational evidence. Reversal stops this local stack and
preserves volumes and retained attempts; there is no agent workload or trading
activation to reverse.

## Local acceptance record

On 2026-09-20, the installed consumer published six attempts and two model states.
A stopped-volume backup was restored into the separate `alpha-clearml-reopen`
project. The restored stack is the currently running local instance; the original
`alpha-clearml-local` volumes are preserved. Fresh SDK/HTTP reads verified task
outcomes, input/output model associations, exact artifacts and dashboard projections.
The original attempts are in `/private/tmp/alpha-model-integration-06`; the four
volume archives and verification record are in
`/private/tmp/alpha-clearml-backup-20260920`. Preserve these local-only files before
temporary-directory cleanup. The private credentials remain outside Git at
`/private/tmp/alpha-clearml-local.env` (owner access only).

To stop the current restored instance while retaining its data:

```sh
docker compose --env-file /private/tmp/alpha-clearml-local.env \
  -p alpha-clearml-reopen -f configs/development/clearml/compose.yaml down
```

The SDK's missing PyPI source distribution still blocks repository dependency
admission; successful Docker integration does not waive that gate. See the
[roadmap evidence and remaining work](../../../docs/roadmap/README.md#fitted-preprocessing-and-model-evaluation).
