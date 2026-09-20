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
The original attempts, four volume archives, verification records and private
credentials were copied into the original checkout's ignored
`logs/clearml-acceptance/2026-09-20/` directory. That persistent local directory
has owner-only permissions; the credential file also has owner-only permissions.
Historical records retain their original `/private/tmp` paths and creation
identities. `live-runtime-installation.tar.gz` preserves the owned installed
runtime files and package metadata; its implementation digest was checked against
all six original attempts, and its archive digest/environment are recorded beside
it. It is an installation snapshot, not a newly built or qualified release wheel.
This is local retained evidence, not a shared backup service.

Set `CLEARML_LOCAL_ENV_FILE` to the retained `alpha-clearml-local.env` file.
To stop the current restored instance while retaining its data:

```sh
docker compose --env-file "$CLEARML_LOCAL_ENV_FILE" \
  -p alpha-clearml-reopen -f configs/development/clearml/compose.yaml down
```

The SDK's missing PyPI source distribution is handled by the implemented,
verified upstream source-archive admission rule. The native release restriction
and shared-service qualification remain separate. See the
[roadmap evidence and remaining work](../../../docs/roadmap/README.md#fitted-preprocessing-and-model-evaluation).
