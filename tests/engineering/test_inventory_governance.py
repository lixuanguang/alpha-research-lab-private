"""Deterministic and adversarial tests for A06 resource inventories."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter_ns

import pytest

from alpha_research.inventory import (
    RESOURCE_KINDS,
    InventoryGovernanceError,
    load_inventory,
    main,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
CATALOG_PATH = REPOSITORY_ROOT / "docs" / "governance" / "resource-inventory.toml"


def _catalog_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "resource-inventory.toml"
    path.write_text(CATALOG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _load_fixture(path: Path) -> None:
    load_inventory(path, repository_root=REPOSITORY_ROOT)


def test_repository_inventory_is_versioned_partial_and_complete_for_current_scope() -> None:
    inventory = validate_repository(REPOSITORY_ROOT)

    assert inventory.catalog_version == 1
    assert inventory.package_status == "partial"
    assert inventory.maximum_items == 10_000
    assert inventory.query_workload_iterations == 10_000
    assert inventory.query_workload_budget_ms == 1_000
    assert inventory.local_evidence_manifest_path.endswith("a06-r2-partial/manifest.toml")
    assert inventory.local_evidence_commit_sha == "2" * 40
    assert tuple(kind.kind for kind in inventory.kinds) == RESOURCE_KINDS
    assert inventory.finding_ids == ("A06-F01", "A06-F02", "A06-F03")
    assert [item.inventory_id for item in inventory.items] == sorted(
        item.inventory_id for item in inventory.items
    )
    assert len(inventory.items) == 6
    assert {item.kind for item in inventory.items} == {"control"}
    assert all(item.status == "provisional" for item in inventory.items)


def test_queries_are_deterministic_and_preserve_explicit_empty_kinds() -> None:
    inventory = validate_repository(REPOSITORY_ROOT)

    assert inventory.query(kind="dataset") == ()
    controls = inventory.query(kind="control", owner_role="platform", status="provisional")
    assert len(controls) == 6
    assert [item.inventory_id for item in controls] == sorted(
        item.inventory_id for item in controls
    )
    assert all(item.record_version == 1 for item in controls)


def test_query_workload_stays_within_the_governed_budget() -> None:
    inventory = validate_repository(REPOSITORY_ROOT)

    started = perf_counter_ns()
    for _ in range(inventory.query_workload_iterations):
        inventory.query(kind="control", owner_role="platform", status="provisional")
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000

    assert elapsed_ms <= inventory.query_workload_budget_ms


def test_stale_owner_generates_a_finding(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(
        path,
        'name = "A01 repository charter and monorepo boundary"\nowner_role = "platform"',
        'name = "A01 repository charter and monorepo boundary"\nowner_role = "former_owner"',
    )

    with pytest.raises(InventoryGovernanceError, match="stale ownership role 'former_owner'"):
        _load_fixture(path)


def test_missing_dependency_lineage_generates_a_finding(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(
        path,
        'lineage_refs = [\n  "inv.control.governance.a01_repository_boundary",\n'
        '  "docs/architecture/principles.md",',
        'lineage_refs = [\n  "docs/README.md",\n  "docs/architecture/principles.md",',
    )

    with pytest.raises(InventoryGovernanceError, match="missing lineage for dependencies"):
        _load_fixture(path)


def test_unresolved_dependency_and_cycle_fail_closed(tmp_path: Path) -> None:
    unresolved = _catalog_fixture(tmp_path)
    _replace(
        unresolved,
        'dependencies = ["inv.control.governance.a04_change_risk"]',
        'dependencies = ["inv.control.governance.missing"]',
    )
    with pytest.raises(InventoryGovernanceError, match="unresolved dependency"):
        _load_fixture(unresolved)

    cyclic = _catalog_fixture(tmp_path)
    _replace(
        cyclic,
        "dependencies = []",
        'dependencies = ["inv.control.governance.a06_resource_inventory"]',
    )
    with pytest.raises(InventoryGovernanceError, match="inventory dependency cycle"):
        _load_fixture(cyclic)


def test_population_state_must_match_registered_items(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(
        path,
        'kind = "dataset"\npopulation_status = "empty"',
        'kind = "dataset"\npopulation_status = "populated"',
    )

    with pytest.raises(InventoryGovernanceError, match="kind 'dataset' must be 'empty'"):
        _load_fixture(path)


def test_deployed_resource_requires_deployment_evidence(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(path, 'deployment_status = "not_deployable"', 'deployment_status = "deployed"')

    with pytest.raises(InventoryGovernanceError, match="require deployment evidence"):
        _load_fixture(path)


def test_deployed_resource_accepts_explicit_deployment_evidence(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(
        path,
        'kind = "service"\npopulation_status = "empty"',
        'kind = "service"\npopulation_status = "populated"',
    )
    deployed_service = """[[items]]
inventory_id = "inv.service.synthetic.deployment_evidence"
kind = "service"
record_version = 1
name = "Synthetic deployment-evidence fixture"
owner_role = "platform"
criticality = "T3"
status = "provisional"
dependencies = ["inv.control.governance.a06_resource_inventory"]
retention_class = "deployable_service_lifecycle"
source_paths = ["docs/governance/resource-inventory.md"]
lineage_refs = [
  "inv.control.governance.a06_resource_inventory",
  "docs/governance/resource-inventory.md",
]
deployment_status = "deployed"
deployment_evidence = ["https://forge.example/deployments/a06-synthetic-fixture"]
status_evidence = ["docs/governance/resource-inventory.md"]
review_due_on = "2026-11-30"

"""
    _replace(path, "[[findings]]", deployed_service + "[[findings]]")

    inventory = load_inventory(path, repository_root=REPOSITORY_ROOT)

    services = inventory.query(kind="service")
    assert len(services) == 1
    assert services[0].deployment_status == "deployed"
    assert services[0].deployment_evidence == (
        "https://forge.example/deployments/a06-synthetic-fixture",
    )


def test_catalog_size_and_workload_limits_fail_closed(tmp_path: Path) -> None:
    size_limited = _catalog_fixture(tmp_path)
    _replace(size_limited, "maximum_items = 10000", "maximum_items = 1")
    with pytest.raises(InventoryGovernanceError, match="catalog contains 6 items"):
        _load_fixture(size_limited)

    invalid_budget = _catalog_fixture(tmp_path)
    _replace(invalid_budget, "query_workload_budget_ms = 1000", "query_workload_budget_ms = 0")
    with pytest.raises(InventoryGovernanceError, match="must be a positive integer"):
        _load_fixture(invalid_budget)


def test_overdue_review_and_unsafe_source_path_generate_findings(tmp_path: Path) -> None:
    stale = _catalog_fixture(tmp_path)
    _replace(stale, 'review_due_on = "2026-11-30"', 'review_due_on = "2026-08-29"')
    with pytest.raises(InventoryGovernanceError, match="ownership review is stale"):
        _load_fixture(stale)

    unsafe = _catalog_fixture(tmp_path)
    _replace(
        unsafe,
        '"docs/governance/repository-charter.md",',
        '"../repository-charter.md",',
    )
    with pytest.raises(InventoryGovernanceError, match="repository path escapes the root"):
        _load_fixture(unsafe)


def test_external_evidence_url_cannot_embed_credentials(tmp_path: Path) -> None:
    path = _catalog_fixture(tmp_path)
    _replace(
        path,
        'status_evidence = ["docs/governance/repository-charter.md"]',
        'status_evidence = ["https://user@example.com/evidence"]',
    )

    with pytest.raises(InventoryGovernanceError, match="HTTPS without credentials"):
        _load_fixture(path)


def test_partial_catalog_requires_exact_findings_and_solo_cannot_validate(
    tmp_path: Path,
) -> None:
    wrong_finding = _catalog_fixture(tmp_path)
    _replace(wrong_finding, 'finding_id = "A06-F02"', 'finding_id = "A06-OTHER"')
    with pytest.raises(InventoryGovernanceError, match="partial status requires findings"):
        _load_fixture(wrong_finding)

    validated = _catalog_fixture(tmp_path)
    _replace(validated, 'package_status = "partial"', 'package_status = "validated"')
    with pytest.raises(InventoryGovernanceError, match="solo_bootstrap.*cannot claim validated"):
        _load_fixture(validated)

    validated_item = _catalog_fixture(tmp_path)
    _replace(validated_item, 'status = "provisional"', 'status = "validated"')
    with pytest.raises(InventoryGovernanceError, match="resources cannot claim validated"):
        _load_fixture(validated_item)


def test_cli_emits_stable_json_for_populated_and_empty_queries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([str(REPOSITORY_ROOT), "--kind", "control"]) == 0
    first_output = capsys.readouterr().out
    assert main([str(REPOSITORY_ROOT), "--kind", "control"]) == 0
    second_output = capsys.readouterr().out
    assert first_output == second_output

    controls = json.loads(first_output)
    assert controls["count"] == 6
    assert [item["inventory_id"] for item in controls["items"]] == sorted(
        item["inventory_id"] for item in controls["items"]
    )
    assert controls["query_limits"] == {
        "maximum_items": 10_000,
        "workload_budget_ms": 1_000,
        "workload_iterations": 10_000,
    }

    assert main([str(REPOSITORY_ROOT), "--kind", "dataset"]) == 0
    datasets = json.loads(capsys.readouterr().out)
    assert datasets["count"] == 0
    assert datasets["items"] == []
    assert datasets["kind_states"] == [
        {
            "kind": "dataset",
            "owner_role": "data_platform",
            "population_status": "empty",
            "rationale": (
                "No canonical or curated dataset has been implemented; bootstrap fixtures "
                "are governance evidence, not datasets."
            ),
        }
    ]
    assert datasets["open_finding_ids"] == ["A06-F01", "A06-F02", "A06-F03"]
    assert "Repository-local" in datasets["inventory_scope"]


def test_cli_rejects_unknown_kind_and_missing_catalog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(REPOSITORY_ROOT), "--kind", "unknown"]) == 1
    assert "unsupported inventory kind" in capsys.readouterr().err

    assert main([str(REPOSITORY_ROOT), "--status", "unknown"]) == 1
    assert "unsupported inventory status" in capsys.readouterr().err

    assert main([str(tmp_path)]) == 1
    assert "domain-ownership.toml" in capsys.readouterr().err

    assert main(["--kind"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_inventory_checker_is_integrated_with_repository_automation() -> None:
    command = "python -m alpha_research.inventory"
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    continuous_integration = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    documentation = (REPOSITORY_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert command in makefile
    assert command in pre_commit
    assert command in continuous_integration
    assert "make inventory-check" in documentation
