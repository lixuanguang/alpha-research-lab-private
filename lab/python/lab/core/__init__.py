"""lab.core — configuration, registry, logging, path helpers."""

from lab.core.config import (
    ConfigValidationError,
    ExperimentConfig,
    load_config,
    load_raw_config,
    normalize_config,
    validate_config,
    validate_macro_allocator_config,
)
from lab.core.logging import get_logger, setup_logging
from lab.core.paths import (
    data_dir,
    experiments_dir,
    lab_root,
    latest_run_dir,
    run_dir,
    runs_root,
)
from lab.core.registry import (
    compute_config_hash,
    compute_results_hash,
    compute_stable_frame_hash,
    compute_stable_series_hash,
    create_run,
    generate_run_id,
    get_git_commit,
)
from lab.core.strategy_registry import get, list_strategies, register

__all__ = [
    # config
    "ConfigValidationError",
    "ExperimentConfig",
    # registry (run identity)
    "compute_config_hash",
    "compute_results_hash",
    "compute_stable_frame_hash",
    "compute_stable_series_hash",
    "create_run",
    # paths
    "data_dir",
    "experiments_dir",
    "generate_run_id",
    # strategy registry
    "get",
    "get_git_commit",
    # logging
    "get_logger",
    "lab_root",
    "latest_run_dir",
    "list_strategies",
    "load_config",
    "load_raw_config",
    "normalize_config",
    "register",
    "run_dir",
    "runs_root",
    "setup_logging",
    "validate_config",
    "validate_macro_allocator_config",
]
