# Retained decision: wheel-only source admission

This note records the one retained exception to the ordinary source admission
contract. It remains reachable because the QuantLib investigation links to it;
the current summary and release boundary are in the [architecture guide](../README.md#dependency-and-release-boundaries).

## Decision

The normal dependency profile requires an exact source distribution and every
locked artifact hash. A source-bound wheel profile may be used only when it
supplies:

- exact package and wheel identities for every supported platform;
- immutable source and native-component evidence with bounded, safe file reads;
- exact builder, build parameters, ordered source materials, and source-to-wheel
  digests; and
- a trusted signer/issuer and Cosign-verified SLSA build attestation.

The separate bounded bootstrap profile accepts publication-only evidence with an
explicitly unverified source-to-wheel binding only for isolated development and
CI. It has an expiry and an enforced release block. Both profiles require an
explicit matching admission record; malformed source metadata never triggers
an automatic fallback. Neither weakens lock, hash, platform, license,
vulnerability, or runtime-install checks. Publication signatures
identify a publisher; they are not treated as build provenance.

## QuantLib 1.43

QuantLib is retained for the C03 date-convention adapter. The exact wheel
attestations, source review, security review, native inventory, compatibility
report, trust root, and verification records live under
`docs/governance/evidence/quantlib-1.43/` and are bound by
`docs/architecture/dependency-admission.toml`.

The source-to-wheel binding is **unverified**. The bounded profile permits
`isolated_development_and_ci` through **2026-10-04**. The artifact supply-chain
boundary therefore blocks artifact creation, signing, publication, and consumer
verification for the graph while this admission remains active. Removing the
record alone cannot clear that block; resolve the evidence gap or remove
QuantLib and its imports, lock entries, and tests together.

## Reversal and review

Revert this note, the policy record, lock identity, tests, and evidence paths
together if the verifier or source-boundary contract is defective. Re-review on
the expiry date, any package or trust-root change, or the first release consumer.
The decision grants no deployment, activation, credential, market, or capital
authority.

Primary references: [PyPI publish attestations](https://docs.pypi.org/attestations/publish/v1/),
[SLSA provenance](https://slsa.dev/spec/v1.1/provenance), and the
[QuantLib 1.43 release files](https://pypi.org/project/QuantLib/1.43/#files).
