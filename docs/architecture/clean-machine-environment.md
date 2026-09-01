# Clean-Machine Developer Environment

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B03 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Repository-local status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Environment definition | [`flake.nix`](../../flake.nix) |
| Environment lock | [`flake.lock`](../../flake.lock) |
| Host-tool record | [`environments/dev/toolchain.toml`](../../environments/dev/toolchain.toml) |

## Objective and delivery boundary

B03 provides a declarative Nix development shell for the supported
`aarch64-darwin` and `x86_64-linux` host systems. The flake contains no
workstation path, Homebrew package, ambient Python, ambient Git, or ambient Make
dependency. It supplies an exact Nix client, CPython, uv, Bazelisk launcher, Git,
GNU Make, CA bundle, and interactive shell from one locked nixpkgs revision.

The environment consumes, rather than changes, B02's build graph. The Bazel
wrapper fixes `USE_BAZEL_VERSION=9.1.0` and executes the Nix-store binary fetched
with B02's reviewed platform digest; `.bazelversion` remains the build-graph
authority. uv uses the flake's CPython 3.12.14 with
`UV_PYTHON_DOWNLOADS=never`; it cannot silently replace that interpreter with a
managed download. `uv.lock`, `MODULE.bazel.lock`, and the B02 source digests
remain authoritative for project and build dependencies.

## Documented prerequisites and bootstrap

The clean host prerequisites are:

- a supported `aarch64-darwin` or `x86_64-linux` system;
- a multi-user Nix installation able to evaluate flakes and reach the configured
  Nix and HTTPS source caches during first realization;
- a clean checkout with enough storage for the Nix, uv, and Bazel caches.

No Docker, Homebrew, system Python, system Bazel, system uv, system Git, or
system Make is a B03 prerequisite. If the Nix installer has not placed its
profile on `PATH`, invoke the stable multi-user profile path directly:

```sh
/nix/var/nix/profiles/default/bin/nix \
  --extra-experimental-features 'nix-command flakes' \
  develop --no-write-lock-file
```

Inside the shell, the supported interfaces are:

```sh
environments/dev/bootstrap.sh verify
environments/dev/bootstrap.sh check
environments/dev/bootstrap.sh rollback
```

`verify` fails unless the platform is supported, the shell marker is present,
every required command resolves from `/nix/store`, exact version output matches,
and uv is bound to the Nix CPython with downloads disabled. `check`, the default,
then checks and synchronizes `uv.lock`, runs the focused B03 Bazel test, and runs
the complete B02 Bazel plus frozen-uv compatibility suite. `rollback` verifies
the same shell and runs `make BUILD_BACKEND=uv check`, demonstrating the retained
pre-B02 build-backend path without invoking Bazel.

The bootstrap requires network access only to realize content-addressed Nix and
locked project/build artifacts that are absent from local caches. Repeated runs
may use caches, but cache presence is not an undeclared correctness input.

## Exact lock and supported-platform evidence

`flake.lock` binds nixpkgs revision
`34ab99075ac4f7e40cf037eef32cb1c360bb85e9` and NAR hash
`sha256-hn1oU2rue2SYK8dAr8+WNZWtbsz1S2W5mnHlSEuh3bo=`. The flake asserts these
exact package versions before producing an output:

| Tool | Exact version | Source boundary |
| --- | --- | --- |
| Nix client | 2.34.8 | Locked nixpkgs derivation |
| uv | 0.12.7 | Official Darwin arm64 and static Linux x86_64 archives with SHA-256 |
| CPython | 3.12.14 | Locked nixpkgs derivation; matches uv and Bazel |
| Bazelisk | 1.29.0 | Locked nixpkgs derivation; matches hosted CI |
| Bazel | 9.1.0 | Official platform binary realized by Nix with B02's SHA-256 |
| Git | 2.55.0 | Locked nixpkgs derivation |
| GNU Make | 4.4.1 | Locked nixpkgs derivation |

The host-tool record adds exact source/digest, license, provisional vulnerability
and maintenance review, native/transitive dependency, supported-system, purpose,
and rollback fields. These are provisional B07 inputs, not final dependency
admission.

Both supported systems evaluate with `nix flake check --all-systems --no-build`.
The repository-local clean realization, exact-tool probe, B03 test, B02 graph,
and uv rollback have executed on `aarch64-darwin`. Protected merged-result
`x86_64-linux` realization and comparison remain target-environment evidence;
the repository does not claim that an evaluation-only result is an executed
Linux build.

## IDE and hook integration

`.envrc` uses the locked flake with `--no-write-lock-file`, so a reviewed direnv
integration cannot refresh the environment implicitly. `.vscode/settings.json`
opens integrated macOS and Linux terminals through the multi-user Nix profile and
points Python tooling at the locked `.venv` created by uv. IDE integration is
convenience over the same flake; it is not a second environment definition.

The existing local pre-commit hooks remain unchanged and run through
`uv run --frozen` inside the shell. B03 does not change hook policy or hosted-CI
selection; B04 and B05 retain those boundaries.

## Bazel equivalence, migration, and rollback

B03 is additive. Existing developers may continue using the documented pre-B03
host prerequisites while the Nix shell is reviewed. The clean-machine `check`
mode executes the same `make check`, Bazel target set, `uv.lock`,
`MODULE.bazel.lock`, sandbox tests, generation tests, governance checks, and
package build used by the existing root interface. It introduces no alternate
compiler flag, dependency lock, test selection, or generated source.

Rollback has two levels:

1. `environments/dev/bootstrap.sh rollback` exercises the retained complete uv
   path from inside the declarative environment.
2. A B03 environment rollback is a reviewed revert of `flake.nix`, `flake.lock`,
   the environment/IDE files, B03 tests, records, documentation, and evidence
   together. The pre-B03 host interface remains documented and unchanged.

A partial revert that leaves the IDE or bootstrap consuming an unreviewed or
missing lock is invalid. Unknown bootstrap modes, unsupported systems, floating
versions, duplicate tool IDs, mutable source records, missing Nix-store commands,
or mismatched exact versions fail closed.

## Risk, gates, and evidence

The A04 facts are: no capital at risk, shared-domain blast radius,
shared-or-candidate materiality for a repository-wide toolchain, no security
privilege, compatibility-window reversal, computational materiality, and no
economic/risk, model, or trading relevance. The resulting class is R2.
QG01-QG06 and QG09-QG14 apply; QG07-QG08 are not triggered and QG15 is not an R2
gate.

The [B03 synthetic local evidence bundle](../governance/evidence/examples/b03-r2-partial/manifest.toml)
binds that classification, exact gates, artifact digests, partial status, and
findings. R2 eventually requires the Platform Code Owner and an independent
domain reviewer.

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B03-F01 | Domain Architecture | Independent domain review and commit-bound Platform Code Owner approval are unavailable during solo bootstrap | Named reviewers approve the exact flake, lock, host-tool record, supported-platform claim, bootstrap, and rollback at the reviewed commit |
| B03-F02 | Platform/CI | Protected merged-result `x86_64-linux` clean realization and retained exact-commit comparison to the verified Darwin/B02 graph are unavailable from this checkout | Protected CI realizes the lock on `x86_64-linux`, runs `verify`, `check`, and `rollback`, and retains matching graph/toolchain evidence for the reviewed merged result |
| B03-F03 | Platform/Security | Final source, license, vulnerability, exploitability, maintenance, and transitive/native dependency admission is B07-owned | B07 admits or replaces every provisional B03 environment input without weakening the lock, supported platforms, bootstrap, or rollback |

These findings are neither waivers nor approvals. B03 remains `partial` until all
three close.

## Operational signals and non-goals

Repository-local signals are flake evaluation/realization failure, lock rewrite,
unsupported platform, host-command fallback, version mismatch, uv interpreter
download, Bazel graph failure, or rollback failure. There is no deployed service,
production monitor, alert, SLO, migration, or operator runbook.

B03 does not implement B04 language/numerical/property standards, B05 affected or
merged-result CI policy, B06 remote cache/execution, B07 final admission, B08
SBOM/provenance/signing, a production environment, deployment, activation,
credentials, market access, venue/account/instrument expansion, limits, or capital
authority.

The next selector is `B04`.
