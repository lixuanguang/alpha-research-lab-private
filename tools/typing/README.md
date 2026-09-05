# Python boundary typing

`make typecheck` checks runtime source, governance, tests and the local native
stubs. It then reconciles the stronger mypy probe with the exact
[remaining inventory](../../docs/architecture/python-typing-debt.json) and runs
stubtest against the installed native libraries. Pre-commit and the full CI lane
use the same command.

The Pydantic 2.13.5 plugin uses typed constructors, forbids extra constructor
keywords and rejects required dynamic aliases. Explicit and unfollowed-import
dynamic types are prohibited throughout the checked scope. Decorated signatures
are checked in both owned packages; the remaining test-framework signatures are
listed in the inventory. The fully checked expression scopes are listed in
`pyproject.toml`. These checks do not imply that all remaining expressions have
precise types.

## Native stubs

`stubs/` contains narrow declarations for the consumed QuantLib 1.43,
exchange-calendars 4.13.2 and pandas 3.0.5 surface. They describe the installed
implementations; they do not replace them at runtime or claim coverage of each
library's complete API. Unlisted members remain unavailable to owned typed code.
The date inputs cover the adapter's usage; pandas timestamps and its NaT
singleton are datetime subclasses. Existing adapter checks still validate raw
results, including deliberately malformed test doubles.

The root mypy path and stubtest configuration resolve these declarations.
Bazel includes them as data of the native adapters and repository build checks;
the source distribution includes `tools/typing`. The stubs are development
inputs and are not injected into the runtime wheel or dependency resolution.
No dependency pin or lockfile changes for this slice.

Stubtest uses `--ignore-missing-stub` because the declarations intentionally cover
only the consumed surface. It checks declared names and signatures without an
allowlist. The native conformance tests additionally check actual return types,
day-count constants, calendar timestamps, break sentinels and both XNYS/XHKG
schedules. Existing financial and calendar goldens verify the owned results.

## Retiring inferred debt

The inventory has a checksum pinned in `engineering_standards/python_typing.py`.
Each obligation identifies a source path, qualified symbol, diagnostic code and
message, multiplicity and a concrete retirement task. Definition and decorator
line shifts do not renew debt. New, moved, multiplied and resolved diagnostics
fail reconciliation; missing tasks and duplicate identities also fail.

Fix the named boundary, remove only the resolved obligations and update the
checksum in the same review. Never regenerate allowances from the current tree.
The probe itself never writes the inventory. Remaining tasks cover precise
serialization and fixture records, framework callbacks, reflected values,
validated collection narrowing, regex results and contextual callback inference.
These are unresolved migration tasks, not source-standard exceptions or a claim
that inferred dynamic typing has been eliminated. Complete them during the
owning module's later migration slices and before step 7 closes adoption.
