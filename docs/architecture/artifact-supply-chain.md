# Artifact supply chain

The artifact boundary builds from one project contract: `pyproject.toml` with the
frozen `uv.lock`. A release candidate is produced by the canonical uv wheel build,
then inspected, signed, published under its content digest, and verified by the
consumer. The workflow runs dependency admission before any artifact tool.

## Build contract

`alpha-governance-artifacts create` accepts an artifact produced by the canonical
uv build invocation and records:

- the complete artifact filename, kind, byte size, and SHA-256 digest;
- the source commit and build platform;
- the normalized backend command identity `uv build --no-build-isolation --wheel --no-sources`;
- the SHA-256 identities of `pyproject.toml` and `uv.lock`;
- normalized SPDX 2.3 output from the admitted Syft version; and
- opaque test evidence files with their copied digest and size.

The bundle manifest is version 2. Version 1 manifests that refer to retired build
targets or duplicate toolchain files are rejected and must be rebuilt. Syft and
Cosign versions remain explicit in the manifest and in policy-bound tool
invocations. The in-toto statement binds the source commit, project manifest, uv
lock, build command, artifact digest, SPDX identity, and builder identity.

The Make build wrapper runs this backend with the frozen environment and supplies
the project and output directory. Those wrapper arguments are intentionally outside
the normalized identity so local and hosted invocations bind the same build backend
while the wrapper controls the checkout and output location.

## Verification and publication

Verification checks the expected immutable `sha256:<64 lowercase hex>` reference,
regular-file and archive safety, every manifest digest and size, the exact bundle
file set, provenance identity and dependencies, SPDX identity, native-library
coverage, signer identity and issuer, and the Cosign signature. It rejects changed
artifact bytes, changed evidence, unknown manifest fields, unsafe symlinks, revoked
signers, malformed provenance, and mutable consumer references. Publication first
verifies a staged copy and creates only one directory at
`<registry>/sha256/<artifact-digest>`.

Every lifecycle operation calls dependency release admission before external tools.
QuantLib's current bootstrap-only, unverified source-to-wheel binding therefore
blocks creation, signing, verification, and publication until its recorded review
condition is resolved. This preserves the native dependency restriction while the
repository moves to uv.

## Tool and evidence boundaries

Syft and Cosign are resolved as ordinary development tools and checked against the
exact versions in the artifact policy. Their output is treated as untrusted input:
JSON duplicate keys, oversized documents, missing native members, and unexpected
tool failures fail closed. The default process runner passes argv without a shell;
the lifecycle does not download or silently regenerate an artifact.

The local B08 evidence remains partial. Protected CI signing, independent review,
registry retention, signer rotation, and recovery exercises are still open findings
and are not implied by a local injected runner.

The retired Bazel label, module lock, Nix toolchain, and four-lock build graph were
removed in cleanup step 2. Their former guarantees are explicitly retired. Clean
`uv build`, installation outside the checkout, digest verification, and the retained
provenance/tamper checks provide the supported replacement evidence.
