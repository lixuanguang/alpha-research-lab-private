"""Unit tests for ArtifactStore abstraction and FilesystemArtifactStore (LA-009)."""

from __future__ import annotations

from pathlib import Path

import pytest

import alpha_core.research.artifact_paths as artifact_paths
from alpha_core.research.artifact_store import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    ArtifactStore,
    FilesystemArtifactStore,
)

RUN_ID = "run_abc123"
KEY = "features.parquet"
DATA = b"fake-parquet-bytes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store(tmp_path: Path) -> FilesystemArtifactStore:
    return FilesystemArtifactStore(tmp_path)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_filesystem_store_satisfies_protocol(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        assert isinstance(store, ArtifactStore)


# ---------------------------------------------------------------------------
# put / get / exists / list — happy paths
# ---------------------------------------------------------------------------


class TestPutGetExistsList:
    def test_put_then_get_roundtrip(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        assert store.get(RUN_ID, KEY) == DATA

    def test_exists_true_after_put(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        assert not store.exists(RUN_ID, KEY)
        store.put(RUN_ID, KEY, DATA)
        assert store.exists(RUN_ID, KEY)

    def test_list_empty_before_any_puts(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        assert store.list(RUN_ID) == []

    def test_list_returns_keys_after_multiple_puts(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, "features.parquet", b"a")
        store.put(RUN_ID, "metrics.json", b"b")
        keys = store.list(RUN_ID)
        assert "features.parquet" in keys
        assert "metrics.json" in keys
        assert keys == sorted(keys)

    def test_list_isolates_by_run_id(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put("run_a", KEY, b"a")
        store.put("run_b", KEY, b"b")
        assert store.list("run_a") == [KEY]
        assert store.list("run_b") == [KEY]

    def test_put_creates_subdirectory_keys(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        nested_key = "sub/dir/data.json"
        store.put(RUN_ID, nested_key, b"nested")
        assert store.exists(RUN_ID, nested_key)
        assert store.get(RUN_ID, nested_key) == b"nested"

    def test_list_includes_nested_keys(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, "a/b/c.json", b"x")
        keys = store.list(RUN_ID)
        assert keys == ["a/b/c.json"]


# ---------------------------------------------------------------------------
# Idempotency / overwrite semantics
# ---------------------------------------------------------------------------


class TestIdempotencyAndOverwrite:
    def test_put_raises_on_duplicate_key_by_default(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        with pytest.raises(ArtifactExistsError, match=KEY):
            store.put(RUN_ID, KEY, b"different")

    def test_put_with_overwrite_true_replaces_artifact(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        new_data = b"replacement"
        store.put(RUN_ID, KEY, new_data, overwrite=True)
        assert store.get(RUN_ID, KEY) == new_data

    def test_put_is_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        """No .tmp file should remain after a successful put."""
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        stage_outputs = artifact_paths.stage_outputs_path(tmp_path, RUN_ID)
        tmp_files = list(stage_outputs.rglob("*.tmp"))
        assert tmp_files == [], f"left-over .tmp files: {tmp_files}"

    def test_prepare_path_raises_on_existing_key(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        with pytest.raises(ArtifactExistsError, match=KEY):
            store.prepare_path(RUN_ID, KEY)

    def test_prepare_path_overwrite_true_returns_path(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        path = store.prepare_path(RUN_ID, KEY, overwrite=True)
        assert path.parent.exists()
        assert isinstance(path, Path)

    def test_prepare_path_creates_parent_dirs(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        path = store.prepare_path(RUN_ID, "sub/nested.json")
        assert path.parent.exists()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_get_raises_artifact_not_found(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="missing.parquet"):
            store.get(RUN_ID, "missing.parquet")

    def test_path_for_raises_artifact_not_found(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="missing.json"):
            store.path_for(RUN_ID, "missing.json")

    def test_path_for_returns_path_when_exists(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        path = store.path_for(RUN_ID, KEY)
        assert path.exists()
        assert path.read_bytes() == DATA


# ---------------------------------------------------------------------------
# Path layout contract — backward compatibility
# ---------------------------------------------------------------------------


class TestPathLayout:
    def test_resolves_to_canonical_artifact_key_path(self, tmp_path: Path) -> None:
        """Store must use the same path as artifact_key_path so existing artifacts
        remain readable without migration."""
        store = make_store(tmp_path)
        store.put(RUN_ID, KEY, DATA)
        expected = artifact_paths.artifact_key_path(tmp_path, RUN_ID, KEY)
        assert expected.exists()
        assert expected.read_bytes() == DATA

    def test_storage_root_property(self, tmp_path: Path) -> None:
        store = make_store(tmp_path)
        assert store.storage_root == tmp_path
