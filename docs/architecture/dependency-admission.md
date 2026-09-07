# Dependency admission reference

The [architecture guide](README.md#dependency-and-release-boundaries) is the
current explanation of this boundary. This short page remains because retained
QuantLib evidence links to its stable headings, while the adjacent
`dependency-admission.toml` is the machine-readable policy consumed by the
checker.

Schema version 3 binds the frozen `uv.lock` to exact package versions, artifact
hashes and URLs, the reviewed PyPI simple index, Darwin arm64 and Linux x86_64
wheel coverage, dependency edges, licenses, and vulnerability coverage. The
checker fixes the lock path and `src`/`tools` runtime scan roots directly;
unused configurable copies of those boundaries were retired. `uv lock --check`
separately ties that lock to the project manifest. The admission checker rejects
missing, duplicate, mutable, unsafe, or unverifiable identities. Development
tools remain outside the runtime package. `pip-audit` must cover the complete
admitted package set, and every finding blocks admission because no vulnerability
waivers are retained.

## Wheel-only source evidence

The former source-bound SLSA wheel profile is retired: it was empty and had no
current consumer. Advisory Scorecard reports, vulnerability-waiver records, and
general emergency-override records are retired for the same reason. Their
parsers, model types, CLI routes, and exclusive tests were removed together.
An ordinary package must continue to provide a digest-bound source distribution;
no alternate profile silently rescues malformed source metadata.
The former `audit-report` command, `PipAuditRunner`/`run_pip_audit` forwarding
API, and package `__main__` forwarding module were also unused and retired;
`audit` remains the canonical scanner command.

## Bounded solo bootstrap publication evidence

The bounded bootstrap profile is the retained native exception. It may
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
