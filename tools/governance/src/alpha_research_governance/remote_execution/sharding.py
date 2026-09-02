"""Deterministic, order-independent whole-target sharding."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from alpha_research_governance.remote_execution.models import RemoteExecutionError, TestShard

_BAZEL_LABEL = re.compile(r"^//(?:[^\s:]+(?::[^\s:]+)?|:[^\s:]+)$")


def shard_targets(
    targets: Iterable[str],
    *,
    shard_count: int,
    seed: str,
    maximum_targets: int,
) -> tuple[TestShard, ...]:
    """Partition unique Bazel labels using a stable SHA-256 seeded modulo."""
    if shard_count < 1:
        raise RemoteExecutionError(["shard_count must be positive"])
    if maximum_targets < 1:
        raise RemoteExecutionError(["maximum_targets must be positive"])
    if not seed or len(seed) > 128:
        raise RemoteExecutionError(["seed must contain between 1 and 128 characters"])

    normalized = tuple(sorted(targets))
    findings: list[str] = []
    if len(normalized) != len(set(normalized)):
        findings.append("test targets must be unique")
    if len(normalized) > maximum_targets:
        findings.append(
            f"test target count {len(normalized)} exceeds the {maximum_targets}-target budget"
        )
    invalid = tuple(target for target in normalized if _BAZEL_LABEL.fullmatch(target) is None)
    if invalid:
        findings.append(f"invalid Bazel test labels: {invalid!r}")
    if findings:
        raise RemoteExecutionError(findings)

    assignments: list[list[str]] = [[] for _ in range(shard_count)]
    for target in normalized:
        digest = hashlib.sha256(f"{seed}\0{target}".encode()).digest()
        assignments[int.from_bytes(digest[:8], "big") % shard_count].append(target)
    return tuple(
        TestShard(index=index, count=shard_count, targets=tuple(assigned))
        for index, assigned in enumerate(assignments)
    )


def select_shard(
    targets: Iterable[str],
    *,
    shard_index: int,
    shard_count: int,
    seed: str,
    maximum_targets: int,
) -> TestShard:
    """Return one validated shard without weakening the complete partition."""
    if shard_index < 0 or shard_index >= shard_count:
        raise RemoteExecutionError(
            [f"shard_index must be in the half-open range [0, {shard_count})"]
        )
    return shard_targets(
        targets,
        shard_count=shard_count,
        seed=seed,
        maximum_targets=maximum_targets,
    )[shard_index]
