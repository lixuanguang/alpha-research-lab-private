# Source validation and CI

The standard check is `make check`: frozen lock verification, Ruff formatting and
linting, strict mypy and native-stub checks, the retained clarity/dependency/artifact
and local-link checks, Bandit, dependency auditing, secret scanning, pytest, and an
isolated installed-wheel smoke. Python 3.12.14 and uv 0.12.7 use the single
[lockfile](../../uv.lock). Governance tooling belongs to the development group.

Hosted CI runs source validation once on Linux, followed by runtime wheel smoke
on Linux and macOS. The required check name, `Authoritative merged-result full
lane`, stays stable and fails if either source validation or macOS smoke fails.
Pull requests also verify the checked-out merge commit and its exact base/head
parents. The four-section pull-request template is guidance; there is no evidence
schema, reviewer-role parser, or classification service.

The smoke check builds the runtime wheel, installs its locked external dependencies
with hashes and binary-only enforcement in an empty environment outside the
checkout, and imports public domain APIs with Python isolation enabled. It verifies
that governance and the retired runtime CLI are absent. This is development/CI
installation evidence, not permission to release a QuantLib-containing artifact.
The [dependency decision](dependency-admission.md) retains that restriction.

## Secret scanning

`make ci-secrets-check` runs `alpha-governance-ci scan-secrets --all`. Bounded
repository patterns and the locked `detect-private-key` hook reject credentials,
unsafe paths, unreadable or oversized files, missing scanners and scanner failures.
Diagnostics print pattern identifiers and paths, never matching contents.

## Local validation

Run only the tests relevant to affected behavior while developing, together with
applicable static and policy checks. For example:

```sh
uv run --frozen --no-editable pytest -q tests/engineering/test_package_definition.py
```

Record the actual selected paths, results and unavailable hosted observations in
the change description. Hosted CI owns the complete required lane. `make check`
is available when a full local run is appropriate; focused local validation must
not be reported as a full run.

The former scheduler, event log, package readiness, topology, ownership, inventory,
role approvals and historical evidence validators are retired. Bazel/Nix and
remote-execution records are historical. The
[development workflow](../governance/workflow.md) owns development and activation;
passing CI grants no deployment, credential or trading authority.
