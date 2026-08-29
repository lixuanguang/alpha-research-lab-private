# Merge request evidence

## Summary and ownership

### Problem or hypothesis
The repository needs deterministic A05 merge-request and evidence governance.

### Roadmap package and linked issue
A05; the roadmap package is the tracked implementation issue for this fixture.

### Accountable owner
Platform.

### Scope
Validate required MR fields and a SHA-bound, digest-verified evidence manifest.

### Non-goals
No release, deployment, activation, credential, market, data, model, or trading change.

### Risk class and classification facts
R0: no capital, documentation-only blast radius, no data/model or privilege impact,
and immediate reviewed revert.

## Impact

### Affected packages, services, strategies, assets, venues, and accounts
Repository governance files and checks only; no services, strategies, assets,
venues, or accounts.

### Data lineage impact
None; the fixture reads no market or research data.

### Model lineage impact
None; the fixture creates or changes no model.

### Schema, data, model, configuration, and limit changes
Only the repository-local A05 TOML evidence contract; no platform schema or limit.

### Security, entitlement, regulatory, and model-risk impact
Commit and digest integrity are enforced; there is no entitlement, regulatory, or
model-risk scope.

## Evidence plan

### QG01-QG15 applicability and rationale
QG01, QG13, and A05-specific QG15 are mandatory; QG03 and QG12 provide supporting
functional and integrity evidence.

### Test plan and acceptance thresholds
All deterministic success, invalid-input, SHA mismatch, tamper, and path-boundary
tests must pass.

### Benchmark delta
Not computationally material; no performance benchmark changes.

### Point-in-time, leakage, and research validation
Not applicable because no data, feature, label, model, or research result changes.

### Replay, integration, and failure scenarios
Repository example validation is the integration path; malformed manifests and
missing MR fields must fail closed.

### Cost, capacity, and risk evidence
No economic or capital risk; governance integrity is covered by the evidence checks.

### Performance and resilience budgets
Not computationally material; deterministic local file validation must terminate
without network access.

### Evidence manifest
docs/governance/evidence/examples/a05-valid/manifest.toml

## Change and release plan

### Migration and compatibility
Additive version-1 repository contract with no persisted state migration.

### Rollout and activation separation
Roll out through repository checks and PR CI; there is no deployment or activation.

### Rollback target and stop or kill procedure
Reviewed revert of A05 files; no runtime stop or kill procedure is affected.

### Monitoring and alerts
CI job status is the signal; no production monitoring or alerts change.

### Runbook impact
No production runbook impact; the governance document owns usage instructions.

### Post-deploy checks and observation window
No deployment. Protected-forge pass/block exercises remain an open finding.

## Approvals and findings

### Code Owners
Platform Code Owner approval is required and remains pending for the synthetic fixture.

### Independent research or model validation
Not required for this R0 governance change; no research or model behavior changes.

### Risk, SRE, security, and compliance review
Not required by R0; protected-forge Platform/CI evidence remains pending.

### Waivers, open findings, owners, expiry, and closure conditions
No waivers. A05-F01 and A05-F02 remain open with owners and closure conditions in
the policy and package documentation.
