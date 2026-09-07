"""Deterministic and adversarial tests for resource inventories."""

from __future__ import annotations

# standard library imports
from pathlib import Path
from time import perf_counter

# third party library imports
import pytest
from pydantic import TypeAdapter

# project library imports
from alpha_research.inventory import (
    RESOURCE_KINDS,
    InventoryGovernanceError,
    InventoryItem,
    load_inventory,
    main,
    validate_repository,
)
from alpha_research_governance.inventory.registry import InventoryLoader, _find_dependency_cycles

REPOSITORY_ROOT = Path(__file__).parents[2]
CATALOG_PATH = REPOSITORY_ROOT / "docs" / "governance" / "resource-inventory.toml"


def _json_object(value: object) -> dict[str, object]:
    """Narrow one inventory CLI response to a JSON object."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("expected a JSON object")
    return value


def _json_list(value: object) -> list[object]:
    """Narrow one inventory CLI response field to a JSON array."""
    if not isinstance(value, list):
        raise TypeError("expected a JSON array")
    return value


def _catalog_fixture(tmp_path: Path) -> Path:
    """Copy the repository catalog into a temporary fixture, overwriting any existing copy.

    Args:
        tmp_path: Pytest-managed directory that receives the copied catalog.

    Returns:
        Path to the writable TOML fixture; the repository catalog remains unchanged.

    Raises:
        OSError: If the source catalog cannot be read or the fixture cannot be written.
    """
    path = tmp_path / "resource-inventory.toml"
    path.write_text(CATALOG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace_inventory_fixture_text(path: Path, old: str, new: str) -> None:
    """Replace the first matching text fragment in a temporary inventory fixture.

    Args:
        path: Temporary TOML fixture to read and rewrite.
        old: Exact fragment that must occur in the fixture.
        new: Replacement fragment written in place of the first match.

    Raises:
        AssertionError: If ``old`` does not occur in the fixture.
        OSError: If the fixture cannot be read or written.
    """
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _validate_inventory_fixture(path: Path) -> None:
    """Load a temporary inventory and validate its references against the real repository.

    This helper exercises ``load_inventory`` only; it does not run the separate local
    evidence-bundle checks performed by ``validate_repository``.

    Args:
        path: Temporary inventory TOML file to validate.

    Raises:
        InventoryGovernanceError: If the fixture violates inventory governance rules.
        OSError: If the inventory or ownership register cannot be read.
    """
    load_inventory(path, repository_root=REPOSITORY_ROOT)


class TestInventoryGovernance:
    """Exercise inventory schema, ownership, lineage, and dependency contracts."""

    def test_loader_reuses_context_after_a_failed_load(self, tmp_path: Path) -> None:
        """Keep one loader usable after a failed invocation without stale findings."""
        path = _catalog_fixture(tmp_path)
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original.replace("schema_version = 1", "schema_version = 9", 1), encoding="utf-8"
        )
        loader = InventoryLoader(REPOSITORY_ROOT)

        with pytest.raises(InventoryGovernanceError, match="schema_version"):
            loader.load(path)

        path.write_text(original, encoding="utf-8")
        assert loader.load(path) == load_inventory(path, repository_root=REPOSITORY_ROOT)

    def test_repository_inventory_is_versioned_partial_and_complete_for_current_scope(
        self,
    ) -> None:
        """Verify the inventory version, status, limits, items and lineage."""
        inventory = validate_repository(REPOSITORY_ROOT)

        assert inventory.catalog_version == 8
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
        assert len(inventory.items) == 16
        assert {item.kind for item in inventory.items} == {"control"}
        assert all(item.status == "provisional" for item in inventory.items)
        repository_topology_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b01_repository_topology"
        )
        assert repository_topology_control.dependencies == (
            "inv.control.governance.a02_architecture_governance",
            "inv.control.governance.a03_ownership_governance",
            "inv.control.governance.a04_change_risk",
            "inv.control.governance.a05_merge_evidence",
        )
        build_graph_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b02_hermetic_build_graph"
        )
        assert build_graph_control.dependencies == (
            "inv.control.governance.a04_change_risk",
            "inv.control.governance.a05_merge_evidence",
            "inv.control.governance.b01_repository_topology",
        )
        environment_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b03_clean_machine_environment"
        )
        assert environment_control.dependencies == (
            "inv.control.governance.a04_change_risk",
            "inv.control.governance.a05_merge_evidence",
            "inv.control.governance.b02_hermetic_build_graph",
        )
        engineering_standards_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b04_engineering_standards"
        )
        assert engineering_standards_control.dependencies == (
            "inv.control.governance.a04_change_risk",
            "inv.control.governance.a05_merge_evidence",
            "inv.control.governance.b02_hermetic_build_graph",
            "inv.control.governance.b03_clean_machine_environment",
        )
        ci_policy_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b05_ci_policy"
        )
        assert ci_policy_control.dependencies == (
            "inv.control.governance.b01_repository_topology",
            "inv.control.governance.b02_hermetic_build_graph",
            "inv.control.governance.b03_clean_machine_environment",
            "inv.control.governance.b04_engineering_standards",
        )
        remote_execution_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b06_remote_execution"
        )
        assert remote_execution_control.dependencies == ("inv.control.governance.b05_ci_policy",)
        assert remote_execution_control.deployment_status == "not_deployable"
        dependency_admission_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b07_dependency_admission"
        )
        assert dependency_admission_control.dependencies == (
            "inv.control.governance.b02_hermetic_build_graph",
            "inv.control.governance.b03_clean_machine_environment",
            "inv.control.governance.b04_engineering_standards",
            "inv.control.governance.b05_ci_policy",
            "inv.control.governance.b06_remote_execution",
        )
        assert dependency_admission_control.deployment_status == "not_deployable"
        artifact_supply_chain_control = next(
            item
            for item in inventory.items
            if item.inventory_id == "inv.control.governance.b08_artifact_supply_chain"
        )
        assert artifact_supply_chain_control.dependencies == (
            "inv.control.governance.a07_security_controls",
            "inv.control.governance.b07_dependency_admission",
        )
        assert artifact_supply_chain_control.deployment_status == "not_deployable"

    def test_inventory_dates_require_extended_calendar_format(self, tmp_path: Path) -> None:
        """Reject a catalog date that is not an ISO extended calendar date."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'as_of_date = "2026-09-03"',
            'as_of_date = "20260901"',
        )

        with pytest.raises(InventoryGovernanceError, match="must use YYYY-MM-DD"):
            _validate_inventory_fixture(path)

    def test_stale_owner_generates_a_finding(self, tmp_path: Path) -> None:
        """Report a finding when an inventory item names an unregistered owner role."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'name = "A01 repository charter and monorepo boundary"\nowner_role = "platform"',
            'name = "A01 repository charter and monorepo boundary"\nowner_role = "former_owner"',
        )

        with pytest.raises(InventoryGovernanceError, match="stale ownership role 'former_owner'"):
            _validate_inventory_fixture(path)

    def test_missing_dependency_lineage_generates_a_finding(self, tmp_path: Path) -> None:
        """Report when an item's dependency is omitted from lineage references."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'lineage_refs = [\n  "inv.control.governance.a01_repository_boundary",\n'
            '  "docs/architecture/principles.md",',
            'lineage_refs = [\n  "docs/README.md",\n  "docs/architecture/principles.md",',
        )

        with pytest.raises(InventoryGovernanceError, match="missing lineage for dependencies"):
            _validate_inventory_fixture(path)

    def test_unresolved_dependency_and_cycle_fail_closed(self, tmp_path: Path) -> None:
        """Reject both an unknown dependency and a dependency cycle in separate fixtures."""
        unresolved = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            unresolved,
            'dependencies = ["inv.control.governance.a04_change_risk"]',
            'dependencies = ["inv.control.governance.missing"]',
        )
        with pytest.raises(InventoryGovernanceError, match="unresolved dependency"):
            _validate_inventory_fixture(unresolved)

        cyclic = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            cyclic,
            "dependencies = []",
            'dependencies = ["inv.control.governance.a06_resource_inventory"]',
        )
        with pytest.raises(InventoryGovernanceError, match="inventory dependency cycle"):
            _validate_inventory_fixture(cyclic)

    def test_population_state_must_match_registered_items(self, tmp_path: Path) -> None:
        """Reject a kind population declaration that disagrees with its registered item count."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'kind = "dataset"\npopulation_status = "empty"',
            'kind = "dataset"\npopulation_status = "populated"',
        )

        with pytest.raises(InventoryGovernanceError, match="kind 'dataset' must be 'empty'"):
            _validate_inventory_fixture(path)

    def test_deployed_resource_requires_deployment_evidence(self, tmp_path: Path) -> None:
        """Reject a deployed resource whose record lacks deployment evidence."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'deployment_status = "not_deployable"',
            'deployment_status = "deployed"',
        )

        with pytest.raises(InventoryGovernanceError, match="require deployment evidence"):
            _validate_inventory_fixture(path)

    def test_deployed_resource_accepts_explicit_deployment_evidence(self, tmp_path: Path) -> None:
        """Accept a synthetic deployed service with a declared valid HTTPS evidence reference."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
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
        _replace_inventory_fixture_text(path, "[[findings]]", deployed_service + "[[findings]]")

        inventory = load_inventory(path, repository_root=REPOSITORY_ROOT)

        services = inventory.query(kind="service")
        assert len(services) == 1
        assert services[0].deployment_status == "deployed"
        assert services[0].deployment_evidence == (
            "https://forge.example/deployments/a06-synthetic-fixture",
        )

    def test_overdue_review_and_unsafe_source_path_generate_findings(self, tmp_path: Path) -> None:
        """Report stale review and repository-escaping source-path findings independently."""
        stale = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            stale, 'review_due_on = "2026-11-30"', 'review_due_on = "2026-08-29"'
        )
        with pytest.raises(InventoryGovernanceError, match="ownership review is stale"):
            _validate_inventory_fixture(stale)

        unsafe = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            unsafe,
            '"docs/governance/repository-charter.md",',
            '"../repository-charter.md",',
        )
        with pytest.raises(InventoryGovernanceError, match="repository path escapes the root"):
            _validate_inventory_fixture(unsafe)

    @pytest.mark.parametrize(
        ("unsafe_url", "message"),
        [
            (
                "https://:synthetic-secret@example.com/evidence",
                "HTTPS without credentials",
            ),
            ("https://[malformed/evidence", "malformed"),
        ],
    )
    def test_external_evidence_url_cannot_embed_credentials_or_be_malformed(
        self, tmp_path: Path, unsafe_url: str, message: str
    ) -> None:
        """Reject evidence references containing credentials or malformed external URLs."""
        path = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            path,
            'status_evidence = ["docs/governance/repository-charter.md"]',
            f'status_evidence = ["{unsafe_url}"]',
        )

        with pytest.raises(InventoryGovernanceError, match=message):
            _validate_inventory_fixture(path)

    def test_partial_catalog_requires_exact_findings_and_solo_cannot_validate(
        self,
        tmp_path: Path,
    ) -> None:
        """Enforce partial findings and prohibit validated solo-bootstrap claims."""
        wrong_finding = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            wrong_finding, 'finding_id = "A06-F02"', 'finding_id = "A06-OTHER"'
        )
        with pytest.raises(InventoryGovernanceError, match="partial status requires findings"):
            _validate_inventory_fixture(wrong_finding)

        validated = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            validated, 'package_status = "partial"', 'package_status = "validated"'
        )
        with pytest.raises(
            InventoryGovernanceError, match=r"solo_bootstrap.*cannot claim validated"
        ):
            _validate_inventory_fixture(validated)

        validated_item = _catalog_fixture(tmp_path)
        _replace_inventory_fixture_text(
            validated_item, 'status = "provisional"', 'status = "validated"'
        )
        with pytest.raises(InventoryGovernanceError, match="resources cannot claim validated"):
            _validate_inventory_fixture(validated_item)


class TestInventoryCli:
    """Exercise deterministic filtered inventory CLI output."""

    def test_cli_emits_stable_json_for_populated_and_empty_queries(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify deterministic filtered JSON for populated controls and an empty dataset query."""
        assert main([str(REPOSITORY_ROOT), "--kind", "control"]) == 0
        first_output = capsys.readouterr().out
        assert main([str(REPOSITORY_ROOT), "--kind", "control"]) == 0
        second_output = capsys.readouterr().out
        assert first_output == second_output

        controls = _json_object(TypeAdapter(dict[str, object]).validate_json(first_output))
        assert controls["count"] == 16
        control_rows = [_json_object(item) for item in _json_list(controls["items"])]
        control_ids = [item["inventory_id"] for item in control_rows]
        assert all(isinstance(item_id, str) for item_id in control_ids)
        assert control_ids == sorted(item_id for item_id in control_ids if isinstance(item_id, str))
        assert controls["query_limits"] == {
            "maximum_items": 10_000,
            "workload_budget_ms": 1_000,
            "workload_iterations": 10_000,
        }

        assert main([str(REPOSITORY_ROOT), "--kind", "dataset"]) == 0
        datasets = _json_object(
            TypeAdapter(dict[str, object]).validate_json(capsys.readouterr().out)
        )
        assert datasets["count"] == 0
        assert _json_list(datasets["items"]) == []
        assert _json_list(datasets["kind_states"]) == [
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
        assert isinstance(datasets["inventory_scope"], str)
        assert "Repository-local" in datasets["inventory_scope"]


class TestInventoryWorkload:
    """Exercise governed inventory query and dependency workloads."""

    @pytest.mark.performance
    def test_inventory_query_workload_stays_within_governed_budget(self) -> None:
        """Keep repeated inventory queries with varied filters within the recorded time budget."""
        inventory = validate_repository(REPOSITORY_ROOT)

        started_at = perf_counter()
        for iteration in range(inventory.query_workload_iterations):
            if iteration % 4 == 0:
                inventory.query()
            elif iteration % 4 == 1:
                inventory.query(kind="control")
            elif iteration % 4 == 2:
                inventory.query(status="provisional")
            else:
                inventory.query(owner_role="platform")
        elapsed_ms = (perf_counter() - started_at) * 1_000

        assert elapsed_ms <= inventory.query_workload_budget_ms, (
            f"{inventory.query_workload_iterations} inventory queries took "
            f"{elapsed_ms:.1f} ms; budget is {inventory.query_workload_budget_ms} ms"
        )

    def test_dependency_cycle_check_handles_catalog_limit_depth(self) -> None:
        """Handle a 1,500-item dependency chain without falsely reporting a cycle."""
        template = validate_repository(REPOSITORY_ROOT).items[0]
        item_count = 1_500
        items = tuple(
            InventoryItem(
                record_version=template.record_version,
                name=template.name,
                owner_role=template.owner_role,
                criticality=template.criticality,
                status=template.status,
                retention_class=template.retention_class,
                source_paths=template.source_paths,
                lineage_refs=template.lineage_refs,
                deployment_status=template.deployment_status,
                deployment_evidence=template.deployment_evidence,
                status_evidence=template.status_evidence,
                review_due_on=template.review_due_on,
                inventory_id=f"inv.service.synthetic.deep_{index:04d}",
                kind="service",
                dependencies=(
                    (f"inv.service.synthetic.deep_{index + 1:04d}",)
                    if index + 1 < item_count
                    else ()
                ),
            )
            for index in range(item_count)
        )

        assert _find_dependency_cycles(items) == ()
