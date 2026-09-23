"""Run bounded DuckDB and Polars views over verified causal feature records."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from research.features import FeatureObservation, OfflineFeatureRequest
from research.results import FeatureStudyResult
from serialization import DomainCodec, WireRecord

if TYPE_CHECKING:
    # third party library imports
    import polars as pl

_MAX_ROWS = 4_096
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class AnalysisQuery(WireRecord, frozen=True, kw_only=True):
    """Declare the only filters supported by the bounded analysis adapters."""

    schema_version: Literal["bounded-analysis-query-v1"] = "bounded-analysis-query-v1"
    entity_type: str | None = None
    entity_key: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    include_missing: bool = True
    max_rows: int = 1_024

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        """Require one nonempty, trimmed analysis text field."""
        if type(value) is not str or not value or value != value.strip():
            raise ValueError(f"{field_name} must be a nonempty trimmed string")
        return value

    @classmethod
    def _digest(cls, value: object, field_name: str) -> str:
        """Require one lowercase SHA-256 digest in analysis metadata."""
        result = cls._text(value, field_name)
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return result

    @staticmethod
    def _time_us(value: datetime) -> int:
        """Encode an aware UTC datetime as exact integer microseconds."""
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise TypeError("analysis timestamps must be aware UTC datetimes")
        delta = value - _EPOCH
        return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds

    def __post_init__(self) -> None:
        """Reject unbounded intervals, naive clocks and arbitrary SQL inputs."""
        if self.schema_version != "bounded-analysis-query-v1":
            raise ValueError("unsupported bounded analysis query schema")
        if self.entity_type is not None:
            self._text(self.entity_type, "entity_type")
        if self.entity_key is not None:
            self._text(self.entity_key, "entity_key")
        if (self.start is None) != (self.end is None):
            raise ValueError("analysis start and end must be supplied together")
        if self.start is not None and self.end is not None:
            if type(self.start) is not datetime or type(self.end) is not datetime:
                raise TypeError("analysis interval requires datetime values")
            if self.start.tzinfo is None or self.end.tzinfo is None:
                raise TypeError("analysis interval requires timezone-aware values")
            if self.start.utcoffset() != timedelta(0) or self.end.utcoffset() != timedelta(0):
                raise ValueError("analysis interval must use UTC")
            if self.end <= self.start:
                raise ValueError("analysis interval must be increasing")
        if type(self.include_missing) is not bool:
            raise TypeError("include_missing must be bool")
        if type(self.max_rows) is not int or not 1 <= self.max_rows <= 1_024:
            raise ValueError("analysis max_rows must be between 1 and 1024")

    @property
    def identity(self) -> str:
        """Return the stable query identity used by retained comparison output.

        Returns:
            Lowercase SHA-256 identity for the fixed query filters and bounds.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class VerifiedFeatureRows:
    """Validate one immutable feature source before it enters either columnar backend."""

    @classmethod
    def from_result(
        cls,
        payload: bytes,
        expected_sha256: str,
        *,
        ttl_us: int,
        feature_name: str = "trailing_return",
        entity_type: str = "instrument",
    ) -> VerifiedFeatureRows:
        """Convert a verified MR3 feature result into retained analysis observations.

        Args:
            payload: Complete ``feature-study-result-v1`` bytes from the causal reader.
            expected_sha256: Digest of the exact retained result bytes.
            ttl_us: Explicit positive feature TTL in microseconds.
            feature_name: Stable name assigned to the projected feature column.
            entity_type: Stable entity type assigned to each projected binding.

        Returns:
            Validated observations retaining source, decision, event and availability clocks.

        Raises:
            ValueError: The digest, payload, feature clocks or exact values are invalid.
        """
        if type(payload) is not bytes or not payload:
            raise ValueError("feature result requires nonempty bytes")
        if (
            AnalysisQuery._digest(expected_sha256, "expected_sha256")
            != hashlib.sha256(payload).hexdigest()
        ):
            raise ValueError("feature result bytes differ from expected source digest")
        AnalysisQuery._text(feature_name, "feature_name")
        AnalysisQuery._text(entity_type, "entity_type")
        try:
            source = FeatureStudyResult.decode(payload)
        except (TypeError, ValueError) as error:
            raise ValueError("feature result does not match the retained MR3 contract") from error
        if type(ttl_us) is not int or not 0 < ttl_us <= 31_536_000_000_000:
            raise ValueError("feature result TTL is outside the bounded analysis contract")
        rows: list[FeatureObservation] = []
        for _, feature in source.features:
            binding = feature.window.binding
            if type(binding) is not tuple or len(binding) != 3:
                raise ValueError("feature result binding lacks an entity key")
            try:
                entity_key = DomainCodec().encode_json(binding).decode("utf-8")
            except (TypeError, ValueError) as error:
                raise ValueError("feature result binding cannot be retained as JSON") from error
            event_at: datetime | None = feature.decision_at
            available_at: datetime | None = feature.available_at
            revision_identity: str | None = None
            value: str | None = None
            missing_reason: str | None = feature.window.missing or "feature value is null"
            points = feature.window.points
            if points:
                revision_identity = points[-1].identity
                if (
                    type(revision_identity) is not str
                    or len(revision_identity) != 64
                    or any(character not in "0123456789abcdef" for character in revision_identity)
                ):
                    raise ValueError("feature result lacks a canonical source revision identity")
            if feature.value is not None:
                value = f"{feature.value.numerator}/{feature.value.denominator}"
                missing_reason = None
            rows.append(
                FeatureObservation(
                    definition_identity=feature.definition_identity,
                    source_version=source.selection_identity,
                    source_sha256=expected_sha256,
                    feature_name=feature_name,
                    entity_type=entity_type,
                    entity_key=entity_key,
                    decision_at=feature.decision_at,
                    event_at=event_at,
                    available_at=available_at,
                    ttl_us=ttl_us,
                    units=source.feature_definition.units,
                    value=value,
                    revision_identity=revision_identity,
                    missing_reason=missing_reason,
                )
            )
        return cls(tuple(rows))

    def __init__(self, rows: Sequence[FeatureObservation]) -> None:
        """Copy and validate a bounded set of rows without coercing any value.

        Args:
            rows: Tuple or list of observations from one retained source snapshot.

        Raises:
            TypeError: The collection or one row has an unsupported type.
            ValueError: Rows exceed the bound, duplicate a key or mix source bindings.
        """
        if type(rows) not in (tuple, list):
            raise TypeError("verified feature rows must be a tuple or list")
        if not rows or len(rows) > _MAX_ROWS:
            raise ValueError("verified feature rows must contain 1 to 4096 rows")
        copied = tuple(rows)
        identities: set[str] = set()
        for row in copied:
            if type(row) is not FeatureObservation:
                raise TypeError("verified feature rows require FeatureObservation records")
            row.__post_init__()
            if row.row_identity in identities:
                raise ValueError("verified feature rows must have unique entity/decision keys")
            identities.add(row.row_identity)
        first = copied[0]
        for row in copied[1:]:
            if (
                row.definition_identity != first.definition_identity
                or row.source_version != first.source_version
                or row.source_sha256 != first.source_sha256
                or row.feature_name != first.feature_name
                or row.units != first.units
                or row.ttl_us != first.ttl_us
            ):
                raise ValueError(
                    "verified feature rows mix immutable source or definition bindings"
                )
        self._rows = copied
        self._source_identity = hashlib.sha256(
            DomainCodec().encode_json(
                (
                    first.definition_identity,
                    first.source_version,
                    first.source_sha256,
                    first.feature_name,
                    tuple(row.row_identity for row in copied),
                )
            )
        ).hexdigest()

    @property
    def rows(self) -> tuple[FeatureObservation, ...]:
        """Return the immutable source rows in caller-authored order.

        Returns:
            Tuple of validated observations.
        """
        return self._rows

    @property
    def source_identity(self) -> str:
        """Return the identity of the verified source projection.

        Returns:
            Lowercase SHA-256 identity for the source binding and row keys.
        """
        return self._source_identity

    def select(self, query: AnalysisQuery) -> tuple[FeatureObservation, ...]:
        """Apply the same bounded filters used by both native adapters.

        Args:
            query: Fixed entity, interval, missingness and row-limit filters.

        Returns:
            Sorted, bounded observations selected from the retained source.
        """
        query.__post_init__()
        rows: Iterable[FeatureObservation] = self._rows
        if query.entity_type is not None:
            rows = (row for row in rows if row.entity_type == query.entity_type)
        if query.entity_key is not None:
            rows = (row for row in rows if row.entity_key == query.entity_key)
        if query.start is not None and query.end is not None:
            start, end = query.start, query.end
            rows = (row for row in rows if start <= row.decision_at < end)
        if not query.include_missing:
            rows = (row for row in rows if row.value is not None)
        selected = tuple(sorted(rows, key=self._sort_key))
        return selected[: query.max_rows]

    def for_request(self, request: OfflineFeatureRequest) -> tuple[FeatureObservation, ...]:
        """Rebind this MR3 source to one offline request and fill missing entities explicitly.

        Args:
            request: Validated offline feature grid whose source metadata is authoritative.

        Returns:
            Complete entity/decision rows with request definition and source identities.

        Raises:
            ValueError: The source rows do not match the request's units, entities or decisions.
        """
        request.__post_init__()
        if (
            request.definition.feature_name != "trailing_return"
            or request.definition.entity_type != "instrument"
        ):
            raise ValueError("offline feature request uses unsupported source semantics")
        if not self._rows or self._rows[0].units != request.definition.units:
            raise ValueError("offline feature source units differ from the request")
        source_rows = {(row.entity_key, row.decision_at): row for row in self._rows}
        if {row.decision_at for row in self._rows} != set(request.decisions):
            raise ValueError("offline feature source decisions differ from the request grid")
        requested = {entity.entity_key for entity in request.entities}
        source_entities = {row.entity_key for row in self._rows}
        if not source_entities <= requested:
            raise ValueError("offline feature request omits a retained MR3 entity")
        rows: list[FeatureObservation] = []
        for entity in request.entities:
            for decision in request.decisions:
                source_row = source_rows.get((entity.entity_key, decision))
                if source_row is None:
                    rows.append(
                        FeatureObservation(
                            definition_identity=request.definition.identity,
                            source_version=request.definition.source_version,
                            source_sha256=request.definition.source_sha256,
                            feature_name=request.definition.feature_name,
                            entity_type=request.definition.entity_type,
                            entity_key=entity.entity_key,
                            decision_at=decision,
                            event_at=None,
                            available_at=None,
                            ttl_us=request.definition.ttl_us,
                            units=request.definition.units,
                            value=None,
                            missing_reason="missing entity or no eligible source row",
                        )
                    )
                    continue
                row = replace(
                    source_row,
                    definition_identity=request.definition.identity,
                    source_version=request.definition.source_version,
                    source_sha256=request.definition.source_sha256,
                    feature_name=request.definition.feature_name,
                    entity_type=request.definition.entity_type,
                    ttl_us=request.definition.ttl_us,
                    units=request.definition.units,
                )
                row.__post_init__()
                rows.append(row)
        return tuple(rows)

    def _verify_projection(
        self,
        row: FeatureObservation,
        projection: Mapping[str, object],
        backend: str,
        *,
        clock_encoding: Literal["microseconds", "datetime"],
    ) -> None:
        """Verify every backend-converted column against its retained source row."""
        expected: dict[str, object] = {
            "row_identity": row.row_identity,
            "feature_name": row.feature_name,
            "entity_type": row.entity_type,
            "entity_key": row.entity_key,
            "ttl_us": row.ttl_us,
            "units": row.units,
            "value": row.value,
            "source_version": row.source_version,
            "source_sha256": row.source_sha256,
            "definition_identity": row.definition_identity,
            "revision_identity": row.revision_identity,
            "missing_reason": row.missing_reason,
        }
        if clock_encoding == "microseconds":
            expected.update(
                {
                    "decision_at": AnalysisQuery._time_us(row.decision_at),
                    "event_at": (
                        None if row.event_at is None else AnalysisQuery._time_us(row.event_at)
                    ),
                    "available_at": (
                        None
                        if row.available_at is None
                        else AnalysisQuery._time_us(row.available_at)
                    ),
                }
            )
        else:
            expected.update(
                {
                    "decision_at": row.decision_at,
                    "event_at": row.event_at,
                    "available_at": row.available_at,
                }
            )
        for name, wanted in expected.items():
            if name not in projection:
                raise ValueError(f"{backend} omitted verified column {name}")
            actual = projection[name]
            if wanted is None:
                valid = actual is None
            else:
                valid = type(actual) is type(wanted) and actual == wanted
            if not valid:
                raise ValueError(f"{backend} changed verified column {name}")

    @staticmethod
    def _sort_key(row: FeatureObservation) -> tuple[str, str, datetime]:
        """Order retained rows without changing their exact values or clocks."""
        return (row.entity_type, row.entity_key, row.decision_at)


class AnalysisResult(WireRecord, frozen=True, kw_only=True):
    """Retain one backend's bounded rows and the exact source/query identities."""

    schema_version: Literal["bounded-analysis-result-v1"] = "bounded-analysis-result-v1"
    backend: Literal["duckdb", "polars"]
    query_identity: str
    source_identity: str
    rows: tuple[FeatureObservation, ...]

    def __post_init__(self) -> None:
        """Validate backend identity and preserve nullable exact feature records."""
        if self.schema_version != "bounded-analysis-result-v1":
            raise ValueError("unsupported bounded analysis result schema")
        if self.backend not in ("duckdb", "polars"):
            raise ValueError("unsupported bounded analysis backend")
        AnalysisQuery._digest(self.query_identity, "query_identity")
        AnalysisQuery._digest(self.source_identity, "source_identity")
        if type(self.rows) is not tuple or len(self.rows) > _MAX_ROWS:
            raise ValueError("analysis result exceeds the bounded row limit")
        seen: set[str] = set()
        for row in self.rows:
            if type(row) is not FeatureObservation:
                raise TypeError("analysis result rows must be FeatureObservation records")
            row.__post_init__()
            if row.row_identity in seen:
                raise ValueError("analysis result rows must be unique")
            seen.add(row.row_identity)


class AnalysisMismatch(WireRecord, frozen=True, kw_only=True):
    """Retain one exact backend/reference difference, including nullable values."""

    schema_version: Literal["analysis-mismatch-v1"] = "analysis-mismatch-v1"
    backend: Literal["duckdb", "polars"]
    row_identity: str
    expected_value: str | None
    actual_value: str | None
    reason: str

    def __post_init__(self) -> None:
        """Validate mismatch identities while keeping values as exact strings."""
        if self.schema_version != "analysis-mismatch-v1":
            raise ValueError("unsupported analysis mismatch schema")
        if self.backend not in ("duckdb", "polars"):
            raise ValueError("unsupported analysis mismatch backend")
        AnalysisQuery._digest(self.row_identity, "row_identity")
        for value, name in (
            (self.expected_value, "expected_value"),
            (self.actual_value, "actual_value"),
        ):
            if value is not None and (type(value) is not str or "/" not in value):
                raise ValueError(f"{name} must remain an exact value string or null")
        AnalysisQuery._text(self.reason, "reason")


class AnalysisComparison(WireRecord, frozen=True, kw_only=True):
    """Compare DuckDB and Polars outputs with the retained native reference rows."""

    schema_version: Literal["bounded-analysis-comparison-v1"] = "bounded-analysis-comparison-v1"
    query_identity: str
    source_identity: str
    duckdb: AnalysisResult
    polars: AnalysisResult
    mismatches: tuple[AnalysisMismatch, ...] = ()

    def __post_init__(self) -> None:
        """Require both backend results to describe the same verified source and query."""
        if self.schema_version != "bounded-analysis-comparison-v1":
            raise ValueError("unsupported bounded analysis comparison schema")
        AnalysisQuery._digest(self.query_identity, "query_identity")
        AnalysisQuery._digest(self.source_identity, "source_identity")
        if type(self.duckdb) is not AnalysisResult or type(self.polars) is not AnalysisResult:
            raise TypeError("analysis comparison requires two AnalysisResult records")
        self.duckdb.__post_init__()
        self.polars.__post_init__()
        for result in (self.duckdb, self.polars):
            if (
                result.query_identity != self.query_identity
                or result.source_identity != self.source_identity
            ):
                raise ValueError("analysis result identity differs from comparison")
        for mismatch in self.mismatches:
            if type(mismatch) is not AnalysisMismatch:
                raise TypeError("analysis mismatches require AnalysisMismatch records")
            mismatch.__post_init__()

    @property
    def exact(self) -> bool:
        """Report whether both native adapters match the retained reference exactly.

        Returns:
            ``True`` when neither backend produced an identity, order or value mismatch.
        """
        return not self.mismatches


class DuckDBFeatureAnalysis:
    """Execute one fixed, parameterized DuckDB query over verified feature rows."""

    def run(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> AnalysisResult:
        """Filter, order and bound rows through DuckDB SQL without accepting caller SQL.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            DuckDB-selected observations reconstructed from retained records.

        Raises:
            ValueError: DuckDB returns an identity outside the verified source.
        """
        # third party library imports
        import duckdb

        source_rows = source.rows
        query.__post_init__()
        values = [
            (
                row.row_identity,
                row.feature_name,
                row.entity_type,
                row.entity_key,
                AnalysisQuery._time_us(row.decision_at),
                None if row.event_at is None else AnalysisQuery._time_us(row.event_at),
                None if row.available_at is None else AnalysisQuery._time_us(row.available_at),
                row.ttl_us,
                row.units,
                row.value,
                row.source_version,
                row.source_sha256,
                row.definition_identity,
                row.revision_identity,
                row.missing_reason,
            )
            for row in source_rows
        ]
        start_us = None if query.start is None else AnalysisQuery._time_us(query.start)
        end_us = None if query.end is None else AnalysisQuery._time_us(query.end)
        parameters: list[object] = [
            query.entity_type,
            query.entity_type,
            query.entity_key,
            query.entity_key,
            start_us,
            start_us,
            end_us,
            end_us,
            query.include_missing,
            query.max_rows,
        ]
        statement = (
            "SELECT row_identity, feature_name, entity_type, entity_key, decision_us, "
            "event_us, available_us, ttl_us, units, value, source_version, source_sha256, "
            "definition_identity, revision_identity, missing_reason FROM feature_rows "
            "WHERE (? IS NULL OR entity_type = ?) AND (? IS NULL OR entity_key = ?) "
            "AND (? IS NULL OR decision_us >= ?) AND (? IS NULL OR decision_us < ?) "
            "AND (? OR value IS NOT NULL) "
            "ORDER BY entity_type, entity_key, decision_us, row_identity LIMIT ?"
        )
        with duckdb.connect(
            database=":memory:", config={"threads": 1, "memory_limit": "512MB"}
        ) as connection:
            connection.execute(
                "CREATE TABLE feature_rows ("
                "row_identity VARCHAR, feature_name VARCHAR, entity_type VARCHAR, "
                "entity_key VARCHAR, decision_us BIGINT, event_us BIGINT, available_us BIGINT, "
                "ttl_us BIGINT, units VARCHAR, value VARCHAR, source_version VARCHAR, "
                "source_sha256 VARCHAR, definition_identity VARCHAR, revision_identity VARCHAR, "
                "missing_reason VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO feature_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            selected = connection.execute(statement, parameters).fetchall()
        indexed = {row.row_identity: row for row in source_rows}
        rows: list[FeatureObservation] = []
        for item in selected:
            if type(item) is not tuple or len(item) != 15 or type(item[0]) is not str:
                raise ValueError("DuckDB returned an invalid row identity")
            row = indexed.get(item[0])
            if row is None:
                raise ValueError("DuckDB returned an unknown verified row")
            projection = {
                name: item[index]
                for index, name in enumerate(
                    (
                        "row_identity",
                        "feature_name",
                        "entity_type",
                        "entity_key",
                        "decision_at",
                        "event_at",
                        "available_at",
                        "ttl_us",
                        "units",
                        "value",
                        "source_version",
                        "source_sha256",
                        "definition_identity",
                        "revision_identity",
                        "missing_reason",
                    )
                )
            }
            source._verify_projection(row, projection, "DuckDB", clock_encoding="microseconds")
            rows.append(row)
        return AnalysisResult(
            backend="duckdb",
            query_identity=query.identity,
            source_identity=source.source_identity,
            rows=tuple(rows),
        )


class PolarsFeatureAnalysis:
    """Run fixed Polars lazy filters while retaining exact strings and UTC timestamps."""

    def frame(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> pl.DataFrame:
        """Build a typed Polars frame from verified rows without float conversion.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            Collected Polars frame with exact strings, UTC clocks and nulls preserved.
        """
        # third party library imports
        import polars as pl

        query.__post_init__()
        rows = source.rows
        frame = pl.DataFrame(
            {
                "row_identity": [row.row_identity for row in rows],
                "feature_name": [row.feature_name for row in rows],
                "entity_type": [row.entity_type for row in rows],
                "entity_key": [row.entity_key for row in rows],
                "decision_at": [row.decision_at for row in rows],
                "event_at": [row.event_at for row in rows],
                "available_at": [row.available_at for row in rows],
                "ttl_us": [row.ttl_us for row in rows],
                "units": [row.units for row in rows],
                "value": [row.value for row in rows],
                "source_version": [row.source_version for row in rows],
                "source_sha256": [row.source_sha256 for row in rows],
                "definition_identity": [row.definition_identity for row in rows],
                "revision_identity": [row.revision_identity for row in rows],
                "missing_reason": [row.missing_reason for row in rows],
            },
            schema={
                "row_identity": pl.String,
                "feature_name": pl.String,
                "entity_type": pl.String,
                "entity_key": pl.String,
                "decision_at": pl.Datetime("us", time_zone="UTC"),
                "event_at": pl.Datetime("us", time_zone="UTC"),
                "available_at": pl.Datetime("us", time_zone="UTC"),
                "ttl_us": pl.Int64,
                "units": pl.String,
                "value": pl.String,
                "source_version": pl.String,
                "source_sha256": pl.String,
                "definition_identity": pl.String,
                "revision_identity": pl.String,
                "missing_reason": pl.String,
            },
            strict=True,
        )
        lazy = frame.lazy()
        if query.entity_type is not None:
            lazy = lazy.filter(pl.col("entity_type").eq(query.entity_type))
        if query.entity_key is not None:
            lazy = lazy.filter(pl.col("entity_key").eq(query.entity_key))
        if query.start is not None and query.end is not None:
            lazy = lazy.filter(
                (pl.col("decision_at") >= query.start) & (pl.col("decision_at") < query.end)
            )
        if not query.include_missing:
            lazy = lazy.filter(pl.col("value").is_not_null())
        return (
            lazy.sort(["entity_type", "entity_key", "decision_at", "row_identity"])
            .limit(query.max_rows)
            .collect()
        )

    def run(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> AnalysisResult:
        """Return typed observations selected by the Polars transformation.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            Polars-selected observations reconstructed from retained records.

        Raises:
            ValueError: Polars returns an identity outside the verified source.
        """
        frame = self.frame(source, query)
        indexed = {row.row_identity: row for row in source.rows}
        rows: list[FeatureObservation] = []
        columns = frame.to_dict(as_series=False)
        identity_column = columns.get("row_identity")
        if identity_column is None:
            raise ValueError("Polars omitted verified row identity")
        for index, identity in enumerate(identity_column):
            if type(identity) is not str or identity not in indexed:
                raise ValueError("Polars returned an unknown verified row identity")
            row = indexed[identity]
            projection: dict[str, object] = {}
            for name, values in columns.items():
                if index >= len(values):
                    raise ValueError("Polars returned a truncated verified column")
                projection[name] = values[index]
            source._verify_projection(row, projection, "Polars", clock_encoding="datetime")
            rows.append(row)
        return AnalysisResult(
            backend="polars",
            query_identity=query.identity,
            source_identity=source.source_identity,
            rows=tuple(rows),
        )


class BoundedFeatureAnalysis:
    """Compare the DuckDB and Polars adapters against the retained native rows."""

    def __init__(self) -> None:
        """Create stateless backend adapters; no SQL or frame state is retained."""
        self._duckdb = DuckDBFeatureAnalysis()
        self._polars = PolarsFeatureAnalysis()

    def duckdb(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> AnalysisResult:
        """Run the bounded DuckDB projection.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            DuckDB result with every converted field checked against the source.
        """
        return self._duckdb.run(source, query)

    def polars(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> AnalysisResult:
        """Run the bounded Polars projection.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            Polars result with every converted field checked against the source.
        """
        return self._polars.run(source, query)

    def compare(self, source: VerifiedFeatureRows, query: AnalysisQuery) -> AnalysisComparison:
        """Compare both adapters with the native selection using identities and nulls.

        Args:
            source: Verified observations from one immutable source projection.
            query: Fixed filters and result bound.

        Returns:
            Both backend results with every identity or exact-value mismatch retained.
        """
        reference = source.select(query)
        duckdb_result = self.duckdb(source, query)
        polars_result = self.polars(source, query)
        mismatches: list[AnalysisMismatch] = []
        backend_rows: tuple[
            tuple[Literal["duckdb", "polars"], tuple[FeatureObservation, ...]], ...
        ] = (
            ("duckdb", duckdb_result.rows),
            ("polars", polars_result.rows),
        )
        for backend, rows in backend_rows:
            if len(rows) != len(reference):
                mismatches.append(
                    AnalysisMismatch(
                        backend=backend,
                        row_identity=source.rows[0].row_identity,
                        expected_value=None,
                        actual_value=None,
                        reason="backend returned a different bounded row count",
                    )
                )
                continue
            for expected, actual in zip(reference, rows, strict=True):
                if expected.row_identity != actual.row_identity:
                    mismatches.append(
                        AnalysisMismatch(
                            backend=backend,
                            row_identity=expected.row_identity,
                            expected_value=expected.value,
                            actual_value=actual.value,
                            reason="backend changed row identity or ordering",
                        )
                    )
                elif expected.value != actual.value:
                    mismatches.append(
                        AnalysisMismatch(
                            backend=backend,
                            row_identity=expected.row_identity,
                            expected_value=expected.value,
                            actual_value=actual.value,
                            reason="backend changed exact value or null semantics",
                        )
                    )
        return AnalysisComparison(
            query_identity=query.identity,
            source_identity=source.source_identity,
            duckdb=duckdb_result,
            polars=polars_result,
            mismatches=tuple(mismatches),
        )
