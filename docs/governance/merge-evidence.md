# Merge Request Template and Evidence Bundle

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A05 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Risk class | R0 governance tooling |
| Applicable gates | QG01, QG03, QG12, QG13, QG15 |
| Machine-readable policy | [MR and evidence policy](merge-evidence-policy.toml) |
| MR template | [Pull request template](../../.github/pull_request_template.md) |

## Contract

The policy is authoritative for the required merge-request headings, template,
example paths, package gates, and open findings. `make evidence-check` validates
the policy, checks that the template and policy cannot drift, lints the complete
example MR body, and verifies its evidence manifest and every referenced artifact.
Hosted pull-request CI additionally reads the forge event body and blocks a
missing, duplicated, or empty required field.

An evidence manifest records the exact source commit, roadmap package, accountable
role, A04 classification facts and output, evidence-retention class, additional
package gates, gate disposition, immutable artifact digests, approval evidence,
waived controls, and open findings. Validation recomputes the A04 decision from
the supplied facts. A caller cannot lower the risk class, remove a required gate,
change the retention class, substitute a different commit, reference an artifact
outside the bundle, or modify an artifact without detection.

An `accepted` bundle is valid only when every required class and package gate has
passed, no finding remains, and the commit-bound approvals satisfy the recomputed
A04 reviewer requirements. A `partial` bundle retains all unresolved gates and
findings without treating them as passed. The repository's example is explicitly
synthetic and partial; it proves validation behavior but is not approval,
promotion, release, deployment, or activation evidence.

## Commands

`make evidence-check` runs the repository policy, template, and example checks.
The underlying CLI also accepts repository-relative paths:

```sh
PYTHONPATH=src uv run --frozen python -m alpha_research.evidence \
  --mr-body path/to/mr-body.md
PYTHONPATH=src uv run --frozen python -m alpha_research.evidence \
  --github-event path/to/pull-request-event.json
PYTHONPATH=src uv run --frozen python -m alpha_research.evidence \
  --manifest path/to/manifest.toml --expected-commit-sha FULL_HEAD_SHA
```

The hosted pull-request job uses the event form. Evidence-producing pipelines
must use the actual reviewed head SHA with the manifest form; a branch name,
mutable tag, abbreviated SHA, or merge-base guess is rejected.

## Manifest fields

The version-1 TOML root contains:

- `bundle_id`, `roadmap_id`, `commit_sha`, `owner_role`, `risk_class`, and
  `evidence_retention_class`.
- A complete `[change]` table using A04's five dimensions and applicability facts.
- `additional_required_gates`, `bundle_status`, `waived_controls`, and
  `open_finding_ids`.
- `[[gates]]` entries with `gate_id`, `status`, rationale, and referenced evidence
  IDs.
- `[[artifacts]]` entries with a bundle-relative path and SHA-256 digest.
- Optional `[[approvals]]` entries bound to the same commit and retained HTTPS
  evidence.
- `[[findings]]` entries with an owner, unavailable evidence, and closure
  condition.

Required gates may be `passed`, `failed`, or `deferred`; `not_applicable` is
permitted only for a recorded non-required gate. A passed gate must reference at
least one verified artifact. An accepted bundle cannot contain failed, deferred,
or not-applicable required gates.

## Migration, rollout, rollback, monitoring, and runbook

A05 adds repository governance only. It changes no platform schema, persisted
data, model, runtime state, deployment, activation envelope, credential, venue,
account, or risk limit. Rollout adds the checker to the root command, pre-commit,
and pull-request CI. CI failure output is the operational signal; no production
dashboard, alert, or runbook changes are introduced.

Rollback is a reviewed revert of the template, policy, validator, and automation
while retaining the package record and findings. A replacement cannot weaken
commit binding, required fields, risk reclassification, digest verification, or
approval requirements.

## Review split plan

The A05 epic should be reviewed as `A05a` for the template, policy, and manifest
contract, `A05b` for the validator and adversarial tests, and `A05c` for examples,
documentation, and automation integration. Every slice retains A05; no slice
alone satisfies its repository-local evidence.

## Supplemental unprotected forge evidence

The [A05 unprotected forge exercise](evidence/a05-unprotected-forge-exercise.md)
retains the complete-body passing job, the missing-field blocking job, exact head
and tree identities, and the observed collision when two PR events shared one
head commit. This is useful hosted integration evidence, but `main` was not
protected and no independent Code Owner approved the change. It therefore closes
neither A05-F01 nor A05-F02 and does not change the package's `partial` status.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| A05-F01 | Platform/CI | Protected-forge enforcement and retained exact-commit MR-linter evidence | Exercise complete and missing-field MR bodies on protected `main` against the exact reviewed commit and retain the pass/block jobs |
| A05-F02 | Platform | Commit-bound Code Owner review | A named Code Owner resolves findings and approves the exact A05 commit |

These are not waivers. A05 remains partial until both findings close.

## Non-goals

A05 does not implement A06 inventories, the wave-B build and evidence pipeline,
provenance, SBOMs, signing, release manifests, forge configuration, deployment,
activation, credentials, external systems, market access, capital, or expanded
risk authority.
