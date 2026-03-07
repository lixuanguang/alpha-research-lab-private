"""Unit tests for alpha_core.research.feature_runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.research.feature_runner as feature_runner_mod


def test_resolve_factor_pack_chain_honors_expected_version(tmp_path: Path) -> None:
    packs_dir = tmp_path / "config" / "research" / "factor_packs"
    packs_dir.mkdir(parents=True)
    factor_pack_mod.save_factor_pack(
        factor_pack_mod.FactorPackManifest(pack_id="momentum", version="1.0.0"),
        packs_dir / "momentum_v1.yaml",
    )
    factor_pack_mod.save_factor_pack(
        factor_pack_mod.FactorPackManifest(pack_id="momentum", version="2.0.0"),
        packs_dir / "momentum_v2.yaml",
    )

    with patch(
        "alpha_core.research.feature_runner.config_paths.find_project_root",
        return_value=tmp_path,
    ):
        chain = feature_runner_mod.resolve_factor_pack_chain(
            "momentum",
            expected_version="1.0.0",
        )

    assert [(pack.pack_id, pack.version) for pack in chain] == [("momentum", "1.0.0")]
