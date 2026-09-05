"""Deterministic contract and adversarial tests for the enforced tooling graph."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
from pathlib import Path
from time import perf_counter

# third party library imports
import pytest

# project library imports
import alpha_research
from alpha_research.repository_topology import (
    RepositoryTopologyError,
    load_topology,
    validate_repository,
)
from alpha_research_governance import ownership_governance as canonical_ownership
from alpha_research_governance.repository_topology import (
    RepositoryTopologyError as CanonicalRepositoryTopologyError,
)
from alpha_research_governance.repository_topology import (
    load_topology as canonical_load_topology,
)
from alpha_research_governance.repository_topology import (
    validate_repository as canonical_validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "repository-topology.toml"


def _topology_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Build a fresh partial repository fixture and copy its topology register for mutation.

    The destination ``repository`` directory must not already exist because the
    source-tree copies use ``copytree``. The fixture includes selected ``src``,
    ``tests`` and governance source trees plus the ownership and topology registers;
    it is not a complete repository checkout.

    Args:
        tmp_path: Pytest-managed directory that receives the fixture repository.

    Returns:
        A pair containing the fixture repository root and its copied topology register.

    Raises:
        OSError: If source trees or fixture files cannot be copied or created.
    """
    fixture_repository_root = tmp_path / "repository"
    shutil.copytree(REPOSITORY_ROOT / "src", fixture_repository_root / "src")
    shutil.copytree(REPOSITORY_ROOT / "tests", fixture_repository_root / "tests")
    shutil.copytree(
        REPOSITORY_ROOT / "tools/governance/src",
        fixture_repository_root / "tools/governance/src",
    )
    governance = fixture_repository_root / "docs" / "governance"
    governance.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "docs/governance/domain-ownership.toml", governance)
    architecture = fixture_repository_root / "docs" / "architecture"
    architecture.mkdir()
    register = architecture / "repository-topology.toml"
    shutil.copy2(REGISTER_PATH, register)
    return fixture_repository_root, register


def _replace_topology_fixture_text(register: Path, old: str, new: str) -> None:
    """Replace the first exact text fragment in a temporary topology register.

    Args:
        register: Temporary TOML topology register to read and rewrite.
        old: Exact fragment that must occur in the register.
        new: Replacement fragment written in place of the first match.

    Raises:
        AssertionError: If ``old`` does not occur in the register.
        OSError: If the register cannot be read or written.
    """
    content = register.read_text(encoding="utf-8")
    assert old in content
    register.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_repository_topology_is_complete_and_acyclic() -> None:
    """Verify the complete B01 topology metadata, owned-unit count and representative kinds."""
    topology = validate_repository(REPOSITORY_ROOT)

    assert topology.delivery_slice == "B01c"
    assert topology.package_status == "partial"
    assert topology.slice_status == "provisionally_implemented"
    assert topology.remaining_slices == ()
    assert topology.validation_workload_budget_ms == 1_000
    assert len(topology.units) == 32
    assert topology.unit("library.alpha_research.instrument_identity").kind == "library"
    assert topology.unit("library.alpha_research.venue_calendar").kind == "library"
    assert topology.unit("test.build").kind == "test"
    assert topology.unit("test.engineering").kind == "test"
    assert topology.unit("tool.governance.repository_topology").kind == "tool"
    assert topology.unit("tool.governance.artifact_supply_chain").kind == "tool"
    assert topology.unit("tool.governance.engineering_standards").kind == "tool"
    assert topology.unit("tool.governance.ci_policy").kind == "tool"
    assert topology.unit("tool.governance.dependency_admission").kind == "tool"
    assert topology.unit("tool.governance.remote_execution").kind == "tool"
    assert topology.unit("compatibility.alpha_research.ci_policy").kind == "compatibility"
    assert topology.unit("compatibility.alpha_research.repository_topology").kind == (
        "compatibility"
    )


@pytest.mark.performance
def test_topology_validation_workload_stays_within_governed_budget() -> None:
    """Keep authoritative topology validation within its recorded millisecond budget."""
    started_at = perf_counter()
    topology = validate_repository(REPOSITORY_ROOT)
    elapsed_ms = (perf_counter() - started_at) * 1_000

    assert elapsed_ms <= topology.validation_workload_budget_ms, (
        f"topology validation took {elapsed_ms:.1f} ms; "
        f"budget is {topology.validation_workload_budget_ms} ms"
    )


def test_compatibility_api_delegates_to_canonical_objects() -> None:
    """Verify topology facade aliases and canonical ownership validation."""
    assert alpha_research.__doc__
    assert RepositoryTopologyError is CanonicalRepositoryTopologyError
    assert load_topology is canonical_load_topology
    assert validate_repository is canonical_validate_repository
    assert canonical_ownership.validate_repository(REPOSITORY_ROOT)


def test_canonical_console_command_is_independent_of_source_path_and_working_directory(
    tmp_path: Path,
) -> None:
    """Run the topology console command from a temporary directory without PYTHONPATH coupling."""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed_process = subprocess.run(
        ["alpha-governance-topology", str(REPOSITORY_ROOT)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed_process.returncode == 0, completed_process.stderr
    assert "32 owned targets; B01 status is partial" in completed_process.stdout


def test_unregistered_current_source_is_rejected(tmp_path: Path) -> None:
    """Reject a current source file that is absent from the declared topology register."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    (fixture_repository_root / "src/alpha_research/unregistered.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )

    with pytest.raises(RepositoryTopologyError, match="current source is not registered"):
        load_topology(register, repository_root=fixture_repository_root)


def test_duplicate_source_assignment_is_rejected(tmp_path: Path) -> None:
    """Reject a topology register assigning one source path to two owned units."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'sources = ["src/alpha_research/architecture_governance.py"]',
        'sources = ["src/alpha_research/architecture_governance.py", '
        '"src/alpha_research/ownership_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match="assigned to both"):
        load_topology(register, repository_root=fixture_repository_root)


def test_undeclared_import_dependency_is_rejected(tmp_path: Path) -> None:
    """Reject a declared unit whose registry dependencies omit an imported unit."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'dependencies = ["tool.governance.architecture_governance"]\n'
        'visibility = ["test.engineering"]\n'
        'sources = ["src/alpha_research/architecture_governance.py"]',
        'dependencies = []\nvisibility = ["test.engineering"]\n'
        'sources = ["src/alpha_research/architecture_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match=r"missing=.*architecture_governance"):
        load_topology(register, repository_root=fixture_repository_root)


def test_stale_dependency_and_visibility_are_rejected(tmp_path: Path) -> None:
    """Reject a stale change-risk dependency declaration with the expected diagnostic."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'dependencies = ["tool.governance.foundation"]\nvisibility = [\n'
        '  "compatibility.alpha_research.ownership_governance",\n'
        '  "test.engineering",\n]\nsources = '
        '["tools/governance/src/alpha_research_governance/ownership_governance.py"]',
        'dependencies = ["tool.governance.change_risk", "tool.governance.foundation"]\n'
        "visibility = [\n"
        '  "compatibility.alpha_research.ownership_governance",\n'
        '  "test.engineering",\n]\nsources = '
        '["tools/governance/src/alpha_research_governance/ownership_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match=r"stale=.*change_risk"):
        load_topology(register, repository_root=fixture_repository_root)


def test_from_package_import_cannot_hide_a_dependency(tmp_path: Path) -> None:
    """Resolve package-level imports and reject an undeclared cross-unit dependency."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    (fixture_repository_root / "src/alpha_research/architecture_governance.py").write_text(
        "from alpha_research import evidence\n", encoding="utf-8"
    )

    with pytest.raises(RepositoryTopologyError, match=r"missing=.*evidence"):
        load_topology(register, repository_root=fixture_repository_root)


def test_upward_dependency_and_cycle_are_rejected(tmp_path: Path) -> None:
    """Report the source dependency cycle created by a layer and dependency mutation."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'unit_id = "tool.governance.change_risk"\nkind = "tool"\nlayer = "policy"',
        'unit_id = "tool.governance.change_risk"\nkind = "tool"\nlayer = "evidence"',
    )
    _replace_topology_fixture_text(
        register,
        'dependencies = ["tool.governance.foundation"]\nvisibility = [\n'
        '  "compatibility.alpha_research.change_risk",',
        'dependencies = ["tool.governance.evidence", '
        '"tool.governance.foundation"]\nvisibility = [\n'
        '  "compatibility.alpha_research.change_risk",',
    )

    with pytest.raises(RepositoryTopologyError, match="source dependency cycle"):
        load_topology(register, repository_root=fixture_repository_root)


def test_unknown_dependency_is_a_domain_error(tmp_path: Path) -> None:
    """Translate an unknown dependency identifier into the topology domain error."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'dependencies = ["tool.governance.architecture_governance"]\n'
        'visibility = ["test.engineering"]',
        'dependencies = ["source.unknown"]\nvisibility = ["test.engineering"]',
    )

    with pytest.raises(RepositoryTopologyError, match="unknown dependency"):
        load_topology(register, repository_root=fixture_repository_root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('owner_role = "domain_architecture"', 'owner_role = "stale_owner"', "stale owner"),
        (
            'kind = "compatibility"',
            'kind = "service"',
            "kind must be compatibility, library, test, or tool",
        ),
        (
            'sources = ["src/alpha_research/architecture_governance.py"]',
            'sources = ["../outside.py"]',
            "invalid repository path",
        ),
        (
            'visibility = ["test.engineering"]',
            "visibility = []",
            "visibility must exactly match direct consumers",
        ),
    ],
)
def test_invalid_registry_boundaries_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    """Reject invalid owner, kind, path and visibility boundary mutations."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(register, old, new)

    with pytest.raises(RepositoryTopologyError, match=message):
        load_topology(register, repository_root=fixture_repository_root)


def test_unknown_registry_field_is_rejected(tmp_path: Path) -> None:
    """Reject an unknown field appended to the final topology unit record."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    register.write_text(register.read_text(encoding="utf-8") + "\nunknown = true\n")

    with pytest.raises(RepositoryTopologyError, match="missing or unknown fields"):
        load_topology(register, repository_root=fixture_repository_root)


def test_source_roots_cannot_hide_a_current_area(tmp_path: Path) -> None:
    """Reject source-root declarations that omit one of the repository's current source areas."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'source_roots = [\n  "src/alpha_research",\n  "tests/build",\n  "tests/engineering",\n'
        '  "tests/unit",\n'
        '  "tools/governance/src/alpha_research_governance",\n]',
        'source_roots = ["src/alpha_research"]',
    )

    with pytest.raises(RepositoryTopologyError, match="exact current source areas"):
        load_topology(register, repository_root=fixture_repository_root)


def test_evidence_manifest_path_cannot_escape_repository(tmp_path: Path) -> None:
    """Reject a local topology evidence path that escapes the fixture repository root."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        "local_evidence_manifest_path = "
        '"docs/governance/evidence/examples/b01c-r2-partial/manifest.toml"',
        'local_evidence_manifest_path = "../outside.toml"',
    )

    with pytest.raises(RepositoryTopologyError, match="invalid repository path"):
        validate_repository(fixture_repository_root)


def test_malformed_toml_is_reported_as_domain_error(tmp_path: Path) -> None:
    """Translate malformed topology TOML into the repository topology domain error."""
    fixture_repository_root, register = _topology_fixture(tmp_path)
    register.write_text("schema_version = [\n", encoding="utf-8")

    with pytest.raises(RepositoryTopologyError, match="invalid TOML"):
        load_topology(register, repository_root=fixture_repository_root)
