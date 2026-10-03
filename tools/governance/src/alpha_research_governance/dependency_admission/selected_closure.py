"""Admit the actual wheel dependency closure of one operating release artifact."""

from __future__ import annotations

# standard library imports
import hashlib
import platform
import sys
import sysconfig
from collections import deque
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

# third party library imports
from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
)
from alpha_research_governance.dependency_admission.policy import DependencyRepository
from alpha_research_governance.dependency_admission.wheel_archive import (
    WheelArchive,
    WheelIdentity,
)

SelectedTarget = Literal["darwin_arm64_cp314"]
_ROOT_LOCK_PATH = "uv.lock"
_OPERATING_LOCKS = {
    "alpha-research-collector": "packages/collector/uv.lock",
    "alpha-research-execution": "packages/execution/uv.lock",
}
_LOCAL_SOURCES = {
    "alpha-research-collector": {"editable": "."},
    "alpha-research-execution": {"editable": "."},
    "alpha-research-contracts": {"directory": "../contracts"},
}
_REGISTRY_SOURCE = {"registry": "https://pypi.org/simple"}


class DependencyEdge(ImmutableModel):
    """Record one metadata requirement activated for the selected target and extra."""

    parent: str
    parent_extra: str
    requirement: str
    child: str
    child_extras: tuple[str, ...]


class SelectedClosureFacts(ImmutableModel):
    """Serialize the precise closure, policy identity and target admitted for release."""

    schema_version: Literal[1] = 1
    root_name: str
    root_version: str
    target: SelectedTarget
    marker_environment: tuple[tuple[str, str], ...]
    policy_sha256: str
    root_lock_sha256: str
    selected_lock_sha256: str
    review_due_on: date
    wheels: tuple[WheelIdentity, ...]
    edges: tuple[DependencyEdge, ...]


class SelectedClosureAdmission:
    """Bind an operating lock to full admission and prove its actual wheel closure."""

    def __init__(self, repository_root: Path, selected_lock: Path) -> None:
        """Bind the repository and one operating lock for repeated admission checks.

        Args:
            repository_root: Checkout containing the full admitted policy and root lock.
            selected_lock: One collector or execution uv.lock within that checkout.
        """
        self._root = repository_root.resolve(strict=True)
        self._selected_lock = selected_lock.resolve(strict=True)
        try:
            self._selected_relative = self._selected_lock.relative_to(self._root).as_posix()
        except ValueError as error:
            raise DependencyAdmissionError(["selected lock lies outside the repository"]) from error
        if self._selected_relative not in _OPERATING_LOCKS.values():
            raise DependencyAdmissionError(["selected lock is not an operating lock"])

    def admit(
        self,
        root_wheel: Path,
        wheels: Sequence[Path],
        *,
        target: SelectedTarget,
    ) -> SelectedClosureFacts:
        """Verify current full admission and an exact installed wheel graph.

        Args:
            root_wheel: Selected collector or execution wheel in the inventory.
            wheels: Complete wheel inventory to install, including the root wheel.
            target: Explicit supported platform and Python runtime identity.

        Returns:
            Serializable wheel, edge, policy and target facts for a signed release.

        Raises:
            DependencyAdmissionError: Any policy, lock, wheel, graph or target mismatch.
            OSError: Required repository or wheel bytes cannot be read.
        """
        environment = self._target_environment(target)
        policy = DependencyRepository.validate(self._root)
        admitted_digests = dict(policy.lock_digests)
        if self._selected_relative not in admitted_digests:
            raise DependencyAdmissionError(
                ["selected lock is absent from current admission policy"]
            )
        selected_digest = hashlib.sha256(self._selected_lock.read_bytes()).hexdigest()
        if selected_digest != admitted_digests[self._selected_relative]:
            raise DependencyAdmissionError(["selected lock differs from admitted SHA-256 digest"])
        selected = DependencyRepository.locked_packages(self._selected_lock)
        full = DependencyRepository.locked_packages(self._root / _ROOT_LOCK_PATH)
        inventory = self._inventory(root_wheel, wheels)
        root_name = inventory[root_wheel.resolve(strict=True)].name
        if _OPERATING_LOCKS.get(root_name) != self._selected_relative:
            raise DependencyAdmissionError(["root wheel does not match selected operating lock"])
        by_name = {item.name: item for item in inventory.values()}
        self._check_pins(root_name, by_name, selected, full, policy, environment)
        edges = self._resolve(root_name, by_name, selected, environment)
        if len({edge.child for edge in edges} | {root_name}) != len(by_name):
            reached = {edge.child for edge in edges} | {root_name}
            raise DependencyAdmissionError(
                [f"wheel inventory has unexpected packages: {sorted(set(by_name) - reached)}"]
            )
        return SelectedClosureFacts(
            root_name=root_name,
            root_version=by_name[root_name].version,
            target=target,
            marker_environment=tuple(sorted(environment.items())),
            policy_sha256=hashlib.sha256(
                (self._root / "docs/architecture/dependency-admission.toml").read_bytes()
            ).hexdigest(),
            root_lock_sha256=admitted_digests[_ROOT_LOCK_PATH],
            selected_lock_sha256=selected_digest,
            review_due_on=policy.review_due_on,
            wheels=tuple(sorted(by_name.values(), key=self._wheel_sort_key)),
            edges=tuple(sorted(edges, key=self._edge_sort_key)),
        )

    @classmethod
    def verify_retained(
        cls,
        facts: SelectedClosureFacts,
        *,
        root_lock: Path,
        selected_lock: Path,
        policy: DependencyAdmission,
        wheels: Sequence[Path],
    ) -> None:
        """Recheck signed closure facts against retained bytes without a checkout.

        The caller authenticates the policy bytes and their ``facts.policy_sha256``
        before parsing them, and separately verifies retained audit/source evidence.
        This method checks current target and expiry, both lock digests, every wheel
        byte and dependency edge represented by the signed closure.

        Args:
            facts: Authenticated selected closure facts from the release manifest.
            root_lock: Retained admitted root uv.lock file.
            selected_lock: Retained collector or execution uv.lock file.
            policy: Authenticated policy parsed from retained bytes.
            wheels: Complete staged wheel inventory from the release bundle.

        Raises:
            DependencyAdmissionError: Retained bytes, environment or facts drift.
            OSError: A retained input cannot be read.
        """
        facts = SelectedClosureFacts.model_validate(facts)
        policy = DependencyAdmission.model_validate(policy)
        environment = cls._target_environment(facts.target)
        if (
            tuple(sorted(environment.items())) != facts.marker_environment
            or date.today() > policy.review_due_on
            or facts.review_due_on != policy.review_due_on
        ):
            raise DependencyAdmissionError(["retained closure target or policy review expired"])
        lock_path = _OPERATING_LOCKS.get(facts.root_name)
        digests = dict(policy.lock_digests)
        if lock_path is None or lock_path not in digests or _ROOT_LOCK_PATH not in digests:
            raise DependencyAdmissionError(["retained closure lock admission is missing"])
        if (
            hashlib.sha256(root_lock.read_bytes()).hexdigest() != facts.root_lock_sha256
            or facts.root_lock_sha256 != digests[_ROOT_LOCK_PATH]
            or hashlib.sha256(selected_lock.read_bytes()).hexdigest() != facts.selected_lock_sha256
            or facts.selected_lock_sha256 != digests[lock_path]
        ):
            raise DependencyAdmissionError(["retained closure lock digest differs"])
        selected = DependencyRepository.locked_packages(selected_lock)
        full = DependencyRepository.locked_packages(root_lock)
        by_name: dict[str, WheelIdentity] = {}
        for path in wheels:
            identity = WheelArchive.inspect(path)
            if identity.name in by_name:
                raise DependencyAdmissionError([f"duplicate retained wheel {identity.name}"])
            by_name[identity.name] = identity
        if (
            facts.root_name not in by_name
            or by_name[facts.root_name].version != facts.root_version
            or tuple(sorted(by_name.values(), key=cls._wheel_sort_key)) != facts.wheels
        ):
            raise DependencyAdmissionError(["retained wheel inventory differs from signed facts"])
        cls._check_pins(facts.root_name, by_name, selected, full, policy, environment)
        edges = cls._resolve(facts.root_name, by_name, selected, environment)
        reached = {edge.child for edge in edges} | {facts.root_name}
        if reached != set(by_name) or tuple(sorted(edges, key=cls._edge_sort_key)) != facts.edges:
            raise DependencyAdmissionError(["retained dependency graph differs from signed facts"])

    @staticmethod
    def _wheel_sort_key(wheel: WheelIdentity) -> str:
        """Order wheel identities canonically for stable signed facts."""
        return wheel.name

    @staticmethod
    def _edge_sort_key(edge: DependencyEdge) -> tuple[str, str, str, str]:
        """Order active requirement evidence canonically for signed facts."""
        return edge.parent, edge.parent_extra, edge.child, edge.requirement

    @staticmethod
    def _target_environment(target: SelectedTarget) -> dict[str, str]:
        """Require the actual verified host to match the supported release target."""
        if (
            target != "darwin_arm64_cp314"
            or platform.system() != "Darwin"
            or platform.machine() != "arm64"
            or sys.implementation.name != "cpython"
            or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
            != (3, 14, 7)
            or cast(int | None, sysconfig.get_config_var("Py_GIL_DISABLED")) not in {None, 0}
        ):
            raise DependencyAdmissionError(["unsupported or mismatched selected release target"])
        environment: dict[str, str] = {}
        for key, value in default_environment().items():
            if not isinstance(value, str):
                raise DependencyAdmissionError(["selected target marker environment is malformed"])
            environment[key] = value
        return environment

    @staticmethod
    def _inventory(root_wheel: Path, wheels: Sequence[Path]) -> dict[Path, WheelIdentity]:
        """Inspect every supplied archive and reject duplicate identities or filenames."""
        if not wheels:
            raise DependencyAdmissionError(["selected wheel inventory is empty"])
        result: dict[Path, WheelIdentity] = {}
        names: set[str] = set()
        filenames: set[str] = set()
        for wheel in wheels:
            resolved = wheel.resolve(strict=True)
            if resolved in result:
                raise DependencyAdmissionError([f"duplicate wheel path: {wheel}"])
            identity = WheelArchive.inspect(wheel)
            if identity.name in names or identity.filename.casefold() in filenames:
                raise DependencyAdmissionError([f"duplicate wheel identity: {identity.name}"])
            result[resolved] = identity
            names.add(identity.name)
            filenames.add(identity.filename.casefold())
        if root_wheel.resolve(strict=True) not in result:
            raise DependencyAdmissionError(["selected root wheel is absent from inventory"])
        return result

    @classmethod
    def _check_pins(
        cls,
        root_name: str,
        wheels: dict[str, WheelIdentity],
        selected: dict[str, dict[str, object]],
        full: dict[str, dict[str, object]],
        policy: DependencyAdmission,
        environment: dict[str, str],
    ) -> None:
        """Tie every actual wheel to the two locks and full policy admissions."""
        admitted = {item.name: item for item in policy.packages}
        supported_tags = {str(tag) for tag in sys_tags()}
        allowances = {item.name for item in policy.wheel_only_allowances}
        for name, wheel in wheels.items():
            package = selected.get(name)
            if package is None or package.get("version") != wheel.version:
                raise DependencyAdmissionError(
                    [f"{name} is absent or version-drifted in selected lock"]
                )
            if name in allowances:
                raise DependencyAdmissionError(
                    [f"selected closure contains unresolved wheel-only allowance {name}"]
                )
            if not set(wheel.tags) & supported_tags:
                raise DependencyAdmissionError([f"{name} wheel tags do not match selected target"])
            if wheel.requires_python and not SpecifierSet(wheel.requires_python).contains(
                environment["python_full_version"]
            ):
                raise DependencyAdmissionError([f"{name} wheel excludes selected Python version"])
            if name in _LOCAL_SOURCES:
                if name not in {root_name, "alpha-research-contracts"}:
                    raise DependencyAdmissionError([f"{name} is outside selected local closure"])
                if package.get("source") != _LOCAL_SOURCES[name]:
                    raise DependencyAdmissionError([f"{name} local source mapping drifted"])
                cls._check_local_metadata(wheel, package, selected)
                continue
            admission = admitted.get(name)
            full_package = full.get(name)
            if (
                admission is None
                or admission.version != wheel.version
                or full_package is None
                or full_package.get("version") != wheel.version
                or package.get("source") != _REGISTRY_SOURCE
                or full_package.get("source") != _REGISTRY_SOURCE
            ):
                raise DependencyAdmissionError([f"{name} is outside the admitted root graph"])
            selected_url = cls._locked_wheel_url(wheel, package)
            full_url = cls._locked_wheel_url(wheel, full_package)
            if selected_url is None or selected_url != full_url:
                raise DependencyAdmissionError([f"{name} wheel bytes or source differ from locks"])

    @staticmethod
    def _locked_wheel_url(wheel: WheelIdentity, package: dict[str, object]) -> str | None:
        """Find the exact artifact URL pinned to this wheel's filename and bytes."""
        records = package.get("wheels")
        if not isinstance(records, list):
            return None
        for record in cast(list[object], records):
            if not isinstance(record, dict):
                continue
            url, digest = record.get("url"), record.get("hash")
            if (
                isinstance(url, str)
                and isinstance(digest, str)
                and urlsplit(url).path.rsplit("/", 1)[-1] == wheel.filename
                and digest == "sha256:" + wheel.sha256
            ):
                return url
        return None

    @staticmethod
    def _check_local_metadata(
        wheel: WheelIdentity,
        package: dict[str, object],
        selected: dict[str, dict[str, object]],
    ) -> None:
        """Match a local wheel's requirements to its locked project metadata."""
        metadata = package.get("metadata")
        if not isinstance(metadata, dict):
            raise DependencyAdmissionError([f"{wheel.name} has no locked local metadata"])
        locked_metadata = cast(dict[str, object], metadata)
        records: object = locked_metadata.get("requires-dist", [])
        if not isinstance(records, list):
            raise DependencyAdmissionError([f"{wheel.name} has malformed locked requirements"])
        expected: list[tuple[str, str, tuple[str, ...], str]] = []
        for record in cast(list[object], records):
            if not isinstance(record, dict) or not isinstance(record.get("name"), str):
                raise DependencyAdmissionError([f"{wheel.name} has malformed locked requirements"])
            locked_requirement = cast(dict[str, object], record)
            name = cast(str, locked_requirement["name"])
            specifier = locked_requirement.get("specifier", "")
            directory = locked_requirement.get("directory")
            extras: object = locked_requirement.get("extras", [])
            marker = locked_requirement.get("marker", "")
            if (
                not isinstance(specifier, str)
                or not isinstance(marker, str)
                or not isinstance(extras, list)
                or not all(isinstance(extra, str) for extra in extras)
            ):
                raise DependencyAdmissionError([f"{wheel.name} has malformed locked requirements"])
            if directory is not None:
                dependency = selected.get(canonicalize_name(name))
                if (
                    name != "alpha-research-contracts"
                    or directory != "../contracts"
                    or dependency is None
                    or dependency.get("source") != _LOCAL_SOURCES[name]
                    or not isinstance(dependency.get("version"), str)
                ):
                    raise DependencyAdmissionError(
                        [f"{wheel.name} locked local requirement source drifted"]
                    )
                expected_version = cast(str, dependency["version"])
                if specifier and specifier != f"=={expected_version}":
                    raise DependencyAdmissionError(
                        [f"{wheel.name} locked local requirement version drifted"]
                    )
                specifier = f"=={expected_version}"
            expected.append(
                (
                    canonicalize_name(name),
                    str(SpecifierSet(specifier)),
                    tuple(sorted(canonicalize_name(extra) for extra in cast(list[str], extras))),
                    str(Marker(marker)) if marker else "",
                )
            )
        actual = []
        for item in wheel.requires_dist:
            requirement = Requirement(item)
            actual.append(
                (
                    canonicalize_name(requirement.name),
                    str(requirement.specifier),
                    tuple(sorted(canonicalize_name(extra) for extra in requirement.extras)),
                    str(requirement.marker) if requirement.marker else "",
                )
            )
        if sorted(actual) != sorted(expected):
            raise DependencyAdmissionError([f"{wheel.name} METADATA differs from selected lock"])

    @classmethod
    def _resolve(
        cls,
        root_name: str,
        wheels: dict[str, WheelIdentity],
        selected: dict[str, dict[str, object]],
        environment: dict[str, str],
    ) -> set[DependencyEdge]:
        """Traverse activated actual wheel requirements and reconcile locked edges."""
        queue = deque([(root_name, "")])
        visited: set[tuple[str, str]] = set()
        edges: set[DependencyEdge] = set()
        activated: dict[str, set[tuple[str, tuple[str, ...]]]] = {}
        while queue:
            name, parent_extra = queue.popleft()
            if (name, parent_extra) in visited:
                continue
            visited.add((name, parent_extra))
            wheel = wheels[name]
            for text in wheel.requires_dist:
                requirement = Requirement(text)
                marker_env = {**environment, "extra": parent_extra}
                if requirement.marker is not None and not requirement.marker.evaluate(marker_env):
                    continue
                child = canonicalize_name(requirement.name)
                candidate = wheels.get(child)
                if candidate is None:
                    raise DependencyAdmissionError([f"{name} requires missing wheel {child}"])
                if not requirement.specifier.contains(candidate.version):
                    raise DependencyAdmissionError(
                        [f"{name} requires incompatible {child} version"]
                    )
                child_extras = tuple(
                    sorted(canonicalize_name(extra) for extra in requirement.extras)
                )
                if set(child_extras) - set(candidate.provides_extras):
                    raise DependencyAdmissionError([f"{name} requires undeclared {child} extra"])
                edges.add(
                    DependencyEdge(
                        parent=name,
                        parent_extra=parent_extra,
                        requirement=text,
                        child=child,
                        child_extras=child_extras,
                    )
                )
                activated.setdefault(name, set()).add((child, child_extras))
                queue.append((child, ""))
                queue.extend((child, extra) for extra in child_extras)
        for name in {visited_name for visited_name, _ in visited}:
            active_extras = {extra for visited_name, extra in visited if visited_name == name}
            cls._check_lock_edges(
                name, activated.get(name, set()), selected[name], environment, active_extras
            )
        return edges

    @staticmethod
    def _check_lock_edges(
        name: str,
        actual: set[tuple[str, tuple[str, ...]]],
        package: dict[str, object],
        environment: dict[str, str],
        active_extras: set[str],
    ) -> None:
        """Require selected-lock edges to describe the same active package set."""
        records = package.get("dependencies", [])
        if not isinstance(records, list):
            raise DependencyAdmissionError([f"{name} lock dependency edges are malformed"])
        expected: set[tuple[str, tuple[str, ...]]] = set()
        for record in cast(list[object], records):
            if not isinstance(record, dict) or not isinstance(record.get("name"), str):
                raise DependencyAdmissionError([f"{name} lock dependency edges are malformed"])
            marker = record.get("marker")
            if marker is not None:
                if not isinstance(marker, str):
                    raise DependencyAdmissionError([f"{name} lock dependency marker is malformed"])
                if not any(
                    Marker(marker).evaluate({**environment, "extra": extra})
                    for extra in active_extras
                ):
                    continue
            extras: object = record.get("extra", [])
            if not isinstance(extras, list) or not all(isinstance(extra, str) for extra in extras):
                raise DependencyAdmissionError([f"{name} lock dependency extras are malformed"])
            expected.add(
                (
                    canonicalize_name(cast(str, record["name"])),
                    tuple(sorted(canonicalize_name(extra) for extra in cast(list[str], extras))),
                )
            )
        if actual != expected:
            raise DependencyAdmissionError(
                [
                    f"{name} actual and selected-lock dependency edges differ: "
                    f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
                ]
            )
