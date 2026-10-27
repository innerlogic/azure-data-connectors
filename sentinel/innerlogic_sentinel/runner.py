from __future__ import annotations

from azure.identity import DefaultAzureCredential

from .checkpoint import TableCheckpointStore
from .client import AuditApiClient
from .config import Config
from .ingest import LogsIngestionSink
from .poller import RunStats, run_once


def run() -> RunStats:
    cfg = Config.from_env()
    client = AuditApiClient(cfg.api_base, cfg.token, max_attempts=cfg.max_attempts)
    if cfg.table_service_uri:
        store = TableCheckpointStore.from_endpoint(
            cfg.table_service_uri, cfg.checkpoint_table, DefaultAzureCredential()
        )
    else:
        store = TableCheckpointStore.from_connection_string(
            cfg.storage_connection_string, cfg.checkpoint_table
        )
    sink = LogsIngestionSink(cfg.dce_endpoint, cfg.dcr_immutable_id, cfg.stream_name)
    return run_once(
        client,
        store,
        sink,
        start_utc=cfg.start_utc,
        page_limit=cfg.page_limit,
        max_runtime_seconds=cfg.max_runtime_seconds,
    )
