"""Inspect retained features reactively; create a formal factor attempt only on explicit action."""

# third party library imports
import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def imports():
    """Load installed public research APIs for the notebook cells."""
    # standard library imports
    import os
    from pathlib import Path

    # third party library imports
    import marimo as mo

    # project library imports
    from applications.explore import compare_factors, compare_windows
    from research.experiments import AttemptStore
    from research.studies import AlphalensStudy
    from research.studies import ClearMLDestination
    from research.studies import WindowDiagnosticStudy
    from research.exploration import (
        AnalysisQuery,
        BoundedFeatureAnalysis,
        FeatureStudy,
        VerifiedFeatureRows,
    )
    from serialization import DomainCodec

    return (
        os,
        Path,
        mo,
        compare_factors,
        compare_windows,
        WindowDiagnosticStudy,
        AlphalensStudy,
        AttemptStore,
        ClearMLDestination,
        AnalysisQuery,
        BoundedFeatureAnalysis,
        FeatureStudy,
        VerifiedFeatureRows,
        DomainCodec,
    )


@app.cell
def source(
    os,
    Path,
    mo,
    AlphalensStudy,
    AttemptStore,
    ClearMLDestination,
    FeatureStudy,
    VerifiedFeatureRows,
    DomainCodec,
):
    """Verify the explicitly selected validation source before display or execution."""
    directory = os.environ.get("ALPHA_COMPARISON_DIRECTORY")
    mo.stop(not directory, mo.md("Select a retained study with `ALPHA_COMPARISON_DIRECTORY`."))
    root = Path(directory).resolve()
    source_attempt = os.environ["ALPHA_COMPARISON_SOURCE_ATTEMPT"]
    source_digest = os.environ["ALPHA_COMPARISON_SOURCE_SHA256"]
    codec = DomainCodec()
    feature_study = codec.decode_json((root / "study.json").read_bytes(), FeatureStudy)
    factor_study = codec.decode_json((root / "factor-study.json").read_bytes(), AlphalensStudy)
    tracking = codec.decode_json((root / "tracking.json").read_bytes(), ClearMLDestination)
    if feature_study.partition != "validation":
        raise ValueError("The preview requires a validation feature study")
    history = AttemptStore(root / "attempts").read(source_attempt)
    if history.status != "completed" or not history.events or history.events[-1].result is None:
        raise ValueError("Select a completed retained feature attempt")
    payload = history.events[-1].result
    verified = VerifiedFeatureRows.from_result(payload, source_digest, ttl_us=60_000_000)
    if factor_study.known_at is None or factor_study.known_at >= feature_study.split.holdout.start:
        raise ValueError("This example requires an explicit validation-only observation cutoff")
    if any(not feature_study.split.validation.contains(row.decision_at) for row in verified.rows):
        raise ValueError("Preview cannot inspect a holdout or a different partition")
    return (
        root,
        source_attempt,
        source_digest,
        codec,
        feature_study,
        factor_study,
        tracking,
        verified,
    )


@app.cell
def controls(mo):
    """Expose bounded display controls and a separate formal run action."""
    limit = mo.ui.slider(1, 100, value=20, label="Rows to display")
    run = mo.ui.run_button(label="Run and retain factor diagnostics")
    mo.vstack(
        [
            mo.md(
                "# Compare retained features\n"
                "Inspect exact feature values and missing observations. "
                "A formal run retains factor diagnostics and publishes them to ClearML."
            ),
            limit,
            run,
        ]
    )
    return limit, run


@app.cell
def preview(mo, limit, verified, AnalysisQuery, BoundedFeatureAnalysis):
    """Compare exact conversions without creating a retained attempt."""
    analysis = BoundedFeatureAnalysis().compare(verified, AnalysisQuery(max_rows=limit.value))
    if not analysis.exact:
        raise ValueError("Dataframe conversions differ from the retained reference")
    mo.ui.table(
        [
            {
                "entity": row.entity_key,
                "decision": row.decision_at.isoformat(),
                "value": row.value,
                "units": row.units,
                "missing": row.missing_reason,
            }
            for row in analysis.polars.rows
        ]
    )
    return (analysis,)


@app.cell
def formal(
    mo,
    os,
    run,
    root,
    source_attempt,
    source_digest,
    feature_study,
    factor_study,
    tracking,
    compare_factors,
):
    """Retain a factor report only after the explicit run action."""
    # Display controls are intentionally absent from this cell's dependencies.
    # The environment switch is an explicit fresh-process action, not a UI default.
    mo.stop(not (run.value or os.environ.get("ALPHA_COMPARISON_RUN") == "1"))
    formal_attempt = compare_factors(
        factor_study,
        family=feature_study.family,
        source_attempt=source_attempt,
        source_sha256=source_digest,
        split=feature_study.split,
        attempts=root / "attempts",
        tracking=tracking,
    )
    mo.md(f"Retained attempt `{formal_attempt.start.attempt_id}`: {formal_attempt.status}.")
    return (formal_attempt,)


@app.cell
def window_controls(mo, os, Path, DomainCodec, WindowDiagnosticStudy, ClearMLDestination):
    """Preview a frozen window request without calculating or creating an attempt."""
    window_directory = os.environ.get("ALPHA_WINDOW_DIRECTORY")
    mo.stop(
        not window_directory,
        mo.md("Select saved window diagnostics with `ALPHA_WINDOW_DIRECTORY`."),
    )
    window_root = Path(window_directory).resolve()
    window_codec = DomainCodec()
    window_study = window_codec.decode_json(
        (window_root / "window-study.json").read_bytes(), WindowDiagnosticStudy
    )
    window_tracking = window_codec.decode_json(
        (window_root / "tracking.json").read_bytes(), ClearMLDestination
    )
    run_windows = mo.ui.run_button(label="Run and retain window diagnostics")
    mo.vstack(
        [
            mo.md(
                "## Reference/current diagnostics\n"
                f"Reference: `{window_study.reference}`\n\nCurrent: `{window_study.current}`\n\n"
                f"Label cutoff: `{window_study.evaluated_as_of}`. "
                "The saved request freezes sources, split, applicability and thresholds. "
                "Running creates a retained report and publishes it to ClearML. "
                "Drift never triggers retraining or promotion."
            ),
            run_windows,
        ]
    )
    return window_root, window_study, window_tracking, run_windows


@app.cell
def window_report(mo, os, window_root, window_study, window_tracking, run_windows, compare_windows):
    """Run saved-window diagnostics only after an explicit user or fresh-process action."""
    mo.stop(not (run_windows.value or os.environ.get("ALPHA_WINDOW_RUN") == "1"))
    window_attempt = compare_windows(
        window_study, attempts=window_root / "attempts", tracking=window_tracking
    )
    mo.md(f"Window report attempt `{window_attempt.start.attempt_id}`: {window_attempt.status}.")
    return (window_attempt,)


if __name__ == "__main__":
    app.run()
