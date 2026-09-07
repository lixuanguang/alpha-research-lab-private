# Pinned Hermetic Build Graph (Historical)

This page records the retired B02 Bazel contract for provenance. It is kept with
its original evidence links so the historical decision remains auditable. The
active repository path is the pinned uv environment and `make check`; Bazel,
its module lock, and the build-only fixtures are no longer setup or validation
requirements.

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
| Build module | `MODULE.bazel` (retired) |
| Provisional dependencies | `build-tool-dependencies.toml` (retired) |

## Historical objective and delivery boundary

B02 made Bazel the default repository build and test graph. Bazel 9.1.0,
`rules_python` 2.2.0, `rules_buf` 0.5.4, `bazel-skylib` 1.8.2, CPython
3.12.14, and Buf 1.72.0 are exact inputs. `MODULE.bazel.lock` captures module
resolution. The official python-build-standalone and Buf manifests are bound by
SHA-256, while `requirements.bazel.txt` is the exact Bazel translation of the
runtime portion of `uv.lock`. The uv lock remains the transitional Python
resolution authority until B07 admits a final dependency workflow.

The graph contains the current platform package, all thirteen governance commands,
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

The former focused local interface was `make bazel-check`; the former B05 hosted
lane included that graph. Those interfaces were retired after the uv path became
authoritative. [B03](clean-machine-environment.md) and B06
([remote execution](remote-execution.md)) are retained as historical records;
neither supplies an active developer or CI dependency.

## Root interface, migration, and rollback

The historical `BUILD_BACKEND=bazel` interface made `make build`, `make test`,
and `make check` delegate to Bazel. It was removed after the uv path and installed
wheel smoke check became authoritative.

The explicit rollback is:

```sh
make check
```

The active command uses the frozen uv environment. The historical rollback was a
reviewed revert of the module, lock, BUILD files, build fixtures, Make/CI
delegation, inventory/program records, evidence, and documentation together.

## Provisional dependency admission

The historical `build-tool-dependencies.toml` record gave each
new build dependency an immutable version/source digest, purpose, licence,
supported platforms, native/transitive dependencies, maintenance and
vulnerability review statement, and rollback. These records are provisional:
B07 must independently verify exploitability, provenance, licensing, platform
coverage, and continued maintenance before final admission. Build tools may run
during build and CI; package installation inside a production runtime remains
prohibited.

## Evidence and governance

The [B02 synthetic local evidence bundle](../governance/evidence/examples/b02-r2-partial/manifest.toml)
binds the exact facts, QG01-QG06 and QG09-QG14, artifact digests, partial status,
and open findings. Repository-local checks cover pins, lock enforcement, targets,
sandbox exclusion, deterministic SQL/Protobuf generation, dependency-record
shape, Make delegation and rollback, topology/inventory/program integration,
documentation, security scan, and failure propagation. Gate definitions live in
the [operations runbook](../governance/operations.md); current state and
validation results are recorded in the [development workflow](../governance/workflow.md).

## Operational signals and boundary

The historical repository-local signals were lockfile-resolution failure, Bazel
action or test failure, sandbox leakage, nondeterministic generated digest,
missing target, dependency-record drift, CI setup failure, or rollback-path
failure. The active signals come from uv synchronization, source validation,
tests, package installation, and the installed wheel smoke check.

The [development workflow](../governance/workflow.md) owns daily evidence. B02
creates build behavior only and grants no deployment, activation, credential,
market or capital authority.
