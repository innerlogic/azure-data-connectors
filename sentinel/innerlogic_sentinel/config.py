from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional

from .errors import ConfigError

DEFAULT_API_BASE = "https://node-v3.innerlogic-api.com"


@dataclass(frozen=True)
class Config:
    api_base: str
    token: str
    start_utc: str
    page_limit: int
    max_runtime_seconds: int
    max_attempts: int
    dce_endpoint: str
    dcr_immutable_id: str
    stream_name: str
    storage_connection_string: Optional[str]
    table_service_uri: Optional[str]
    checkpoint_table: str

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env

        def required(name: str) -> str:
            value = (env.get(name) or "").strip()
            if not value:
                raise ConfigError(f"Missing required setting {name}")
            return value

        token = required("INNERLOGIC_AUDIT_TOKEN")
        if token.startswith("@Microsoft.KeyVault"):
            # The platform failed to resolve the Key Vault reference.
            raise ConfigError(
                "INNERLOGIC_AUDIT_TOKEN is an unresolved Key Vault reference; "
                "check the function's identity has 'Key Vault Secrets User' on the vault"
            )

        connection_string = (env.get("AzureWebJobsStorage") or "").strip() or None
        table_uri = (env.get("AzureWebJobsStorage__tableServiceUri") or "").strip() or None
        if not connection_string and not table_uri:
            raise ConfigError(
                "Set AzureWebJobsStorage (connection string, local development) or "
                "AzureWebJobsStorage__tableServiceUri (managed identity, Azure)"
            )

        page_limit = _int(env, "PAGE_LIMIT", 500)
        if not 1 <= page_limit <= 1000:
            raise ConfigError("PAGE_LIMIT must be between 1 and 1000")

        return cls(
            api_base=(env.get("INNERLOGIC_API_BASE") or DEFAULT_API_BASE).rstrip("/"),
            token=token,
            start_utc=normalize_start(required("INNERLOGIC_START_UTC")),
            page_limit=page_limit,
            max_runtime_seconds=_int(env, "MAX_RUNTIME_SECONDS", 240),
            max_attempts=_int(env, "MAX_ATTEMPTS", 5),
            dce_endpoint=required("DCE_ENDPOINT"),
            dcr_immutable_id=required("DCR_IMMUTABLE_ID"),
            stream_name=(env.get("DCR_STREAM_NAME") or "Custom-InnerlogicAudit"),
            storage_connection_string=connection_string,
            table_service_uri=table_uri,
            checkpoint_table=(env.get("CHECKPOINT_TABLE") or "innerlogiccheckpoint"),
        )


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def normalize_start(value: str, now: Optional[datetime] = None) -> str:
    """Return a UTC timestamp ending in Z that is not in the future.

    The API requires `from` to be UTC (ending in Z) and not in the future.
    A deployment-time default can be a few seconds ahead of the API's clock,
    so a future value is clamped to now rather than rejected.
    """
    now = now or datetime.now(timezone.utc)
    text = value.strip()
    if not text.endswith("Z"):
        raise ConfigError("INNERLOGIC_START_UTC must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ConfigError("INNERLOGIC_START_UTC is not a valid ISO 8601 timestamp") from exc
    if parsed > now:
        parsed = now
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"
