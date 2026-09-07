# Python boundary typing

`make typecheck` checks runtime source, governance, tests and the local native
stubs with strict mypy and then runs stubtest against the installed native
libraries. Pre-commit and the full CI lane use the same command.

The Pydantic 2.13.5 plugin uses typed constructors, forbids extra constructor
keywords and rejects required dynamic aliases. Explicit and unfollowed-import
dynamic types, dynamically typed decorated signatures and expressions containing
dynamic types are prohibited throughout the checked scope, including tests.
The four `disallow_any_*` flags are global in `pyproject.toml`; there are no
module allowances or migration inventories.

The historical `python -m alpha_research_governance.engineering_standards.python_typing`
entry point remains available and now fails directly on diagnostics. The root
command runs mypy once; it no longer invokes a second inventory probe.

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

## Boundary changes

Annotate sorting and substitution callbacks with their consumed argument and
result types. Receive dynamic library results as `object` and narrow them before
field access. Framework adapters must retain real command registration,
dispatch, error rendering and exit statuses. A type annotation must not make
malformed test inputs appear valid or replace the runtime rejection under test.

For a changed boundary, run the affected strict typing checks and the owning
tests, including malformed inputs and serialization or native goldens where
applicable. Changes to global enforcement require checking the complete static
scope. No baseline, test exclusion or blanket suppression may admit a new
diagnostic. Reviewed source-function exceptions remain separately governed by
the engineering-standards checker; they cannot waive typing errors.
