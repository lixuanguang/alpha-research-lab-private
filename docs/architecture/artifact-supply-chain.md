# Artifact supply chain

## Build contract

This boundary records the release requirements that a future trusted artifact
consumer must implement. It does not build, sign, publish, or verify artifacts
today. The former bundle lifecycle and its machine-readable policy were retired
because this repository has no release consumer that could use their output.

`alpha-governance-artifacts release-check` delegates to dependency admission
and then fails closed with a no-consumer finding. The former no-argument check
only repeated dependency-policy parsing and input existence checks after the
artifact framework was removed; that redundant source-check phase is retired.
`make governance-check` retains the actual clarity, dependency and local-link
checks. Passing development checks does not authorize release or deployment.

The current dependency gate rejects release use while QuantLib's source-to-wheel
binding remains unresolved. If that admission is later resolved, the explicit
no-consumer rejection remains until a real release consumer owns the artifact
format, verification inputs, and operational record. There is no bypass for
either condition.

When a consumer exists, its build contract should bind the source commit,
dependency lock, target platform, configuration and model/data references to
the complete artifact digest. It should build once and promote those same bytes.
The consumer must verify a trusted origin and builder identity, exact digest
references, provenance and inventory identities, archive member safety, and
tamper detection before installation. Its tests should cover changed bytes,
unexpected origins, unsafe paths, unknown or missing records, and mismatched
source or dependency identities. Signing, key or identity rotation, registry
retention, state compatibility, rollback and deployment activation belong to
that consumer's runbook and evidence.

The future consumer should retain one release record containing the source
commit, artifact digest, dependency lock, build command, environment,
configuration/model/data references, operating limits, rollback artifact and
state-compatibility result. Activation remains a separate explicit decision;
building or verifying an artifact never grants trading authority.

## Commands

```sh
uv run --frozen alpha-governance-artifacts release-check
```

This diagnostic is expected to fail until both dependency admission and a
trusted release consumer exist. No-argument and retired lifecycle invocations
return usage failures and produce no artifacts.
