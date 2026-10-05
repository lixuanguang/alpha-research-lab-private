"""Materialize a feature version's stream: compute, publish to Feast, verify, then append."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from pathlib import Path

# project library imports
from research.features.contracts import FeatureKernel, FeatureSession
from research.features.fitting import FittedTransform, TransformVersion
from research.features.serving import FeastServingBridge, FeastServingSnapshot
from research.features.store import (
    FeatureMaterialization,
    FeatureStoreDefinition,
    StoredFeature,
    VersionedFeatureStore,
)
from research.observations import DecisionSource
from serialization import DomainCodec


class FeatureMaterializer:
    """Extend one feature version's stream from a causal source, Feast-verified first.

    Research jobs and the signed paper feature publisher share this one path, so a
    served stream is built exactly as an offline one.
    """

    def materialize(
        self,
        store: VersionedFeatureStore,
        definition: FeatureStoreDefinition,
        *,
        source: DecisionSource,
        kernel: FeatureKernel,
        instance: str,
        entities: tuple[str, ...],
        decisions: tuple[datetime, ...],
        source_version: str,
        source_sha256: str,
        dataset_version: str,
        dataset_sha256: str,
        version: str,
        bridge: FeastServingBridge,
        serving_root: Path,
        transform: FittedTransform | None = None,
        transform_version: TransformVersion | None = None,
    ) -> FeatureMaterialization:
        """Commit each vector with its successor state, then publish and activate verified Feast.

        The caller supplies admitted immutable source/dataset identities. Every row
        retains the source's actual input lineage. A retry resumes committed cutoffs.
        The snapshot at the last decision is prepared, its Feast generation published
        and read back, and only then appended, so a reader of the version's stream
        never finds a snapshot without its generation. Calling again with the same
        version and later decisions extends that stream; an interrupted publication
        leaves the preceding snapshot and active version intact.
        A fitted definition (one with ``transform_identity``) is materialized with
        the study's ``FittedTransform`` and its retained ``TransformVersion``: each raw
        vector is transformed with that state, never refitted, and stored under the
        definition's output fields. A decision before the version's availability is
        refused by the transform itself.
        """
        if (
            not entities
            or len(set(entities)) != len(entities)
            or not decisions
            or tuple(sorted(set(decisions))) != decisions
            or kernel.schema != definition.schema
            or (definition.transform_identity is None) != (transform_version is None)
            or (transform is None) != (transform_version is None)
            or (
                transform is not None
                and transform_version is not None
                and (
                    definition.transform_identity != transform_version.identity
                    or definition.output_fields != transform_version.output_fields
                    or transform.identity != transform_version.implementation
                )
            )
            or (definition.schema.mode == "incremental" and definition.instance != instance)
            or source.requirements != kernel.schema.inputs
            or source_version != source.identity
        ):
            raise ValueError(
                "materialization requires matching source/schema and ordered unique scope"
            )
        store.register(definition)
        expected_active = store.active_version(definition)
        codec = DomainCodec()
        for entity in entities:
            checkpoint = store.get_checkpoint(
                definition,
                instance,
                entity,
                source_version=source_version,
                source_sha256=source_sha256,
                dataset_version=dataset_version,
                dataset_sha256=dataset_sha256,
            )
            session = FeatureSession(
                kernel, instance=instance, entity=entity, checkpoint=checkpoint
            )
            for at in decisions:
                if (
                    checkpoint is not None
                    and checkpoint.last_at is not None
                    and at <= checkpoint.last_at
                ):
                    continue
                vector = session.evaluate(source.read(entity, at))
                if transform is not None and transform_version is not None:
                    vector = transform.apply(transform_version, vector)
                row = StoredFeature(
                    definition_identity=definition.identity,
                    vector=vector,
                    source_version=source_version,
                    source_sha256=source_sha256,
                    dataset_version=dataset_version,
                    dataset_sha256=dataset_sha256,
                    revision_identity=hashlib.sha256(
                        codec.encode_json((vector.identity, source_version, dataset_version))
                    ).hexdigest(),
                )
                store.append(definition, row, checkpoint=session.checkpoint())
        prepared = store.prepare(definition, version, decisions[-1], entities)
        snapshot = FeastServingSnapshot.from_materialization(prepared)
        generation = bridge.materialize(snapshot, serving_root)
        for entity in entities:
            bridge.retrieve(snapshot, generation, entity, decisions[-1])
        materialization = store.materialize(
            definition, version, decisions[-1], entities, expected_identity=prepared.identity
        )
        store.activate_if_current(definition, version, expected_active)
        return materialization
