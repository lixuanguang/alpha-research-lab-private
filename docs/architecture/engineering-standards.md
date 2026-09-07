# Python engineering standards

The repository keeps a small local clarity checker beside the ordinary tools.
The checker covers source rules that Ruff and mypy do not fully express, while
Ruff owns formatting and linting and strict mypy owns inferred typing. It does
not load a roadmap, ownership table, change-risk policy, evidence bundle, or
exception register.

Run the direct checker with:

```sh
uv run --frozen alpha-governance-engineering-standards
```

The command scans `src`, `tests`, `tools/governance/src`, and
`tools/typing/stubs`. It exits zero only when the source and configuration
checks pass. A missing root, unreadable source, malformed configuration, or
finding returns a nonzero status.

## Protected clarity checks

The source checker preserves the following behavior:

- Every import category has its exact heading and blank-line separation. Future
  imports remain immediately after the module docstring. Standard library,
  third-party, and project imports are ordered consistently. Relative imports
  and imports inside `TYPE_CHECKING` blocks follow the same project rules.
- Explicit `Any` is rejected in annotations, aliases, qualified references,
  assignments, type comments, quoted annotations, generic bounds, and nested
  scopes. Text, docstrings, and `Literal` values remain ordinary values.
- Every module, class, and named function has a meaningful Google-style summary.
  Public functions describe their parameters and applicable `Returns:`,
  `Yields:`, and `Raises:` sections. Private helpers and test functions retain
  summary-only documentation where no public contract is exposed.
- A class remains appropriate when it identifies a concept, owns state,
  groups related behavior, or establishes an invariant. Module-level functions
  remain valid when they are the clearest representation of a stateless or
  low-level operation.

The checker reports findings directly. It has no source-rule waiver or function
registration mechanism. Semantic review still decides whether documentation
actually explains behavior; syntax checks cannot make that judgment.

## Tool configuration

The configuration boundary keeps these settings global and visible:

- strict mypy runs with `disallow_any_explicit`, `disallow_any_unimported`,
  `disallow_any_decorated`, and `disallow_any_expr` enabled;
- the Pydantic mypy plugin remains enabled with typed constructors, forbidden
  extra constructor fields, and dynamic-alias warnings;
- mypy checks `src`, `tests`, `tools/governance/src`, and
  `tools/typing/stubs` through the configured source and stub paths;
- Ruff retains import sorting (`I`), Google documentation (`D`), and dynamic
  typing (`ANN401`) checks with the Google pydocstyle convention; and
- pytest treats warnings as errors.

The checker rejects global excludes, per-file ignores, module overrides, and
other configuration changes that narrow these requirements. The command does
not replace the configured Ruff, mypy, pytest, Bandit, or native stub checks.

## Suppression metadata

Supported source suppressions remain line-scoped and carry local accountability
metadata in this exact order:

```text
[owner=<identifier>; rationale=<concrete reason>; expires=YYYY-MM-DD]
```

The owner is an explicit source annotation; it is not resolved through an
organizational role registry. The rationale must meet the configured minimum
length, and expiry must be no more than 180 days from validation. Missing,
malformed, expired, or overlong metadata fails the checker.

## Typing and native stubs

`tools/typing/` contains the narrow native declarations consumed by the domain
adapters. `tools/typing/README.md` documents their boundary and the installed
stub checks. The stronger typing command runs mypy directly over the complete
source, test, governance, and stub scope and reports every diagnostic without a
baseline. Native stub conformance remains a separate focused check for the
installed dependencies.

## Regression coverage

The retained behavior is covered by the focused engineering tests:

- `tests/engineering/test_python_source_standards.py` covers import headings,
  relative and `TYPE_CHECKING` imports, aliases, qualified and quoted `Any`,
  generic bounds, and public/private/test documentation behavior;
- `tests/engineering/test_python_standards.py` covers source discovery,
  diagnostics, ordinary functions, malformed input, and untracked `.py`/`.pyi`
  files;
- `tests/engineering/test_engineering_standards.py` covers direct command
  behavior, strict configuration wiring, and bounded suppression metadata; and
- `tests/engineering/test_python_typing.py` covers the complete mypy argument
  scope, failure propagation, and native-stub participation.

These tests are focused on the protected engineering behavior. Domain tests and
native conformance tests remain with their owning adapters and units.
