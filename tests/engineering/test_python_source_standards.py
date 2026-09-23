"""Behavioral contract tests for the Python source standards scanner."""

from __future__ import annotations

# standard library imports
import ast
from textwrap import dedent

# third party library imports
import pytest
from pydantic import ValidationError

# project library imports
from alpha_research_governance.engineering_standards.python_source import (
    PythonFinding,
    PythonSourceChecker,
    _ImportRecord,
    _Scope,
)


class TestPythonSourceRecords:
    """Exercise strict value records and mutable lexical-scope state."""

    def test_finding_is_strict_frozen_and_has_stable_key(self) -> None:
        """Reject coercion and mutation while preserving finding identity."""
        finding = PythonFinding(
            path="src/a.py",
            symbol="parse",
            rule="PYD001",
            detail="summary",
            line=3,
        )

        assert finding.key == ("src/a.py", "parse", "PYD001", "summary")
        invalid_line: object = {
            "path": "src/a.py",
            "symbol": "parse",
            "rule": "PYD001",
            "detail": "summary",
            "line": "3",
        }
        with pytest.raises(ValidationError, match="valid integer"):
            PythonFinding.model_validate(invalid_line)
        unknown_field: object = {
            "path": "src/a.py",
            "symbol": "parse",
            "rule": "PYD001",
            "detail": "summary",
            "line": 3,
            "unexpected": "synthetic",
        }
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PythonFinding.model_validate(unknown_field)
        with pytest.raises(ValidationError, match="Instance is frozen"):
            setattr(finding, "line", 4)

    def test_scope_preserves_parent_identity_and_independent_defaults(self) -> None:
        """Keep live parent lookup while isolating each scope's mutable bindings."""
        parent = _Scope(symbol="<module>", parent=None)
        first = _Scope(symbol="first", parent=parent)
        second = _Scope(symbol="second", parent=parent)

        assert first.parent is parent
        first.bind_alias("Alias", "typing-any")
        assert first.aliases == {"Alias": "typing-any"}
        assert second.aliases == {}
        assert second.bindings == set()
        parent.bind_alias("Shared", "typing-module")
        assert first.resolve("Shared") == "typing-module"
        first.bind_name("Shared")
        assert first.resolve("Shared") is None
        assert parent.resolve("Shared") == "typing-module"

    def test_import_record_preserves_ast_identity(self) -> None:
        """Keep the arbitrary AST node object unchanged at the import boundary."""
        statement = ast.parse("import os\n").body[0]
        assert isinstance(statement, ast.Import)

        record = _ImportRecord(node=statement, category="standard", line=1)

        assert record.node is statement


class TestPythonSourceChecker:
    """Exercise the source scanner's rules and finding identity contract."""

    @staticmethod
    def _scan(source: str, path: str = "module.py") -> tuple[PythonFinding, ...]:
        """Scan an indented source snippet under a repository-relative path."""
        return PythonSourceChecker().scan(path, dedent(source))

    @staticmethod
    def _rule(findings: tuple[PythonFinding, ...], rule: str) -> tuple[PythonFinding, ...]:
        """Select findings for one scanner rule."""
        return tuple(finding for finding in findings if finding.rule == rule)

    def test_type_comments_and_pep695_aliases_cannot_hide_any(self) -> None:
        """Inspect actual type contexts while preserving ordinary comment prose."""
        sources = (
            "from typing import Any\nitems = []  # type: list[Any]\n",
            "import typing as t\nitems = []  # type: list[t.Any]\n",
            "import typing as t\ndef f(value):  # type: (t.Any) -> t.Any\n    return value\n",
            "import typing as t\ntype Dynamic = t.Any\n",
        )
        for source in sources:
            findings = self._rule(self._scan(source), "PYT001")
            assert any("import" not in finding.detail for finding in findings), source
        assert not self._rule(self._scan('"""Module."""\n# Any is banned.\n'), "PYT001")

    def test_summary_only_public_functions_do_not_need_structured_sections(self) -> None:
        """Keep structured Google sections optional when the summary is meaningful."""
        source = (
            '"""Module."""\n'
            "def f(first: int, second: str) -> int:\n"
            '    """Process inputs."""\n'
            "    return first\n"
        )
        assert self._rule(self._scan(source), "PYD002") == ()

    def test_new_parameter_cannot_reuse_a_present_args_allowance(self) -> None:
        """Assign a separate obligation to each undocumented present Args entry."""
        source = (
            '"""Module."""\n'
            "def f(first: int) -> None:\n"
            '    """Process inputs.\n\n'
            "    Args:\n"
            "        first: First input.\n"
            '    """\n'
        )
        old = {item.key for item in self._rule(self._scan(source), "PYD002")}
        changed = source.replace("first: int", "first: int, second: str")
        new = {item.key for item in self._rule(self._scan(changed), "PYD002")}
        assert new - old
        assert any("second" in key[-1] for key in new - old)

    def test_stdlib_submodules_and_multiple_future_imports_remain_standard(self) -> None:
        """Classify imports by their package root and accept contiguous future statements."""
        findings = self._scan(
            '''
            """Module."""

            from __future__ import annotations
            from __future__ import generator_stop

            # standard library imports
            from collections.abc import Iterable
            from importlib.metadata import version
            '''
        )
        assert not self._rule(findings, "PYI001")

    def test_future_import_cannot_follow_an_assignment(self) -> None:
        """Reject misplaced future statements even though AST parsing accepts them."""
        source = '"""Module."""\nvalue = 1\n\nfrom __future__ import annotations\n'
        assert any(item.detail == "future-position" for item in self._scan(source))

    def test_annotation_metadata_is_text_but_annotated_types_are_checked(self) -> None:
        """Distinguish forward types from Literal values and Annotated metadata."""
        for imports, literal, annotated, dynamic in (
            ("import typing as t", "t.Literal", "t.Annotated", "t.Any"),
            ("from typing import Literal as L, Annotated as A, Any as D", "L", "A", "D"),
        ):
            source = f"{imports}\nx: {literal}['{dynamic}']\ny: {annotated}[str, '{dynamic}']\n"
            findings = self._rule(self._scan(source), "PYT001")
            assert all(item.detail.startswith("import:") for item in findings)
            changed = source + f"z: {annotated}['{dynamic}', 'description']\n"
            assert any(item.detail == "variable:z" for item in self._scan(changed))

    def test_generic_bounds_and_annotated_alias_uses_are_checked(self) -> None:
        """Track bound types and reuse of an explicitly annotated dynamic alias."""
        source = (
            "import typing as t\n"
            "Dynamic: t.TypeAlias = t.Any\n"
            "value: Dynamic\n"
            "def convert[T: t.Any](value: T) -> T:\n    return value\n"
            "class Model[T: t.Any]:\n    pass\n"
            "type Items[T: t.Any] = list[T]\n"
        )
        findings = self._rule(self._scan(source), "PYT001")
        assert any(item.detail == "variable:value" for item in findings)
        assert sum(item.detail == "type-bound:T" for item in findings) == 3

    def test_missing_summary_remains_a_summary_finding(self) -> None:
        """Keep missing summaries distinct from optional structured sections."""
        source = '"""Module."""\ndef f(first: int) -> None:\n    pass\n'
        findings = self._scan(source)
        assert any(item.rule == "PYD001" and item.symbol == "f" for item in findings)
        assert self._rule(findings, "PYD002") == ()

    def test_overload_signatures_inherit_concrete_implementation_documentation(self) -> None:
        """Skip repeated overload summaries while requiring the implementation summary."""
        source = '''
        """Overload documentation fixture."""

        # standard library imports
        import typing as typing_alias
        from typing import overload as overloaded

        @overloaded
        def convert(value: int) -> int:
            ...

        @typing_alias.overload
        def convert(value: str) -> str:
            ...

        def convert(value: int | str) -> int | str:
            """Convert one supported value.

            Args:
                value: Integer or string value to convert.

            Returns:
                The unchanged value with its concrete overload type.

            """
            return value
        '''
        assert self._scan(source) == ()

        implementation_without_summary = source.replace(
            "        def convert(value: int | str) -> int | str:\n"
            '            """Convert one supported value.\n\n'
            "            Args:\n"
            "                value: Integer or string value to convert.\n\n"
            "            Returns:\n"
            "                The unchanged value with its concrete overload type.\n\n"
            '            """\n',
            "        def convert(value: int | str) -> int | str:\n",
        )
        findings = self._scan(implementation_without_summary)
        assert any(finding.rule == "PYD001" and finding.symbol == "convert" for finding in findings)

    def test_google_sections_require_indented_content(self) -> None:
        """Reject flush-left prose pretending to document an argument or result."""
        source = '''
        """Module."""
        def convert(value: int) -> int:
            """Convert a value.

            Args:
            value: Input value.

            Returns:
            Converted value.
            """
            return value
        '''
        details = {item.detail for item in self._rule(self._scan(source), "PYD002")}
        assert {"Args", "parameter:value", "Returns"} <= details

    def test_test_name_only_exempts_functions_in_test_sources(self) -> None:
        """Keep test-path summary exemptions separate from production summaries."""
        source = '''
        """Module."""
        def test_connection(endpoint: str) -> bool:
            """Check connectivity.

            Returns:

            """
            return bool(endpoint)
        '''
        assert self._rule(self._scan(source, "tests/test_connection.py"), "PYD002") == ()
        assert self._rule(self._scan(source, "src/connection.py"), "PYD002")

    def test_compliant_typed_class_with_google_docs_has_no_findings(self) -> None:
        """Accept a documented class and method with complete contracts."""
        findings = self._scan(
            '''
            """Pricing service module."""

            class PricingService:
                """Calculate deterministic prices for requested quantities."""

                def quote(self, symbol: str, quantity: int) -> float:
                    """Calculate a quote for one instrument.

                    Args:
                        symbol: Instrument identifier.
                        quantity: Requested quantity.

                    Returns:
                        Deterministic quote amount.

                    Raises:
                        ValueError: If quantity is not positive.
                    """
                    if quantity <= 0:
                        raise ValueError("quantity must be positive")
                    return float(len(symbol) * quantity)
            '''
        )

        assert findings == ()

    def test_import_headings_accept_ordered_categories_and_future_group(self) -> None:
        """Accept correctly headed standard, third-party, and project imports."""
        findings = self._scan(
            '''
            """Import contract fixture."""

            from __future__ import annotations

            # standard library imports
            import os

            # third party library imports
            import pytest

            # project library imports
            from alpha_research_governance.engineering_standards import main
            '''
        )

        assert self._rule(findings, "PYI001") == ()

    def test_import_headings_reject_missing_heading_and_group_spacing(self) -> None:
        """Reject missing category headings and missing blank separation."""
        missing_heading = self._scan(
            '''
            """Missing heading fixture."""

            import os
            '''
        )
        wrong_heading = self._scan(
            '''
            """Wrong heading fixture."""

            # third party library imports
            import os
            '''
        )
        missing_blank = self._scan(
            '''
            """Missing blank fixture."""

            # standard library imports
            import os
            # third party library imports
            import pytest
            '''
        )

        missing_details = tuple(
            finding.detail.lower() for finding in self._rule(missing_heading, "PYI001")
        )
        wrong_details = tuple(
            finding.detail.lower() for finding in self._rule(wrong_heading, "PYI001")
        )
        spacing_details = tuple(
            finding.detail.lower() for finding in self._rule(missing_blank, "PYI001")
        )
        assert missing_details and any("standard" in detail for detail in missing_details)
        assert wrong_details and any("standard" in detail for detail in wrong_details)
        assert spacing_details and any(
            "blank" in detail or "separat" in detail for detail in spacing_details
        )

    def test_import_headings_reject_wrong_category_order_and_future_position(self) -> None:
        """Reject category order drift and a future import after ordinary imports."""
        findings = self._scan(
            '''
            """Import order fixture."""

            # third party library imports
            import pytest

            # standard library imports
            import os

            # project library imports
            from alpha_research_governance.engineering_standards import main

            from __future__ import annotations
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYI001"))
        assert details
        assert any("order" in detail or "standard" in detail for detail in details)
        assert any("future" in detail for detail in details)

    def test_import_headings_cover_type_checking_and_relative_project_blocks(self) -> None:
        """Apply project headings to guarded and relative imports."""
        findings = self._scan(
            '''
            """Guarded import fixture."""

            from __future__ import annotations

            # standard library imports
            from typing import TYPE_CHECKING

            # third party library imports
            import pytest

            # project library imports
            from alpha_research_governance.engineering_standards import main

            if TYPE_CHECKING:
                # project library imports
                from .models import ToolStandard
            '''
        )

        assert self._rule(findings, "PYI001") == ()

    def test_type_checking_relative_block_requires_its_heading(self) -> None:
        """Reject an unheaded relative import inside a type-checking block."""
        findings = self._scan(
            '''
            """Guarded heading fixture."""

            from __future__ import annotations

            # standard library imports
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from .models import ToolStandard
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYI001"))
        assert details and any("project" in detail or "heading" in detail for detail in details)

    def test_explicit_any_alias_and_qualified_references_are_reported(self) -> None:
        """Report imported aliases and qualified typing Any references."""
        findings = self._scan(
            '''
            """Any reference fixture."""

            from __future__ import annotations

            # standard library imports
            import typing
            from typing import Any as Dynamic

            # third party library imports
            import typing_extensions

            def use_alias(value: Dynamic) -> Dynamic:
                """Pass through a dynamically typed value."""
                return value

            def use_qualified(value: typing.Any) -> typing_extensions.Any:
                """Pass through qualified dynamic values."""
                return value
            '''
        )

        any_findings = self._rule(findings, "PYT001")
        details = tuple(finding.detail.lower() for finding in any_findings)
        alias_findings = tuple(finding for finding in any_findings if finding.symbol == "use_alias")
        qualified_findings = tuple(
            finding for finding in any_findings if finding.symbol == "use_qualified"
        )
        assert any_findings
        assert len(alias_findings) >= 2
        assert len(qualified_findings) >= 2
        assert any("parameter" in finding.detail.lower() for finding in alias_findings)
        assert any("returns" in finding.detail.lower() for finding in qualified_findings)
        assert any("dynamic" in detail or "alias" in detail for detail in details)

    def test_explicit_any_assignments_aliases_and_quoted_annotations_are_reported(self) -> None:
        """Report Any in assignments, type aliases, and quoted annotations."""
        findings = self._scan(
            '''
            """Assignment and quoted annotation fixture."""

            from __future__ import annotations

            # standard library imports
            from typing import Any, TypeAlias

            Payload: TypeAlias = dict[str, Any]
            Alias = Any

            class Envelope:
                """Hold one payload."""

                payload: "Any"
                mapping: dict[str, Any]
            '''
        )

        any_findings = self._rule(findings, "PYT001")
        details = tuple(finding.detail.lower() for finding in any_findings)
        assert len(any_findings) >= 4
        assert any("payload" in detail or "annotation" in detail for detail in details)
        assert any("alias" in detail or "assignment" in detail for detail in details)

    def test_nested_any_findings_keep_qualified_scope_identity(self) -> None:
        """Keep outer and nested function Any findings in their own scopes."""
        findings = self._scan(
            '''
            """Nested scope fixture."""

            from __future__ import annotations

            # standard library imports
            from typing import Any

            def outer(value: Any) -> int:
                """Return a value after checking a nested callback."""

                def inner(item: Any) -> int:
                    """Return the nested item marker."""
                    return 1

                return inner(value)
            '''
        )

        symbols = {finding.symbol for finding in self._rule(findings, "PYT001")}
        assert "outer" in symbols
        assert "outer.inner" in symbols
        assert "inner" not in symbols

    def test_literal_any_and_ordinary_text_are_not_false_positives(self) -> None:
        """Ignore Literal string values, docstrings, and ordinary source text."""
        findings = self._scan(
            '''
            """The word Any in this module documentation is ordinary text."""

            from __future__ import annotations

            # standard library imports
            from typing import Literal

            class Label:
                """Document the literal value Any."""

                value: Literal["Any"]
                text = "Any"
            '''
        )

        assert self._rule(findings, "PYT001") == ()

    def test_each_additional_any_occurrence_has_a_distinct_key(self) -> None:
        """Retain separate findings when one symbol gains another Any use."""
        one_occurrence = self._scan(
            '''
            """One Any occurrence."""

            from __future__ import annotations

            # standard library imports
            from typing import Any

            def transform(value: Any) -> int:
                """Transform one value."""
                return 1
            '''
        )
        two_occurrences = self._scan(
            '''
            """Two Any occurrences."""

            from __future__ import annotations

            # standard library imports
            from typing import Any

            def transform(value: Any) -> Any:
                """Transform one value."""
                return value
            '''
        )

        first = tuple(
            finding
            for finding in self._rule(one_occurrence, "PYT001")
            if finding.symbol == "transform"
        )
        second = tuple(
            finding
            for finding in self._rule(two_occurrences, "PYT001")
            if finding.symbol == "transform"
        )
        assert len(second) == len(first) + 1
        assert len({finding.key for finding in second}) == len(second)
        assert len({finding.detail for finding in second}) == len(second)

    def test_missing_class_and_private_docstrings_are_named(self) -> None:
        """Report missing class and private method summaries by qualified name."""
        findings = self._scan(
            '''
            """Class documentation fixture."""

            class MissingClass:
                def public_method(self) -> None:
                    """Run a documented public operation."""
                    return None

                def _private_method(self) -> None:
                    return None
            '''
        )

        doc_findings = self._rule(findings, "PYD001")
        symbols = {finding.symbol for finding in doc_findings}
        assert "MissingClass" in symbols
        assert "MissingClass._private_method" in symbols
        assert all(finding.detail for finding in doc_findings)

    def test_missing_module_docstring_is_reported(self) -> None:
        """Report an absent module summary while retaining documented definitions."""
        findings = self._scan(
            '''
            class Documented:
                """Document the class."""
            '''
        )

        doc_findings = self._rule(findings, "PYD001")
        assert any(finding.symbol == "<module>" for finding in doc_findings)
        assert any("summary" in finding.detail.lower() for finding in doc_findings)

    def test_public_api_summary_does_not_require_google_sections(self) -> None:
        """Keep public structured sections available for meaningful contracts."""
        findings = self._scan(
            '''
            """Public API fixture."""

            def calculate(value: int, enabled: bool = False) -> int:
                """Calculate a value."""
                return value if enabled else value + 1
            '''
        )

        assert self._rule(findings, "PYD002") == ()

    def test_structured_sections_are_optional_for_return_yield_and_raise_facts(self) -> None:
        """Avoid inferring documentation obligations from syntax alone."""
        findings = self._scan(
            '''
            """Derived facts fixture."""

            def values(items: list[int]) -> list[int]:
                """Yield items or reject an empty input."""
                if not items:
                    raise ValueError("items must not be empty")
                for item in items:
                    yield item
            '''
        )

        assert self._rule(findings, "PYD002") == ()

    def test_empty_args_returns_and_raises_sections_are_rejected(self) -> None:
        """Reject empty Google sections on a validating public API."""
        findings = self._scan(
            '''
            """Empty section fixture."""

            def validate(value: int) -> int:
                """Validate one value.

                Args:

                Returns:

                Raises:

                """
                if value < 0:
                    raise ValueError("value must be non-negative")
                return value
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYD002"))
        assert len(details) >= 3
        assert any("args" in detail for detail in details)
        assert any("returns" in detail for detail in details)
        assert any("raises" in detail for detail in details)

    def test_present_empty_yields_section_is_rejected(self) -> None:
        """Reject an explicitly empty Yields section without requiring it syntactically."""
        findings = self._scan(
            '''
            """Generator documentation fixture."""

            def values(items: list[int]) -> list[int]:
                """Yield each item.

                Args:
                    items: Values to yield.

                Yields:

                """
                for item in items:
                    yield item
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYD002"))
        assert details and any("yields" in detail for detail in details)

    def test_present_args_section_rejects_unknown_parameter_names(self) -> None:
        """Reject an Args entry that is absent from the function signature."""
        findings = self._scan(
            '''
            """Argument names fixture."""

            def build(name: str) -> int:
                """Build one name.

                Args:
                    name: Name to build.
                    count: Unknown count parameter.

                Returns:
                    Built count.

                """
                return len(name)
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYD002"))
        assert details and any("count" in detail for detail in details)

    def test_public_args_section_must_describe_every_argument(self) -> None:
        """Reject a public Args section that omits one parameter."""
        findings = self._scan(
            '''
            """Argument completeness fixture."""

            def build(name: str, count: int) -> int:
                """Build a count for one name.

                Args:
                    name: Name to build.

                Returns:
                    Built count.

                """
                return len(name) + count
            '''
        )

        details = tuple(finding.detail.lower() for finding in self._rule(findings, "PYD002"))
        assert details and any("count" in detail for detail in details)

    def test_nested_yield_and_raise_do_not_change_parent_contract(self) -> None:
        """Keep nested generator and exception behavior out of parent docs."""
        findings = self._scan(
            '''
            """Nested documentation fixture."""

            def parent(value: int) -> int:
                """Return the parent value.

                Args:
                    value: Parent value.

                Returns:
                    The unchanged parent value.

                """
                def child() -> list[int]:
                    """Yield child values.

                    Yields:
                        One child marker.

                    """
                    yield 1

                def failing() -> None:
                    """Raise a child error.

                    Raises:
                        ValueError: Always raised by this child.

                    """
                    raise ValueError("child failure")

                return value
            '''
        )

        parent_details = tuple(
            finding.detail.lower()
            for finding in self._rule(findings, "PYD002")
            if finding.symbol == "parent"
        )
        assert not any("yields" in detail or "raises" in detail for detail in parent_details)

    def test_typed_documented_ordinary_and_test_functions_are_accepted(self) -> None:
        """Accept documented sync, async, and ordinary test functions without registration."""
        findings = self._scan(
            '''
            """Ordinary function fixture."""

            def process_records(records: list[str], prefix: str) -> list[str]:
                """Process records with a prefix.

                Args:
                    records: Records to process.
                    prefix: Prefix to apply.

                Returns:
                    Processed records.

                """
                normalized = [record.strip() for record in records]
                return [prefix + record for record in normalized if record]

            async def load_records(source: str) -> list[str]:
                """Load records from one source.

                Args:
                    source: Source identifier to load.

                Returns:
                    Loaded records from the source.

                """
                return [source]

            def test_records() -> None:
                """Exercise ordinary record processing."""
                assert process_records(["alpha"], "-") == ["-alpha"]
            ''',
            path="tests/test_records.py",
        )

        assert findings == ()

    def test_functions_retain_typing_import_and_docstring_rejections(self) -> None:
        """Keep retained source diagnostics active for module-level functions."""
        findings = self._scan(
            '''
            """Function diagnostics fixture."""

            # standard library imports
            from typing import Any

            def invalid(value: Any) -> int:
                import os
                return value
            '''
        )

        assert any(finding.rule == "PYT001" and finding.symbol == "invalid" for finding in findings)
        assert any(finding.rule == "PYI001" and finding.symbol == "invalid" for finding in findings)
        assert any(finding.rule == "PYD001" and finding.symbol == "invalid" for finding in findings)
        assert self._rule(findings, "PYD002") == ()

    def test_private_and_test_functions_need_only_summary_docstrings(self) -> None:
        """Accept summary-only docs for private and test functions."""
        findings = self._scan(
            '''
            """Summary-only documentation fixture."""

            def _normalize(value: int) -> int:
                """Normalize one value."""
                return value

            def test_contract() -> None:
                """Exercise the contract."""
                assert _normalize(1) == 1
            '''
        )

        assert self._rule(findings, "PYD001") == ()
        assert self._rule(findings, "PYD002") == ()

    def test_qualified_names_and_keys_remain_stable_under_blank_lines(self) -> None:
        """Keep qualified symbols and semantic keys independent of line spacing."""
        compact = dedent(
            '''
            """Qualified name fixture."""

            class Outer:
                """Contain nested definitions."""
                class Inner:
                    """Contain the missing method documentation."""
                    def method(self, value: int) -> int:
                        return value
            '''
        )
        spaced = compact.replace("    class Inner:", "\n    class Inner:")
        compact_findings = self._rule(PythonSourceChecker().scan("qualified.py", compact), "PYD001")
        spaced_findings = self._rule(PythonSourceChecker().scan("qualified.py", spaced), "PYD001")

        compact_by_key = {finding.key: finding for finding in compact_findings}
        spaced_by_key = {finding.key: finding for finding in spaced_findings}
        assert any(finding.symbol == "Outer.Inner.method" for finding in compact_findings)
        assert set(compact_by_key) == set(spaced_by_key)
        assert any(compact_by_key[key].line != spaced_by_key[key].line for key in compact_by_key)

    def test_repeated_scans_are_deterministic_and_do_not_leak_state(self) -> None:
        """Return identical findings after scanning another path with one checker."""
        checker = PythonSourceChecker()
        source = dedent(
            '''
            """Repeat scan fixture."""

            def missing_docs(value: int) -> int:
                return value
            '''
        )
        first = checker.scan("first.py", source)
        second = checker.scan(
            "second.py",
            dedent(
                '''
                """Second repeat fixture."""

                class Documented:
                    """Documented class."""
                '''
            ),
        )
        third = checker.scan("first.py", source)

        assert first == third
        assert first and all(finding.path == "first.py" for finding in first)
        assert all(finding.path == "second.py" for finding in second)

    def test_scan_releases_invocation_state_after_success_and_failure(self) -> None:
        """Release source context after both ordinary and malformed scans."""
        checker = PythonSourceChecker()
        checker.scan("valid.py", '"""Valid module."""\n')
        assert checker._path == ""
        assert checker._lines == ()
        assert checker._findings == []

        checker.scan("broken.py", "def broken(:\n")
        assert checker._path == ""
        assert checker._lines == ()
        assert checker._findings == []

    def test_malformed_syntax_returns_a_syntax_finding(self) -> None:
        """Return a PYS001 finding instead of raising for malformed source."""
        findings = self._scan(
            '''
            """Malformed source fixture."""

            def broken(:
                pass
            ''',
            path="broken.py",
        )

        syntax_findings = self._rule(findings, "PYS001")
        assert syntax_findings
        assert any(
            "syntax" in finding.detail.lower() or "token" in finding.detail.lower()
            for finding in syntax_findings
        )
        assert all(finding.path == "broken.py" for finding in syntax_findings)

    def test_unterminated_multiline_string_preserves_token_error_line(self) -> None:
        """Report an unterminated string at its opening line, not the file end."""
        findings = self._scan(
            '"""Module."""\nvalue = """unterminated\nsecond line\n',
            path="unterminated.py",
        )

        syntax_findings = self._rule(findings, "PYS001")
        assert syntax_findings
        assert syntax_findings[0].line == 2
