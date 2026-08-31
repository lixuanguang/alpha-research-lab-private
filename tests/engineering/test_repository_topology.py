"""Deterministic contract and adversarial tests for the B01a source graph."""

from __future__ import annotations

import shutil
from pathlib import Path
from time import perf_counter_ns

import pytest

from alpha_research.repository_topology import (
    RepositoryTopologyError,
    load_topology,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "repository-topology.toml"


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repository"
    shutil.copytree(REPOSITORY_ROOT / "src", root / "src")
    shutil.copytree(REPOSITORY_ROOT / "tests", root / "tests")
    governance = root / "docs" / "governance"
    governance.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "docs/governance/domain-ownership.toml", governance)
    architecture = root / "docs" / "architecture"
    architecture.mkdir()
    register = architecture / "repository-topology.toml"
    shutil.copy2(REGISTER_PATH, register)
    return root, register


def _replace(register: Path, old: str, new: str) -> None:
    content = register.read_text(encoding="utf-8")
    assert old in content
    register.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_repository_topology_is_complete_and_acyclic() -> None:
    topology = validate_repository(REPOSITORY_ROOT)

    assert topology.delivery_slice == "B01a"
    assert topology.package_status == "partial"
    assert topology.slice_status == "provisionally_implemented"
    assert topology.remaining_slices == ("B01b", "B01c")
    assert len(topology.units) == 10
    assert topology.unit("test.engineering").kind == "test"


def test_unknown_unit_fails_closed() -> None:
    topology = validate_repository(REPOSITORY_ROOT)

    with pytest.raises(RepositoryTopologyError, match="unknown source unit"):
        topology.unit("source.unknown")


def test_repository_validation_stays_within_the_governed_budget() -> None:
    started = perf_counter_ns()
    topology = validate_repository(REPOSITORY_ROOT)
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000

    assert len(topology.units) == 10
    assert elapsed_ms <= topology.validation_workload_budget_ms


def test_unregistered_current_source_is_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    (root / "src/alpha_research/unregistered.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(RepositoryTopologyError, match="current source is not registered"):
        load_topology(register, repository_root=root)


def test_duplicate_source_assignment_is_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'sources = ["src/alpha_research/architecture_governance.py"]',
        'sources = ["src/alpha_research/architecture_governance.py", '
        '"src/alpha_research/ownership_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match="assigned to both"):
        load_topology(register, repository_root=root)


def test_undeclared_import_dependency_is_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'dependencies = ["source.alpha_research.foundation"]\nvisibility = ["test.engineering"]',
        'dependencies = []\nvisibility = ["test.engineering"]',
    )

    with pytest.raises(RepositoryTopologyError, match=r"missing=.*foundation"):
        load_topology(register, repository_root=root)


def test_stale_dependency_and_visibility_are_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'dependencies = []\nvisibility = ["test.engineering"]\nsources = '
        '["src/alpha_research/ownership_governance.py"]',
        'dependencies = ["source.alpha_research.foundation"]\n'
        'visibility = ["test.engineering"]\nsources = '
        '["src/alpha_research/ownership_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match=r"stale=.*foundation"):
        load_topology(register, repository_root=root)


def test_from_package_import_cannot_hide_a_dependency(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    (root / "src/alpha_research/architecture_governance.py").write_text(
        "from alpha_research import evidence\n", encoding="utf-8"
    )

    with pytest.raises(RepositoryTopologyError, match=r"missing=.*evidence"):
        load_topology(register, repository_root=root)


def test_upward_dependency_and_cycle_are_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'unit_id = "source.alpha_research.change_risk"\nkind = "library"\nlayer = "policy"',
        'unit_id = "source.alpha_research.change_risk"\nkind = "library"\nlayer = "evidence"',
    )
    _replace(
        register,
        'dependencies = ["source.alpha_research.foundation"]\nvisibility = [\n'
        '  "source.alpha_research.evidence",',
        'dependencies = ["source.alpha_research.evidence", '
        '"source.alpha_research.foundation"]\nvisibility = [\n'
        '  "source.alpha_research.evidence",',
    )

    with pytest.raises(RepositoryTopologyError, match="source dependency cycle"):
        load_topology(register, repository_root=root)


def test_unknown_dependency_is_a_domain_error(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'dependencies = ["source.alpha_research.foundation"]\nvisibility = ["test.engineering"]',
        'dependencies = ["source.unknown"]\nvisibility = ["test.engineering"]',
    )

    with pytest.raises(RepositoryTopologyError, match="unknown dependency"):
        load_topology(register, repository_root=root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('owner_role = "domain_architecture"', 'owner_role = "stale_owner"', "stale owner"),
        ('kind = "library"', 'kind = "service"', "kind must be library or test"),
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
        ("maximum_source_files = 1000", "maximum_source_files = 1", "must be 1000"),
        (
            "validation_workload_budget_ms = 1000",
            "validation_workload_budget_ms = 1",
            "must be 1000",
        ),
    ],
)
def test_invalid_registry_boundaries_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root, register = _fixture(tmp_path)
    _replace(register, old, new)

    with pytest.raises(RepositoryTopologyError, match=message):
        load_topology(register, repository_root=root)


def test_unknown_registry_field_is_rejected(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    register.write_text(register.read_text(encoding="utf-8") + "\nunknown = true\n")

    with pytest.raises(RepositoryTopologyError, match="missing or unknown fields"):
        load_topology(register, repository_root=root)


def test_source_roots_cannot_hide_a_current_area(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        'source_roots = ["src/alpha_research", "tests/engineering"]',
        'source_roots = ["src/alpha_research"]',
    )

    with pytest.raises(RepositoryTopologyError, match="exact current source areas"):
        load_topology(register, repository_root=root)


def test_evidence_manifest_path_cannot_escape_repository(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    _replace(
        register,
        "local_evidence_manifest_path = "
        '"docs/governance/evidence/examples/b01a-r2-partial/manifest.toml"',
        'local_evidence_manifest_path = "../outside.toml"',
    )

    with pytest.raises(RepositoryTopologyError, match="invalid repository path"):
        validate_repository(root)


def test_malformed_toml_is_reported_as_domain_error(tmp_path: Path) -> None:
    root, register = _fixture(tmp_path)
    register.write_text("schema_version = [\n", encoding="utf-8")

    with pytest.raises(RepositoryTopologyError, match="invalid TOML"):
        load_topology(register, repository_root=root)
