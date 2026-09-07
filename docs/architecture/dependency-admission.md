# Dependency admission reference

The [architecture guide](README.md#dependency-and-release-boundaries) is the
current explanation of this boundary. This short page remains because retained
QuantLib evidence links to its stable headings, while the adjacent
`dependency-admission.toml` is the machine-readable policy consumed by the
checker.

The policy binds `pyproject.toml` and the frozen `uv.lock` to exact package
versions, artifact hashes and URLs, source indexes, platform wheels, dependency
edges, licenses, and vulnerability coverage. It rejects missing, duplicate,
mutable, unsafe, or unverifiable identities. Development tools remain outside
the runtime package. `pip-audit` must cover the complete admitted package set.

## Wheel-only source evidence

The ordinary profile requires a hashed source distribution. A source-bound
wheel profile is an explicit alternative for a package without a PyPI source
distribution. It requires an authenticated, complete SLSA build claim:
exact builder and parameters, ordered source materials, source and wheel
digests, trusted signer and issuer, and Cosign verification. The checker never
falls back to this profile to rescue malformed source metadata; the matching
package admission must select it explicitly. It cannot bypass the release boundary.

## Bounded solo bootstrap publication evidence

The bounded bootstrap profile is separate from source-bound admission. It may
accept publication-only evidence with an explicitly unverified source-to-wheel
binding only for isolated development and CI, with an expiry and an enforced
release block. The old institutional evidence packs are retired. Retained native
records are ordinary digest-bound files under
`docs/governance/evidence/quantlib-1.43/`, with the separate 1.40 investigation
kept for historical comparison. Publication attestations identify the publisher;
they do not prove that the inspected source produced the wheel.

## QuantLib exception

QuantLib 1.43 is admitted only for isolated development and CI through
**2026-10-04**. Its source-to-wheel binding remains unverified, so the artifact
boundary blocks release creation, signing, publication, and consumer
verification for the graph. Resolve the evidence gap or remove the dependency,
imports, lock entries, and tests together before clearing the block.

## Commands

```sh
uv run --frozen alpha-governance-dependencies
uv run --frozen alpha-governance-dependencies audit
uv run --frozen pip-audit --locked
```
