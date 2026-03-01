"""Connector lifecycle abstractions for data collection."""

from __future__ import annotations

import apps.data_collector.connectors._lifecycle as connector_lifecycle
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors._streaming as connector_streaming
import apps.data_collector.connectors._types as connector_types

BaseConnector = connector_lifecycle.BaseConnector
ConnectorState = connector_types.ConnectorState
EmitCallback = connector_lifecycle.EmitCallback
FatalConnectorError = connector_types.FatalConnectorError
OutcomeStreamingConnector = connector_streaming.OutcomeStreamingConnector
PollingBatch = connector_types.PollingBatch
PollingConnector = connector_polling.PollingConnector
StreamingConnector = connector_streaming.StreamingConnector
normalize_outcome_ids = connector_types.normalize_outcome_ids

__all__ = [
    "BaseConnector",
    "ConnectorState",
    "EmitCallback",
    "FatalConnectorError",
    "OutcomeStreamingConnector",
    "PollingBatch",
    "PollingConnector",
    "StreamingConnector",
    "normalize_outcome_ids",
]
