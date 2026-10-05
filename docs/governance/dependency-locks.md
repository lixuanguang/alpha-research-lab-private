# Dependency lock ownership

Owner: repository founder. Status: implemented local validation, checked 2026-09-25.

The repository keeps one uv-generated resolution for each independently installed
environment. These files retain exact versions, dependency edges, platform
markers and artifact hashes. Their size reflects the resolved graph and available
artifacts; it is not a reason to divide a lock into hand-maintained fragments.
uv owns the [lockfile format and generation](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile).

| Project and lock | Installation boundary |
| --- | --- |
| [Research project](../../pyproject.toml), [lock](../../uv.lock) | Full research runtime and development checks, including the local governance package |
| [Collector](../../packages/collector/pyproject.toml), [lock](../../packages/collector/uv.lock) | Independently installed collector and its shared contracts |
| [Execution](../../packages/execution/pyproject.toml), [lock](../../packages/execution/uv.lock) | Independently installed execution application and its shared contracts |
| [Paper services](../../packages/paper-services/pyproject.toml), [lock](../../packages/paper-services/uv.lock) | Supervised paper services, the candidate runtime and the research extensions its release installs |
| [Feast worker](../../configs/development/research-worker/pyproject.toml), [lock](../../configs/development/research-worker/uv.lock) | Isolated Feast service environment with its compatible pandas dependency |
| [ClearML agent](../../configs/development/clearml/worker/pyproject.toml), [lock](../../configs/development/clearml/worker/uv.lock) | Isolated local agent environment and its reviewed overrides |

The shared [contracts package](../../packages/contracts/pyproject.toml) is resolved
inside each consuming application's lock. Research extensions under
`extensions/` are resolved by the research project and the paper services lock;
they may declare only external dependencies. The governance package is resolved by
the research project. Neither needs an additional independently installed
environment merely to shorten another file.

The worker boundaries are intentional: the Feast lock admits pandas 2 while the
research environment uses pandas 3. A uv workspace would share a resolution
across members, so combining these projects would change that isolation contract.
See [uv's workspace guidance](https://docs.astral.sh/uv/concepts/projects/workspaces/).

## Check and change locks

From the repository root, run:

```sh
make lock-check
```

This runs `uv lock --check` for all six projects without writing lockfiles or
synchronizing environments. A stale or missing lock fails the normal source
check before linting, tests or wheel installation. `--frozen` only requires an
existing lock; it does not substitute for checking manifest consistency.

When changing a dependency, edit the owning manifest and regenerate only that
project's lock with the pinned uv version. For example:

```sh
uv lock --project packages/collector
make lock-check
```

Review the resolved version, source and hash changes before committing the
manifest and lock together. Run the owning environment's checks and the
[dependency admission and audit](../architecture/dependency-admission.md) required
for that environment. Root and operating locks also have exact digest bindings
in the admission policy; a lock change must update and revalidate those bindings.
Worker validation remains in the [Feast](../../configs/development/research-worker/README.md)
and [ClearML](../../configs/development/clearml/README.md) guides.

Do not delete artifact hashes, platform variants or transitive dependencies to
reduce line counts. Do not add a custom include/concatenation mechanism to the
lock format. Keep generated locks in Git; `.gitattributes` identifies them as
generated for code-hosting review while their full diffs remain available.

The module decomposition leaves all five lockfiles byte-for-byte unchanged.
The two locks exceeding 1,000 lines are intentional generated-file exceptions;
authored source and documentation are organized by responsibility instead.
