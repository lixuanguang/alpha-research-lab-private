# Artifact supply chain

## Build contract

This boundary records the release requirements that a future trusted artifact
consumer must implement. It does not build, sign, publish, or verify artifacts
today; this repository has no implemented release consumer.

`alpha-governance-artifacts release-check` delegates to dependency admission
and then fails closed with a no-consumer finding.
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

## Delivery dependency

The [artifact verification package](../roadmap/future-mr10-to-mr21.md#trusted-deployment-artifact)
implements this contract for the first concrete deployment target. It must
precede any deployed collector or paper/shadow runtime;
it does not depend on a strategy or executable venue adapter. Bounded activation binds
trading authority to the already verified release. Local development installation
can proceed within the current allowance and does not close this release gate.

Artifact verification first resolves the [deployment dependency graph](dependency-admission.md#first-deployment-dependency-decision).
Clearing QuantLib alone does not supply a trusted consumer; implementing a
consumer alone does not clear dependency admission. Both remain required.

## Commands

```sh
uv run --frozen alpha-governance-artifacts release-check
```

This diagnostic is expected to fail until both dependency admission and a
trusted release consumer exist. Unsupported invocations return usage failures
and produce no artifacts.
