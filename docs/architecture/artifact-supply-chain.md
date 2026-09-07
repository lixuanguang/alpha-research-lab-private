# Artifact supply chain

This boundary verifies a built artifact before a release consumer can use it.
The policy binds the root project manifest and `uv.lock`, accepted artifact
kinds, archive member limits, native-library markers, in-toto/SLSA identities,
and the protected-main Cosign identity. `alpha-governance-artifacts` does not
maintain package status, review gates, role catalogs, or evidence packs.

Bundle creation hashes the complete artifact and test records, records the
source commit, normalized build command and platform, emits a deterministic
SPDX inventory, and writes in-toto provenance. Verification rejects changed
artifact bytes, changed manifest or provenance identities, unsafe paths,
unknown fields, incomplete native-library coverage, revoked signers, and
mutable digest references. Cosign receives fixed argv and a pinned executable;
the lifecycle never downloads or silently rebuilds an artifact.

Publishing verifies a staged copy and writes exactly one content-addressed
directory at `registry/sha256/<artifact-digest>`. Consumers should retain the
digest returned by verification and the matching source commit. The dependency
admission gate runs before each lifecycle operation. QuantLib's current
source-to-wheel binding is unresolved, so release creation, signing,
verification, and publication remain blocked until the exception is resolved.

The policy is intentionally local and declarative. It is not a release approval
workflow or a claim of hosted signing, registry retention, signer rotation, or
live deployment readiness. Those controls require a concrete release consumer
and should be added with that consumer's tests.

## Commands

```sh
uv run --frozen alpha-governance-artifacts
uv run --frozen alpha-governance-artifacts create ARTIFACT KIND BUILD SOURCE_COMMIT TESTS OUTPUT
uv run --frozen alpha-governance-artifacts verify BUNDLE SHA256
```
