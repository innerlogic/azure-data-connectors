from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient

from .errors import IngestionError


def to_row(event: Dict[str, Any]) -> Dict[str, Any]:
    """Map one Innerlogic event onto the DCR input stream.

    Nulls are allowed everywhere. The untouched event is kept in `rawEvent`
    so unknown fields and new categories are never lost.
    """
    sequence = event.get("sequence")
    schema_version = event.get("schemaVersion")
    return {
        "eventId": event.get("eventId"),
        "sequence": None if sequence is None else str(sequence),
        "occurredAt": event.get("occurredAt"),
        "recordedAt": event.get("recordedAt"),
        "tenantId": event.get("tenantId"),
        "schemaVersion": schema_version if isinstance(schema_version, int) else None,
        "category": event.get("category"),
        "action": event.get("action"),
        "outcome": event.get("outcome"),
        "description": event.get("description"),
        "actor": event.get("actor"),
        "resource": event.get("resource"),
        "source": event.get("source"),
        "requestId": event.get("requestId"),
        "correlationId": event.get("correlationId"),
        "metadata": event.get("metadata"),
        "rawEvent": event,
    }


class LogsIngestionSink:
    def __init__(
        self,
        endpoint: str,
        dcr_immutable_id: str,
        stream_name: str,
        client: Optional[LogsIngestionClient] = None,
    ) -> None:
        self._client = client or LogsIngestionClient(
            endpoint=endpoint, credential=DefaultAzureCredential(), logging_enable=False
        )
        self._rule_id = dcr_immutable_id
        self._stream = stream_name

    def upload(self, rows: Iterable[Dict[str, Any]]) -> None:
        failures: List[str] = []

        def on_error(error: Any) -> None:
            failures.append(f"{type(error.error).__name__}: {error.error}")

        self._client.upload(
            rule_id=self._rule_id,
            stream_name=self._stream,
            logs=list(rows),
            on_error=on_error,
        )
        if failures:
            raise IngestionError(
                f"Azure rejected {len(failures)} upload chunk(s); first error: {failures[0]}"
            )
