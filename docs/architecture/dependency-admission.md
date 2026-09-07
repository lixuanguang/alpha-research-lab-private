# Dependency admission

The dependency boundary has one source of truth: `pyproject.toml` plus the
frozen `uv.lock`. `alpha-governance-dependencies` reads
`docs/architecture/dependency-admission.toml`, verifies the lock's SHA-256
identity, then checks every registry package, exact version, artifact hash,
artifact URL, source index, platform wheel, and dependency edge. It does not
install or modify packages.

The policy records the packages used by the current runtime and development
environment, together with the reviewed license expressions. Development tools
remain development dependencies. Source code and owned scripts are scanned for
runtime `pip install`, `uv add`, and equivalent installation commands.

`pip-audit` remains a blocking check over the exact admitted package set. A
report must cover each name and version once; skipped packages and unresolved
vulnerability IDs fail. Scorecard is an advisory signal and cannot turn a
failed dependency check into a pass.

## Wheel-only source evidence

The retained source-bound profile, when a package has one, requires every
locked wheel filename and digest, approved PyPI origin, source archive revision
and digest, trusted root, attestation claim, and Cosign verification. It rejects
unsafe paths, alternate origins, duplicate identities, missing hashes, and
changed source or wheel claims. The current policy has no source-bound record;
QuantLib remains on the bounded bootstrap profile below.

## Bounded solo bootstrap publication evidence

The old institutional evidence package is no longer an admission input. The
small retained native records are ordinary digest-bound files consumed by the
QuantLib exception and remain reachable at their existing paths.

## QuantLib exception

QuantLib 1.43 is retained for the existing financial convention adapter. Its
source archives, locked wheel identities, native inventory, compatibility
report, trust root, and attestation bundles remain reachable under
`docs/governance/evidence/examples/c03-r2-partial/` and are checked by digest.
The source-to-wheel binding is explicitly `unverified`. The exception permits
isolated development and CI through **2026-10-04**; it expires after that date
unless authenticated complete source-to-wheel evidence is recorded or QuantLib
is removed with its imports, declarations, and lock entries.

Every artifact lifecycle operation calls `require_release_admission`. While the
exception exists, that gate blocks release creation, signing, verification, and
publication, even when lock checks pass. This keeps the unresolved native
uncertainty visible and prevents a development wheel from becoming a release
artifact by deleting a policy record.

## Commands

```sh
uv run --frozen alpha-governance-dependencies
uv run --frozen alpha-governance-dependencies audit
uv run --frozen pip-audit --locked
```

Cosign 3.1.3 is required only for retained wheel-attestation verification. It is
installed by the CI job that runs the dependency admission check. The local
policy parser and lock checks do not fetch source or wheel bytes.
