"""Compare retained economic features with scheduled batch execution and restored state."""

from __future__ import annotations

# standard library imports
import hashlib

# project library imports
from market_data.query import QueryReader
from market_data.replay import Replay
from research.features import (
    ScheduledFeatureCheckpoint,
    ScheduledFeatureParity,
    ScheduledFeatures,
    ScheduledFeatureSpec,
    ScheduledFeatureValue,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import EconomicResult


def qualify_scheduled_features(
    reader: QueryReader,
    reference: EconomicResult,
    *,
    batch_size: int = 256,
) -> ScheduledFeatureParity:
    """Compare every saved replay close with uninterrupted and reload-only batch features.

    Args:
        reader: Verified pinned input used by the retained economic reference.
        reference: Complete historical replay result; no candidate or source acceptance implied.
        batch_size: Positive delivery bound, independent of output identity.

    Returns:
        Full versioned traces and the first divergence, if any. A caller must inspect
        is_equal before treating the record as software parity evidence. Models and online
        retrieval are inapplicable to this unfitted completed-price feature.

    Raises:
        ValueError: Reference, input cursor, supported scope or state compatibility fails.
    """
    codec = DomainCodec()
    reference = codec.decode_json(codec.encode_json(reference), EconomicResult)
    spec = reference.spec
    Replay(
        reader,
        (spec.binding[2],),
        start=spec.start,
        end=spec.end,
        terminal=spec.end,
        config_identity=spec.identity,
        batch_size=batch_size,
        cursor=reference.checkpoint.cursor,
    )
    definition = ScheduledFeatureSpec(
        instance=spec.instance,
        binding=spec.binding,
        tick=spec.limits.tick,
        start=spec.start,
        end=spec.end,
        cadence_seconds=spec.cadence_seconds,
        max_age_seconds=spec.max_age_seconds,
    )
    batch = ScheduledFeatures(reader, definition, batch_size=batch_size)
    restarted = ScheduledFeatures(reader, definition, batch_size=batch_size)
    replay_values: list[ScheduledFeatureValue] = []
    for event in reference.checkpoint.state.trace:
        if event.phase != "decision":
            continue
        if event.observation is None:
            raise ValueError("economic decision lacks its completed observation")
        replay_values.append(
            ScheduledFeatureValue(
                observation=event.observation,
                value=event.return_ratio,
                has_current_gap=any(
                    known == event.at for _, known in reference.checkpoint.state.observations.gaps
                ),
            )
        )
        batch.evaluate(event.at)
        # Restore only serialized public state before each decision, including warm-up.
        restored = codec.decode_json(
            codec.encode_json(restarted.checkpoint), ScheduledFeatureCheckpoint
        )
        restarted = ScheduledFeatures(
            reader, definition, checkpoint=restored, batch_size=batch_size
        )
        restarted.evaluate(event.at)
    values = tuple(replay_values)
    return ScheduledFeatureParity(
        reference_sha256=hashlib.sha256(codec.encode_json(reference)).hexdigest(),
        implementation_sha256=ImplementationIdentity.sha256(),
        replay=ScheduledFeatureCheckpoint(
            definition=definition,
            input_identity=reader.identity,
            values=values,
            values_sha256=hashlib.sha256(codec.encode_json(values)).hexdigest(),
        ),
        batch=batch.checkpoint,
        restarted=restarted.checkpoint,
        limitations=(
            "Saved-input batch parity only; "
            "no live input, timing budget or online store qualification",
            "Unfitted completed-price feature; model prediction parity is inapplicable",
            *reference.limitations,
        ),
    )
