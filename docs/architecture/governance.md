# Architecture decisions

Use a short architecture decision record when a choice is expensive to reverse,
such as a dependency, storage format, time semantic, process boundary, or
deployment target. An ADR explains the context, alternatives, decision,
consequences, migration, and reversal. It is a durable technical note; it does
not create an approval, staffing, or package-completion requirement.

Keep the record in [`docs/architecture/decisions/`](decisions/README.md) and
link it from the change that implements the decision. A decision can be
replaced by a later record that explains the new constraint and migration path.
Routine implementation details do not need an ADR.

The architecture command checks repository-local Markdown links and fragments.
It does not parse ADR metadata, require a role catalog, or infer acceptance from
the presence of a field. Use the [development workflow](../governance/workflow.md)
for implementation, release, and founder activation decisions.
