# Pinned Hermetic Build Graph

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B02 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Repository-local status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Build module | [`MODULE.bazel`](../../MODULE.bazel) |
| Provisional dependencies | [Build-tool dependency records](build-tool-dependencies.toml) |

## Objective and delivery boundary

B02 makes Bazel the default repository build and test graph. Bazel 9.1.0,
`rules_python` 2.2.0, `rules_buf` 0.5.4, `bazel-skylib` 1.8.2, CPython
3.12.14, and Buf 1.72.0 are exact inputs. `MODULE.bazel.lock` captures module
resolution. The official python-build-standalone and Buf manifests are bound by
SHA-256, while `requirements.bazel.txt` is the exact Bazel translation of the
runtime portion of `uv.lock`. The uv lock remains the transitional Python
resolution authority until B07 admits a final dependency workflow.

The graph contains the current platform package, all nine governance commands,
the documentation bundle, a repository-owned SQL template rule and golden output,
and a test-only Protobuf schema exercised by the pinned Buf binary. It creates no
domain placeholder package and no production schema. The Protobuf fixture proves
toolchain execution and byte-stable descriptor generation; C05 still owns
canonical schemas and compatibility policy.

No C++ or Rust target is selected in B02. The current repository has no native
source or measured native-language need, so fabricating a native placeholder
would violate B01's populated-target rule. B04 now owns and enforces language
admission and sanitizer policy while keeping native languages dormant until a
justified target is introduced. Bazel's host C++
autodetection is not part of the representative B02 target set.

## Hermeticity and reproducibility contract

`.bazelrc` enables Bzlmod with lockfile error mode, strict action environments,
explicit Python package initialization, sandboxed actions, deterministic locale
and timezone, no workspace convenience symlinks, and stable noninteractive CI
output. Avoiding absolute output links also keeps the retained Python sdist path
portable. The Python toolchain is an
explicit CPython patch release instead of a workstation interpreter. Bazel tests
receive only declared runfiles. The negative sandbox test confirms that a local
secret, `.git/config`, an undeclared documentation file, and an injected host
environment variable are unavailable.

The SQL rule uses `ctx.actions.expand_template`; inputs, substitutions, and the
declared output are part of the action key. A golden test checks exact bytes and
an analysis test rejects malformed substitution keys. The Buf test executes with
an empty `PATH`, temporary home/cache directories, fixed locale and timezone,
lints the test schema, generates two descriptor sets, and compares their
SHA-256 digests. Documentation is a declared Bazel filegroup so documentation
changes participate in the representative graph without inventing a publishing
pipeline.

The retained focused local interface is `make bazel-check`; B05 hosted CI now
contains that graph inside its authoritative `make ci-full` interface. CI installs
Bazelisk 1.29.0 from an immutable action commit; `.bazelversion` then selects
Bazel 9.1.0. The workflow intentionally adds no remote cache or remote execution:
B06 owns authentication, isolation, correctness, and local fallback for those
services. [B03](clean-machine-environment.md) now supplies the clean-machine
developer environment and repository-local Darwin equivalence evidence. B02
continues to configure the same graph for hosted Linux; protected merged-result
Linux execution remains external evidence.

## Root interface, migration, and rollback

The default `BUILD_BACKEND=bazel` makes `make build`, `make test`, and
`make check` delegate to Bazel. `make check` also executes `rollback-check`, the
entire pre-B02 frozen-uv validation, smoke, and package-build path. This makes the
migration additive while compatibility is being measured.

The explicit rollback is:

```sh
make BUILD_BACKEND=uv check
```

That command contains no Bazel invocation and is contract-tested. A full rollback
is a reviewed revert of the module, lock, BUILD files, build fixtures, Make/CI
delegation, inventory/program records, evidence, and documentation together.
Removing only the lock or only the delegating surface is invalid and fails the
structural build test.

## Provisional dependency admission

The [machine-readable dependency record](build-tool-dependencies.toml) gives each
new build dependency an immutable version/source digest, purpose, licence,
supported platforms, native/transitive dependencies, maintenance and
vulnerability review statement, and rollback. These records are provisional:
B07 must independently verify exploitability, provenance, licensing, platform
coverage, and continued maintenance before final admission. Build tools may run
during build and CI; package installation inside a production runtime remains
prohibited.

## Risk, gates, and evidence

The A04 facts are: no capital at risk, shared-domain blast radius,
shared-or-candidate data-model materiality, no security privilege,
compatibility-window reversal, computational materiality, and no economic/risk,
model, or trading relevance. The resulting class is R2. QG07-QG08 are not
triggered and QG15 is not an R2 gate.

The [B02 synthetic local evidence bundle](../governance/evidence/examples/b02-r2-partial/manifest.toml)
binds the exact facts, QG01-QG06 and QG09-QG14, artifact digests, partial status,
and open findings. Repository-local checks cover pins, lock enforcement, targets,
sandbox exclusion, deterministic SQL/Protobuf generation, dependency-record
shape, Make delegation and rollback, topology/inventory/program integration,
documentation, security scan, and failure propagation.

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B02-F01 | Domain Architecture | Independent domain review and commit-bound Platform Code Owner approval are unavailable during solo bootstrap | Named reviewers approve the exact graph, toolchain pins, dependency records, compatibility window, and rollback at the reviewed commit |
| B02-F02 | Platform/CI | Protected merged-result Linux execution and retained exact-commit local/CI digest comparison are unavailable from this checkout | Protected CI runs the representative graph at the reviewed merged result and retains target/toolchain digests matching a supported local run |
| B02-F03 | Platform | B03 clean-machine execution passes repository-locally on Darwin; B07 final dependency admission has not occurred | B07 admits or replaces every provisional B02 dependency without weakening the graph or B03 equivalence |

These findings are neither waivers nor approvals. B02 remains `partial` until all
three close. R2 requires the Platform Code Owner and an independent domain
reviewer.

## Operational signals and non-goals

The repository-local signals are a lockfile-resolution failure, Bazel action or
test failure, sandbox leakage, nondeterministic generated digest, missing target,
dependency-record drift, CI setup failure, or rollback-path failure. There is no
deployed service, production alert, or operator runbook in B02.

B02 does not itself implement B03 clean-machine provisioning or B04 engineering
standards; both are separately governed and provisionally implemented. It does not
implement B05 affected/full or schema-compatibility CI policy, B06 remote
cache/execution, B07 final dependency admission, B08 SBOM/provenance/signing, C05
domain schemas, production data or model behavior, deployment, activation,
credentials, venue or market access, limits, or capital authority.

The successor B03 environment is provisionally implemented separately; B02
remains partial on its own evidence and findings.
