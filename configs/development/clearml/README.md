# Local ClearML integration server

Owner: repository founder. Updated 2026-09-20. **Local development only.**
[compose.yaml](compose.yaml) is a bounded self-hosted tracking/artifact consumer
for [model studies](../../../src/research/models/README.md) and
[bounded economic comparisons](../../../src/simulation/README.md). It exposes API,
web UI and files only on `127.0.0.1:18008`, `127.0.0.1:18080` and
`127.0.0.1:18081`. Databases have no host ports. It creates no workers/agents,
mounts no Docker socket, and has no automatic restart policy. MR06 still owns
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

For repeat use, the existing keys can live in the Git-ignored, mode-600
`secrets/local-services.env`. `make local-services-up` loads it automatically and
starts both local services; `make local-services-status` shows their state, and
`make local-services-down` stops them without deleting volumes. The private file's
`CLEARML_LOCAL_PROJECT` selects another project; omission uses `alpha-clearml-local`.
This workspace retains no ClearML data: every local volume was deleted on 2026-10-06,
so the server starts empty under its default project and needs no setup.
See the [lakeFS startup guide](../lakefs/README.md#local-services) for the shared
file and project selection. SDK callers still explicitly select this file via
`ALPHA_CLEARML_LOCAL_ENV` when using the publication verifier. Browser sign-in
remains separate from the server's SDK keys.

Both manual consumers accept blank lines and whole-line comments, including
indented comments, in this `KEY=value` file.
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
It uses only synthetic data. The feature/model integration test exercises local
model behavior with an explicitly unavailable transport; wheel smoke checks
installation and a small OKX book run. Neither requires Docker. For the
actual server check, first run the offline feature/model, economic or Feast
consumer using the [test guide](../../../tests/README.md). The model workflow
checks fitted, reloaded, rejected, failed and abandoned attempts in ordinary CI.
Domain consumers no longer read credentials or publish to a server.

Copy the [publication verifier](../../../tests/integration/consumers/research/clearml_publication.py)
outside the checkout and run it with the same installed interpreter, explicitly
selecting the generated attempt stores. With `FEATURE_RUN` pointing to fresh
feature/model output, for example:

```sh
ALPHA_CLEARML_LOCAL_ENV="$CLEARML_LOCAL_ENV_FILE" \
  /absolute/core/bin/python -I /absolute/consumers/clearml_publication.py \
  "$FEATURE_RUN/attempts" "$FEATURE_RUN/models/attempts"
```

Economic output has `attempts`, `configured-attempts` and `comparison-attempts`;
Feast output has `attempts`. The verifier uses each attempt's retained destination,
requires the local endpoints, loses one pending receipt per store, and reconciles
in a fresh process. It checks unique tasks, terminal outcomes, unchanged local
histories, idempotent receipts and every uploaded artifact's exact bytes.
Use fresh outputs for the lost-receipt exercise; `resume` before the store paths
rechecks existing publication without injecting another interruption. Research
is not rerun, and the original acceptance records below remain historical.

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
[source admission record](../../../docs/architecture/dependency-admission.md#verified-upstream-source-archives)
and current [release requirements](../../../docs/governance/workflow.md#build-a-release).

## Serial installed research worker

The serial pipeline provides an explicit local worker consumer for
[configured economics](../../../src/research/studies/README.md#configured-economics-reports-and-serial-pipelines).
The Compose stack still starts no workers. The separate
[worker lock](worker/uv.lock) pins ClearML Agent 3.0.3 and its 14 macOS dependencies;
`uv sync --frozen --project configs/development/clearml/worker` installs it outside
the research environment. The agent and runtime both use CPython 3.14.7.

The stable agent's upstream requirements cap Requests below 2.33, Setuptools
below 82 and virtualenv below 21. Those versions failed the local audit with
CVE-2026-25645, CVE-2026-59890 and PYSEC-2026-4011 through PYSEC-2026-4014. The
worker's explicit uv overrides instead pin Requests 2.34.2, Setuptools 83.0.0 and
virtualenv 21.14.1. This is an intentionally qualified local compatibility choice,
not an upstream-supported constraint claim: `uv pip check` reports the original
metadata bounds. The agent has its own vendored `pkg_resources` fallback. The
patched lock passes `pip-audit`, and actual serial installed tasks exercise it.
No audit finding is waived, and no unpinned install occurs during a task.

The virtualenv override was added on 2026-10-01; it also brings python-discovery
1.6.1 and packaging 26.3 into the lock. The agent uses virtualenv only as a
subprocess (`python -m virtualenv <path>`, optionally with `--system-site-packages`).
With the exact locked closure installed, both forms created working CPython 3.14.7
environments with pip, and the agent imported and started. The serial installed-task
run above could not be repeated then because the local services were stopped;
repeat it before relying on the worker.

The local agent uses Apache-2.0; Requests, virtualenv and distlib are Apache-2.0;
certifi is MPL-2.0; psutil is BSD-3-Clause; idna is BSD-3-Clause;
charset-normalizer, filelock, platformdirs, python-discovery, Setuptools and
urllib3 are MIT; packaging is Apache-2.0 OR BSD-2-Clause.
Its wheel includes upstream vendored notices. This service-tool lock is outside
the runtime dependency admission graph, like the Compose server images; it is not
an admitted release artifact. Keep its independent audit and actual execution
record with the runtime evidence. Export/audit it explicitly with `uv export
--frozen --project configs/development/clearml/worker --no-emit-project
--output-file ...` then `pip-audit --requirement ... --disable-pip --no-deps`.

Run exactly one foreground worker on a dedicated `alpha-research-local` queue
with `--cpu-only`; do not enable Docker mode, dynamic workers or parallel services.
Set the existing private SDK endpoints/credentials and
`CLEARML_AGENT_SKIP_PYTHON_ENV_INSTALL=1`. Use a private `CLEARML_CONFIG_FILE` with
explicit writable agent code/cache directories and a distinct `agent.worker_id`.
The agent executes the handoff in its workspace, then the sole installed
`alpha-backtest` command verifies the pinned runtime implementation/environment.
It neither discovers dependencies nor installs the SDK into the research wheel.

```sh
configs/development/clearml/worker/.venv/bin/clearml-agent daemon \
  --queue alpha-research-local --create-queue --foreground --cpu-only
alpha-backtest pipeline --config "$RUN/configured.json" \
  --tracking "$RUN/tracking.json" --inputs "$RUN" \
  --attempts "$RUN/configured-attempts" --output "$RUN/pipelines" \
  --wheel "$WHEEL" --max-bytes 2000000 --queue alpha-research-local
```

Retain the exact installed wheel supplied by `--wheel`; changed installed bytes
or environment fail before a worker reads data. Caching and automatic retries
are disabled. Selection/features precede economics/report with exact upstream
attempt verification. Shared-store workflows serialize through the attempt store's writer
lock. Do not reset failed tasks to reuse IDs: start a fresh pipeline, preserving
failed attempts and dependent non-completion. Publication recovery uses the
existing attempt/task mapping through `alpha-backtest publish`.

The [actual-agent acceptance consumer](../../../tests/integration/consumers/backtest/pipeline_workflow.py)
runs three pipelines, compares CLI output manifests, removes one raw input to
force a failed selection step, restores it for a fresh recovery, and edits a fresh
server task's `Run/configuration` to exercise the same resolved-parameter path as
UI overrides. A changed rule must produce both a changed run identity and changed
economics. Pass retained configured output, a fresh acceptance output, and the
exact wheel as its three arguments, with `ALPHA_CLEARML_LOCAL_ENV` pointing to the
private local credentials. Stop the foreground agent with Ctrl-C when acceptance
ends. This does not authorize unattended jobs, shared service or trading.

## Scheduled study workspaces

MR04's bounded concurrent scheduler composes the existing MR03 study API and
ClearML outbox; it does not replace an active ClearML agent or alter its locked
environment. See the [scheduled study contract](../../../src/research/studies/README.md#scheduled-studies-and-reproducible-workspaces).
Jobs select local or deferred publication, retain a stable idempotency key, and
reopen completed attempts after lost acknowledgement. Publish the retained
outbox with the existing public API or installed publication verifier. The
verifier accepts an **absolute** `ALPHA_CLEARML_LOCAL_ENV` path because its fresh
reconciliation subprocess changes directory.

MR04's local service run uses separate `alpha-workspace-studies` and
`alpha-workspace-studies-restored` projects with task-owned volumes and the same
pinned images. The owning [acceptance record](../../../docs/roadmap/README.md#mr04-delivery-and-acceptance)
links the stopped-volume backup and post-restore byte checks. Those projects' volumes
were deleted on 2026-10-06; the record keeps the evidence.
