"""YAML and merge helpers for layered configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML mapping from path, returning empty mapping when file is missing/empty."""
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a YAML object at {path}, got {type(loaded).__name__}")
    return loaded


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings and named mapping lists."""
    merged = dict(base)
    for key, value in incoming.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = deep_merge(base_value, value)
        elif isinstance(base_value, list) and isinstance(value, list):
            merged[key] = merge_list_values(base_value, value)
        else:
            merged[key] = value
    return merged


def named_mapping_list(
    entries: list[Any],
    *,
    context: str,
) -> tuple[dict[str, dict[str, Any]], list[str]] | None:
    """Return `({name->entry}, order)` for lists of `{\"name\": ...}` mappings."""
    by_name: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name = entry.get("name")
        if not isinstance(name, str):
            return None
        if name in by_name:
            raise ValueError(f"Duplicate named entry `{name}` in {context}")
        by_name[name] = entry
        order.append(name)

    return by_name, order


def merge_list_values(base: list[Any], incoming: list[Any]) -> list[Any]:
    """Merge list overlays by `name` when both sides are named mapping lists."""
    base_named = named_mapping_list(base, context="base list")
    incoming_named = named_mapping_list(incoming, context="incoming list")
    if base_named is None or incoming_named is None:
        return incoming

    base_by_name, merged_order = base_named
    incoming_by_name, incoming_order = incoming_named
    merged_by_name = dict(base_by_name)

    for name in incoming_order:
        incoming_item = incoming_by_name[name]
        if name in merged_by_name:
            merged_by_name[name] = deep_merge(merged_by_name[name], incoming_item)
            continue

        merged_by_name[name] = incoming_item
        merged_order.append(name)

    return [merged_by_name[name] for name in merged_order]


def resolve_list_index(container: list[Any], key: str) -> int:
    """Resolve list selector by numeric index or entry `name` value."""
    if key.isdigit():
        index = int(key)
        if index < 0 or index >= len(container):
            raise IndexError(f"List override index out of range: {index}")
        return index

    for index, item in enumerate(container):
        if isinstance(item, dict) and item.get("name") == key:
            return index

    raise ValueError(
        f"List overrides must use numeric indices or existing `name` values, got `{key}`"
    )


def set_nested_value(target: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set nested mapping/list path, validating container structure along the way."""
    cursor: Any = target
    for key in keys[:-1]:
        if isinstance(cursor, dict):
            if key not in cursor:
                cursor[key] = {}
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            cursor = cursor[resolve_list_index(cursor, key)]
            continue

        raise TypeError(
            f"Cannot set nested override under non-container type: {type(cursor).__name__}"
        )

    last_key = keys[-1]
    if isinstance(cursor, dict):
        cursor[last_key] = value
        return

    if isinstance(cursor, list):
        cursor[resolve_list_index(cursor, last_key)] = value
        return

    raise TypeError(f"Cannot set nested override under non-container type: {type(cursor).__name__}")


def path_exists(config: dict[str, Any], keys: list[str]) -> bool:
    """Return True when mapping/list path exists in config payload."""
    cursor: Any = config
    for key in keys:
        if isinstance(cursor, dict):
            if key not in cursor:
                return False
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            if key.isdigit():
                index = int(key)
                if index < 0 or index >= len(cursor):
                    return False
                cursor = cursor[index]
                continue

            named_item = next(
                (item for item in cursor if isinstance(item, dict) and item.get("name") == key),
                None,
            )
            if named_item is None:
                return False
            cursor = named_item
            continue

        return False

    return True


__all__ = [
    "deep_merge",
    "load_yaml",
    "path_exists",
    "set_nested_value",
]
