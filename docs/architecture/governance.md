# Architecture Decision, Deprecation, and Exception Governance

## Purpose

This A02 process governs cross-cutting architecture choices. The
[decision log](decisions/README.md) is authoritative for ADR status. Under the
[current operating policy](../governance/domain-ownership.md#current-operating-policy),
`Founder accepted` decisions authorize repository implementation after the founder
decides the scope, rationale, alternatives and reversal. `Accepted` continues to
mean institutional acceptance with the existing commit-bound review evidence.

## When an ADR is required

Create an ADR before a change selects or materially changes:

- build systems, toolchains, language/runtime roles, dependency policy, or native
  boundaries;
- canonical schemas, identifiers, time semantics, storage, transport,
  persistence, or event ordering;
- service/process splits, control/data planes, runtime lanes, deployment,
  activation, observability, recovery, or security zones;
- a dependency-rule exception, breaking compatibility change, or reversal of an
  accepted cross-cutting decision.

Local implementation details that preserve an accepted contract do not need a
new ADR. When uncertain, record a short proposed ADR rather than hiding a
cross-cutting choice in code.

## ADR workflow and lifecycle

1. Copy [the template](decisions/template.md) to the next contiguous four-digit
   identifier with a lower-kebab-case slug.
2. Record the owner, context, measurable drivers, at least two meaningful
   alternatives, consequences, migration/rollout, reversal, review date, and
   evidence. Link affected contracts, roadmap packages, and exceptions.
3. Add the record to the decision log in the same change. For founder acceptance,
   set `Status` to `Founder accepted`, record an `Operating domain` from the
   ownership register and `Approval evidence` as `founder=@lixuanguang`. The
   decision date must fall within the registered founder's effective assignment.
4. Institutional `Accepted` status still requires the risk-class reviewers and
   commit-bound approval evidence. Founder acceptance does not assert independent
   review. A later hire reviews material decisions in their handover scope rather
   than retroactively invalidating every founder decision.
5. Review on the recorded date or earlier when assumptions, measurements,
   incidents, target environments, regulations, dependencies, or supported use
   change materially.
6. Set obsolete records to `Superseded`, `Deprecated`, or `Rejected`; retain them
   permanently and link the successor or rationale. Never rewrite decision
   history to hide an earlier choice.

Allowed statuses are `Proposed`, `Founder accepted`, `Accepted`, `Rejected`, `Deprecated`, and
`Superseded`. Accepted ADRs require approval evidence in the exact form
`commit=<40-or-64-hex>; approval=<HTTPS evidence URL>` so a free-form assertion
cannot change lifecycle status. The URL remains externally verified evidence; its
presence is not proof that the forge approved the commit. The A02 checker rejects
malformed records, gaps in numbering, unlogged ADRs, and broken repository-local
documentation links.

## Deprecation policy

Deprecation is an explicit compatibility change, not a comment or silent removal.
The owning change must record:

- the affected API, schema, artifact, data, configuration, state, or operational
  procedure and its accountable owner;
- the replacement and migration path, affected consumers selected from the
  dependency graph, compatibility tests, and target completion evidence;
- the announcement/adoption date, supported compatibility window, removal
  condition and date, rollback point, monitoring, and retained audit evidence;
- schema or state expansion, migration/backfill, dual-read/write where required,
  and contraction only after old consumers and rollback obligations have ended.

Removal must fail closed when a consumer remains. Unknown fields and versions are
handled according to their canonical contract; they are never silently coerced.
Security fixes may shorten a window only through the applicable change class,
compensating controls, migration evidence, and time-bounded exception process.
Indefinite compatibility shims and ownerless removal dates are prohibited.

## Architecture exception process

An exception is permitted only when a named rule cannot currently be met and the
exception does not weaken the blueprint. The requesting change records an
`EXC-YYYY-NNNN` entry in the relevant ADR and decision log with:

- the exact rule, affected target/release/scope, rationale, considered
  alternatives, and why ordinary compliance is unavailable;
- owner, required approvers, compensating controls, test/monitoring evidence,
  expiry, closure condition, and remediation or reversal package;
- affected dependencies, security/data/model/risk impact, and explicit prohibited
  uses while the exception remains open.

Exceptions default to rejected when scope, owner, evidence, or expiry is missing.
They are reviewed on every affected change and close by remediation, reversal, or
expiry. Expiry blocks further use; it does not renew automatically. Architecture
exceptions do not replace quality-gate waivers and cannot waive point-in-time
causality, immutable release identity, independent hard risk, kill capability, or
any legal, entitlement, credential, market-access, capital, or activation control.

There are no active architecture exceptions for A02.

## Migration, rollback, and evidence

Adopting this process changes documentation governance and CI checks only. It
does not migrate schemas, data, state, runtimes, or credentials. Rollback requires
a reviewed revert or superseding ADR and must preserve the decision history and
findings. Institutional evidence remains separately recorded; its absence does
not prevent A02 engineering completion under the current operating policy.
