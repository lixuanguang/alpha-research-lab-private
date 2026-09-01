"""Deterministic contract and adversarial tests for the enforced tooling graph."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter_ns

import pytest

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
from alpha_research_governance.repository_topology import main as canonical_main
from alpha_research_governance.repository_topology import (
    validate_repository as canonical_validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "repository-topology.toml"


def _topology_fixture(tmp_path: Path) -> tuple[Path, Path]:
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
    content = register.read_text(encoding="utf-8")
    assert old in content
    register.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_repository_topology_is_complete_and_acyclic() -> None:
    topology = validate_repository(REPOSITORY_ROOT)

    assert topology.delivery_slice == "B01c"
    assert topology.package_status == "partial"
    assert topology.slice_status == "provisionally_implemented"
    assert topology.remaining_slices == ()
    assert len(topology.units) == 20
    assert topology.unit("test.build").kind == "test"
    assert topology.unit("test.engineering").kind == "test"
    assert topology.unit("tool.governance.repository_topology").kind == "tool"
    assert topology.unit("compatibility.alpha_research.repository_topology").kind == (
        "compatibility"
    )


def test_compatibility_api_delegates_to_canonical_objects() -> None:
    assert alpha_research.__doc__
    assert RepositoryTopologyError is CanonicalRepositoryTopologyError
    assert load_topology is canonical_load_topology
    assert validate_repository is canonical_validate_repository
    assert canonical_ownership.validate_repository(REPOSITORY_ROOT)


def test_canonical_console_command_is_independent_of_source_path_and_working_directory(
    tmp_path: Path,
) -> None:
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
    assert "20 owned targets; B01 status is partial" in completed_process.stdout


def test_canonical_and_compatibility_module_commands_agree() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    outputs: list[str] = []
    for module in (
        "alpha_research_governance.repository_topology",
        "alpha_research.repository_topology",
    ):
        completed_process = subprocess.run(
            [sys.executable, "-m", module, str(REPOSITORY_ROOT)],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed_process.returncode == 0, completed_process.stderr
        outputs.append(completed_process.stdout)

    assert outputs[0] == outputs[1]
    assert "20 owned targets; B01 status is partial" in outputs[0]


def test_canonical_command_rejects_invalid_arguments_and_missing_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert canonical_main(["one", "two"]) == 2
    assert "usage:" in capsys.readouterr().err

    assert canonical_main([str(tmp_path / "missing")]) == 1
    assert "No such file or directory" in capsys.readouterr().err


def test_unknown_unit_fails_closed() -> None:
    topology = validate_repository(REPOSITORY_ROOT)

    with pytest.raises(RepositoryTopologyError, match="unknown source unit"):
        topology.unit("source.unknown")


def test_repository_validation_stays_within_the_governed_budget() -> None:
    started = perf_counter_ns()
    topology = validate_repository(REPOSITORY_ROOT)
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000

    assert len(topology.units) == 20
    assert elapsed_ms <= topology.validation_workload_budget_ms


def test_unregistered_current_source_is_rejected(tmp_path: Path) -> None:
    fixture_repository_root, register = _topology_fixture(tmp_path)
    (fixture_repository_root / "src/alpha_research/unregistered.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )

    with pytest.raises(RepositoryTopologyError, match="current source is not registered"):
        load_topology(register, repository_root=fixture_repository_root)


def test_duplicate_source_assignment_is_rejected(tmp_path: Path) -> None:
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
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        "dependencies = []\nvisibility = [\n"
        '  "compatibility.alpha_research.ownership_governance",\n'
        '  "test.engineering",\n]\nsources = '
        '["tools/governance/src/alpha_research_governance/ownership_governance.py"]',
        'dependencies = ["tool.governance.foundation"]\nvisibility = [\n'
        '  "compatibility.alpha_research.ownership_governance",\n'
        '  "test.engineering",\n]\nsources = '
        '["tools/governance/src/alpha_research_governance/ownership_governance.py"]',
    )

    with pytest.raises(RepositoryTopologyError, match=r"stale=.*foundation"):
        load_topology(register, repository_root=fixture_repository_root)


def test_from_package_import_cannot_hide_a_dependency(tmp_path: Path) -> None:
    fixture_repository_root, register = _topology_fixture(tmp_path)
    (fixture_repository_root / "src/alpha_research/architecture_governance.py").write_text(
        "from alpha_research import evidence\n", encoding="utf-8"
    )

    with pytest.raises(RepositoryTopologyError, match=r"missing=.*evidence"):
        load_topology(register, repository_root=fixture_repository_root)


def test_upward_dependency_and_cycle_are_rejected(tmp_path: Path) -> None:
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
            "kind must be compatibility, test, or tool",
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
        ("maximum_source_files = 1000", "maximum_source_files = 1", "must be 1000"),
        (
            "validation_workload_budget_ms = 1000",
            "validation_workload_budget_ms = 1",
            "must be 1000",
        ),
        (
            "remaining_slices = []",
            'remaining_slices = ["B02"]',
            "must be empty after B01c",
        ),
    ],
)
def test_invalid_registry_boundaries_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(register, old, new)

    with pytest.raises(RepositoryTopologyError, match=message):
        load_topology(register, repository_root=fixture_repository_root)


def test_unknown_registry_field_is_rejected(tmp_path: Path) -> None:
    fixture_repository_root, register = _topology_fixture(tmp_path)
    register.write_text(register.read_text(encoding="utf-8") + "\nunknown = true\n")

    with pytest.raises(RepositoryTopologyError, match="missing or unknown fields"):
        load_topology(register, repository_root=fixture_repository_root)


def test_source_roots_cannot_hide_a_current_area(tmp_path: Path) -> None:
    fixture_repository_root, register = _topology_fixture(tmp_path)
    _replace_topology_fixture_text(
        register,
        'source_roots = [\n  "src/alpha_research",\n  "tests/build",\n  "tests/engineering",\n'
        '  "tools/governance/src/alpha_research_governance",\n]',
        'source_roots = ["src/alpha_research"]',
    )

    with pytest.raises(RepositoryTopologyError, match="exact current source areas"):
        load_topology(register, repository_root=fixture_repository_root)


def test_evidence_manifest_path_cannot_escape_repository(tmp_path: Path) -> None:
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
    fixture_repository_root, register = _topology_fixture(tmp_path)
    register.write_text("schema_version = [\n", encoding="utf-8")

    with pytest.raises(RepositoryTopologyError, match="invalid TOML"):
        load_topology(register, repository_root=fixture_repository_root)


def test_topology_checker_is_enforced_by_root_pre_commit_and_hosted_ci() -> None:
    canonical_command = "alpha-governance-topology"
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    continuous_integration = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    assert canonical_command in makefile
    assert canonical_command in pre_commit
    assert canonical_command in continuous_integration
    assert "id: repository-topology" in pre_commit
    assert "always_run: true" in pre_commit
    automation_configuration = makefile + pre_commit + continuous_integration
    assert "python -m alpha_research." not in automation_configuration
    assert "PYTHONPATH=src" not in automation_configuration
