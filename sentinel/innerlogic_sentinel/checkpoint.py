from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode

PARTITION = "audit"
ROW = "cursor"


class TableCheckpointStore:
    """Single-row cursor store in Azure Table Storage.

    One upsert of one entity is atomic, which is what the guide requires:
    save the cursor only after the whole page was accepted.
    """

    def __init__(self, service: TableServiceClient, table_name: str) -> None:
        service.create_table_if_not_exists(table_name)
        self._table = service.get_table_client(table_name)

    @classmethod
    def from_connection_string(cls, connection_string: str, table_name: str) -> "TableCheckpointStore":
        """Local development (Azurite) or shared-key storage."""
        return cls(TableServiceClient.from_connection_string(connection_string), table_name)

    @classmethod
    def from_endpoint(cls, endpoint: str, table_name: str, credential: Any) -> "TableCheckpointStore":
        """Managed identity: needs 'Storage Table Data Contributor' on the account."""
        return cls(TableServiceClient(endpoint=endpoint, credential=credential), table_name)

    def get(self) -> Optional[str]:
        try:
            entity = self._table.get_entity(PARTITION, ROW)
        except ResourceNotFoundError:
            return None
        return entity.get("Cursor") or None

    def save(self, cursor: str) -> None:
        self._table.upsert_entity(
            {
                "PartitionKey": PARTITION,
                "RowKey": ROW,
                "Cursor": cursor,
                "UpdatedAt": datetime.now(timezone.utc).isoformat(),
            },
            mode=UpdateMode.REPLACE,
        )
