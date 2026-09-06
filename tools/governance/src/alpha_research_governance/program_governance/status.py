"""Render the human program status from the authoritative program record."""

from __future__ import annotations

# standard library imports
import posixpath
from pathlib import Path, PurePosixPath

# project library imports
from alpha_research_governance.program_governance.models import (
    PackageNode,
    PackageState,
    ProgramGovernance,
    ProgramGovernanceError,
)


def _markdown_cell(value: str) -> str:
    """Escape Markdown table delimiters and replace LF newline characters."""
    return value.replace("|", "\\|").replace("\n", " ")


def _relative_link(*, target: str, status_path: str) -> str:
    """Return a POSIX relative link from the status file directory to a target."""
    return posixpath.relpath(target, start=PurePosixPath(status_path).parent.as_posix())


class ProgramStatusRenderer:
    """Render and validate status documents for one immutable program record.

    Construction retains the validated program model and performs no file or network I/O.
    Rendering derives all values from the model for each call, so repeated calls are
    deterministic and do not retain findings or other per-render state. Validation reads the
    supplied status path and compares its decoded text with a fresh rendered document.

    Attributes:
        _program: Immutable program record supplying status, readiness, finding, and path data.
    """

    def __init__(self, program: ProgramGovernance) -> None:
        """Bind the immutable program record used for rendering and validation.

        Args:
            program: Validated program model whose stored order and derived queries define the
                status document. Construction performs no I/O and does not mutate the model.
        """
        self._program = program

    def render(self) -> str:
        r"""Render the deterministic Markdown status document.

        Returns:
            A new Markdown string containing the source link, package totals and statuses, the
            first ready package for each readiness track, package rows in stored state order,
            and the active handover queue in stored state order. Objective cells escape only
            ``|`` as ``\|`` and LF characters as spaces; relative links use POSIX path semantics
            from the status-file directory. The result ends with one LF.

        Raises:
            ProgramGovernanceError: If ``program.generated_status_path`` is ``None``.
            KeyError: If a package state names no package in ``program.packages``.
            IndexError: If a directly constructed package state has no evidence path for its
                contract.
        """
        status_path = self._require_status_path()
        next_implementation, next_institutional = self._next_ready_packages()
        pending_handover = self._pending_handover()
        lines = self._header_lines(
            status_path=status_path,
            next_implementation=next_implementation,
            next_institutional=next_institutional,
        )
        lines.extend(self._package_rows(status_path=status_path))
        lines.extend(self._handover_section(pending_handover))
        return "\n".join(lines)

    def validate(self, path: Path) -> None:
        """Validate a generated status file against a fresh rendering.

        Args:
            path: UTF-8 status-document path to read; the file is not created, rewritten, or
                otherwise modified.

        Returns:
            ``None`` after ``path`` has been decoded with universal-newline translation and its
            text matches the freshly rendered document exactly.

        Raises:
            ProgramGovernanceError: If the generated path is absent, the file cannot be read due
                to an ``OSError`` (with its cause preserved), or its decoded text differs from
                the rendered document.
            UnicodeDecodeError: If ``path`` is not valid UTF-8.
            KeyError: If rendering encounters a package state without a matching package.
            IndexError: If rendering encounters a directly constructed package state without an
                evidence path.
        """
        expected = self.render()
        try:
            observed = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ProgramGovernanceError(
                [f"cannot read generated program status: {error}"]
            ) from error
        if observed != expected:
            raise ProgramGovernanceError(
                [
                    "generated program status is stale; run `make program-status` and "
                    "commit the result"
                ]
            )

    def _require_status_path(self) -> str:
        """Return the configured generated status path or raise its existing model error."""
        if self._program.generated_status_path is None:
            raise ProgramGovernanceError(["program schema does not define a generated status path"])
        return self._program.generated_status_path

    def _next_ready_packages(self) -> tuple[PackageNode | None, PackageNode | None]:
        """Return the first implementation and institutional readiness candidates."""
        implementation_ready = self._program.ready_packages(institutional=False)
        institutional_ready = self._program.ready_packages(institutional=True)
        next_implementation = None if not implementation_ready else implementation_ready[0]
        next_institutional = None if not institutional_ready else institutional_ready[0]
        return next_implementation, next_institutional

    def _pending_handover(self) -> tuple[PackageState, ...]:
        """Return pending package states in their stored order."""
        return tuple(
            state for state in self._program.package_states if state.governance_status == "pending"
        )

    def _header_lines(
        self,
        *,
        status_path: str,
        next_implementation: PackageNode | None,
        next_institutional: PackageNode | None,
    ) -> list[str]:
        """Build the fixed heading and program-summary lines in document order."""
        program_source_link = _relative_link(
            target="docs/governance/program-governance.toml",
            status_path=status_path,
        )
        return [
            "# Program status",
            "",
            "<!-- Generated by alpha-governance-program --write-status. Do not edit by hand. -->",
            "",
            (
                f"Authoritative source: [program-governance.toml]({program_source_link}). "
                f"Snapshot date: `{self._program.as_of_date.isoformat()}`."
            ),
            "",
            (
                f"- Registered implementation records: {len(self._program.package_states)} of "
                f"{len(self._program.packages)} packages."
            ),
            f"- Program implementation: `{self._program.implementation_status}`.",
            f"- Program governance: `{self._program.governance_status}`.",
            f"- Institutional acceptance: `{self._program.package_status}`.",
            (
                "- Next implementation-ready package: none."
                if next_implementation is None
                else (
                    f"- Next implementation-ready package: `{next_implementation.package_id}` — "
                    f"{_markdown_cell(next_implementation.objective)}."
                )
            ),
            (
                "- Next institutionally ready package: none."
                if next_institutional is None
                else f"- Next institutionally ready package: `{next_institutional.package_id}`."
            ),
            "",
            "Implementation completion is independent of institutional acceptance. "
            "Finding IDs below",
            "are retained institutional or operational obligations unless they also appear in the",
            "technical-findings column. Legacy findings have one migration disposition in the",
            "program record; current behavior and operation controls live in the linked contract",
            "and its adjacent machine-readable policy.",
            "",
            (
                "| Package | Capability | Implementation | Governance | Institutional | "
                "Technical findings | Role handover | Operation prerequisites | Contract |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]

    def _package_rows(self, *, status_path: str) -> list[str]:
        """Build package table rows in the program's stored package-state order."""
        packages_by_id = {package.package_id: package for package in self._program.packages}
        return [
            self._package_row(state, packages_by_id=packages_by_id, status_path=status_path)
            for state in self._program.package_states
        ]

    def _package_row(
        self,
        state: PackageState,
        *,
        packages_by_id: dict[str, PackageNode],
        status_path: str,
    ) -> str:
        """Render one package row while preserving state and finding order."""
        package = packages_by_id[state.package_id]
        contract_link = _relative_link(target=state.contract_path, status_path=status_path)
        technical_findings = ", ".join(f"`{item}`" for item in state.technical_finding_ids)
        role_findings = ", ".join(
            f"`{item}`"
            for item in state.open_finding_ids
            if self._program.finding_disposition_for(item) == "role_handover"
        )
        operation_findings = ", ".join(
            f"`{item}`"
            for item in state.open_finding_ids
            if self._program.finding_disposition_for(item) == "operation_prerequisite"
        )
        return (
            "| "
            + " | ".join(
                (
                    f"`{state.package_id}`",
                    _markdown_cell(package.objective),
                    f"`{state.implementation_status}`",
                    f"`{state.governance_status}`",
                    f"`{state.status}`",
                    technical_findings or "—",
                    role_findings or "—",
                    operation_findings or "—",
                    f"[contract]({contract_link})",
                )
            )
            + " |"
        )

    def _handover_section(self, pending_handover: tuple[PackageState, ...]) -> list[str]:
        """Build the active handover heading, queue, and command footer."""
        return [
            "",
            "## Active handover queue",
            "",
            (
                "No scoped handover is active. A joined, assigned reviewer activates only "
                "their domain."
                if not pending_handover
                else "\n".join(
                    f"- `{state.package_id}`: {', '.join(state.assigned_reviewers)}"
                    for state in pending_handover
                )
            ),
            "",
            "For the full graph, KPI definitions and machine-readable filters, run",
            "`alpha-governance-program --json`.",
            "",
        ]


def render_status_markdown(program: ProgramGovernance) -> str:
    r"""Render status through the supported compatibility function.

    Args:
        program: Immutable program record whose package order, derived statuses, readiness
            queries, finding dispositions, snapshot date, generated-status path, objectives,
            reviewer assignments, and contract paths supply the rendered values.

    Returns:
        A new Markdown string with deterministic status content. The wrapper performs no file or
        network I/O and delegates all rendering to ``ProgramStatusRenderer.render``.

    Raises:
        ProgramGovernanceError: If ``program.generated_status_path`` is ``None``.
        KeyError: If a package state names no package in ``program.packages``.
        IndexError: If a directly constructed package state has no evidence path for its contract.
    """
    return ProgramStatusRenderer(program).render()


def validate_status_document(path: Path, program: ProgramGovernance) -> None:
    """Validate a generated status document through the compatibility function.

    Args:
        path: UTF-8 status-document path to read; the file is not created, rewritten, or
            otherwise modified.
        program: Immutable program record bound to ``ProgramStatusRenderer`` to produce the
            expected document.

    Returns:
        ``None`` after the decoded file text matches the rendered string exactly. ``read_text``
        applies normal universal-newline translation before comparison, and the rendered output
        itself ends with one LF; extra or missing trailing content therefore fails validation.
        The wrapper performs the same file read as ``ProgramStatusRenderer.validate`` and does
        not create or modify the path.

    Raises:
        ProgramGovernanceError: If the generated path is absent, the file cannot be read due to
            an ``OSError`` (with its cause preserved), or the decoded text differs from the
            rendered document. The check compares text only and performs no Markdown parsing or
            full-document sanitization.
        UnicodeDecodeError: If ``path`` is not valid UTF-8.
        KeyError: If rendering encounters a package state without a matching package.
        IndexError: If rendering encounters a directly constructed package state without an
            evidence path.
    """
    ProgramStatusRenderer(program).validate(path)
