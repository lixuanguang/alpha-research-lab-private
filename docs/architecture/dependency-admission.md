# Dependency admission

This contract keeps the repository's Python dependency graph reproducible with one
supported build path: the root `pyproject.toml` and its frozen `uv.lock`. The
governance checker reads the lock, verifies every admitted package and dependency
edge, and checks that the lock digest matches the policy. It does not install or
modify packages.

## Repository boundary

`docs/architecture/dependency-admission.toml` is the machine-readable admission
record. Its `lock_paths` contains exactly `uv.lock`; the corresponding
`lock_digests` entry binds the complete file with SHA-256. Package names, exact
versions, approved PyPI source, source and wheel digests, platform coverage, and
license decisions are checked against the lock. Unknown packages, alternate
registries, missing hashes, malformed dependency edges, and drifted lock bytes
fail closed.

Development tools remain development dependencies. Runtime source may not execute
`pip install`, `uv add`, or an equivalent package installation. The repository
validator scans owned source and shell roots for those commands and keeps this
runtime boundary independent of the build backend.

`pip-audit` is a required blocking signal over the exact locked graph. A report
must cover every admitted package, bind vulnerability IDs to the package and
version, and provide a current policy decision for each finding. Skips, unresolved
findings, duplicate records, stale decisions, and incomplete coverage fail. The
OpenSSF Scorecard report is an advisory signal and cannot turn a failing dependency
admission into a pass.

## Wheel-only source evidence

Wheel-only admissions retain their complete wheel set, approved registry, source
archive identity, trusted root, in-toto/SLSA claim, and Cosign verification. The
validator rejects unsafe evidence paths, symlinks, duplicate identities, unexpected
sources, malformed wheel names, missing platform wheels, and claims whose subjects
or digests differ from the frozen lock. It authenticates supplied evidence; it does
not silently fetch or substitute artifacts.

## Bounded solo bootstrap publication evidence

The repository's local evidence package records the exact policy review, source and
security reviews, native inventory, compatibility report, trusted root, and locked
wheels used for the bounded QuantLib bootstrap. Each referenced file and wheel is
bound by its recorded SHA-256 digest, and the package remains explicitly partial
until independent review and complete source-to-wheel provenance are available.

QuantLib 1.43 remains a deliberate bootstrap-only admission. Its source-to-wheel
binding is recorded as `unverified`, with the source review, security review,
native inventory, compatibility report, trusted root, and all locked wheels bound
by digest. It is available for isolated development and CI while the review window
is open. `require_release_admission` blocks every artifact lifecycle operation
while this record exists, so removing the record without replacing its evidence
cannot make an unprovenanced native wheel releasable. The record expires on
2026-10-04 and must be resolved by authenticated complete source-to-wheel evidence
or by removing/replacing QuantLib together with its declarations and lock entries.

## Validation commands

Run the policy check from the frozen uv environment:

```sh
uv run --frozen alpha-governance-dependencies
uv run --frozen pip-audit --locked
```

The first command checks policy, lock identity, package provenance, integration
fragments, runtime installation scans, and retained evidence. The second command
produces the vulnerability signal consumed by the policy workflow. Build and
install verification uses `uv build` and a clean environment outside the checkout;
the artifact policy records that project manifest and the same `uv.lock` identity.

The former Bazel requirements subset, module lock, Nix lock, developer toolchain
registry, and migrated build records were retired in cleanup step 2. Their prior
hermetic graph, Nix bootstrap, and duplicate lock-surface checks are no longer
release guarantees. The replacement is the frozen uv lock plus clean wheel build
and installation smoke validation. No dependency restriction was removed to make
the migration pass.
