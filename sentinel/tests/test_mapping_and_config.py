from datetime import datetime, timezone

import pytest

from innerlogic_sentinel.config import Config, normalize_start
from innerlogic_sentinel.errors import ConfigError
from innerlogic_sentinel.ingest import to_row

SAMPLE = {
    "eventId": "9f6f919c-d754-48a1-8d38-b753f902f42c",
    "sequence": "82104",
    "occurredAt": "2026-09-01T14:10:00.000Z",
    "recordedAt": "2026-09-01T14:10:00.010Z",
    "tenantId": "11111111-1111-4111-8111-111111111111",
    "schemaVersion": 1,
    "category": "data_activity",
    "action": "survey_results.accessed",
    "outcome": "SUCCESS",
    "actor": {"type": "USER", "email": "analyst@example.com", "credentialId": None},
    "resource": {"type": "survey_schedule", "id": "44444444"},
    "source": {"ip": "192.0.2.10", "userAgent": "Example", "authMethod": "JWT"},
    "requestId": "request-example-123",
    "correlationId": None,
    "description": "Alex Analyst accessed survey results",
    "metadata": {"dataClass": "AGGREGATE"},
    "brandNewField": {"kept": True},
}


def test_row_maps_documented_fields_and_keeps_raw_event():
    row = to_row(SAMPLE)
    assert row["eventId"] == SAMPLE["eventId"]
    assert row["sequence"] == "82104"
    assert row["tenantId"] == SAMPLE["tenantId"]
    assert row["rawEvent"] is SAMPLE and row["rawEvent"]["brandNewField"] == {"kept": True}
    assert row["correlationId"] is None


def test_row_tolerates_sparse_events_and_numeric_sequence():
    row = to_row({"eventId": "x", "sequence": 82104})
    assert row["sequence"] == "82104"
    assert row["actor"] is None and row["schemaVersion"] is None


def test_row_keys_match_dcr_stream_columns():
    import json, pathlib
    stream = json.loads((pathlib.Path(__file__).parents[1] / "schema/dcr-stream.json").read_text())
    declared = [c["name"] for c in stream["streamDeclarations"]["Custom-InnerlogicAudit"]["columns"]]
    assert sorted(to_row(SAMPLE)) == sorted(declared)


ENV = {
    "INNERLOGIC_AUDIT_TOKEN": "ilaudit_x", "INNERLOGIC_START_UTC": "2026-09-01T00:00:00Z",
    "DCE_ENDPOINT": "https://d.ingest.monitor.azure.com", "DCR_IMMUTABLE_ID": "dcr-1",
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
}


def test_config_defaults():
    cfg = Config.from_env(ENV)
    assert cfg.api_base == "https://node-v3.innerlogic-api.com"
    assert cfg.page_limit == 500 and cfg.stream_name == "Custom-InnerlogicAudit"


@pytest.mark.parametrize("missing", ["INNERLOGIC_AUDIT_TOKEN", "DCE_ENDPOINT", "DCR_IMMUTABLE_ID", "INNERLOGIC_START_UTC"])
def test_config_requires_settings(missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(ConfigError):
        Config.from_env(env)


def test_config_accepts_managed_identity_table_uri_instead_of_connection_string():
    env = {k: v for k, v in ENV.items() if k != "AzureWebJobsStorage"}
    env["AzureWebJobsStorage__tableServiceUri"] = "https://acct.table.core.windows.net"
    cfg = Config.from_env(env)
    assert cfg.table_service_uri and cfg.storage_connection_string is None


def test_config_requires_some_storage_setting():
    env = {k: v for k, v in ENV.items() if k != "AzureWebJobsStorage"}
    with pytest.raises(ConfigError, match="AzureWebJobsStorage"):
        Config.from_env(env)


def test_config_flags_unresolved_key_vault_reference():
    with pytest.raises(ConfigError, match="Key Vault"):
        Config.from_env({**ENV, "INNERLOGIC_AUDIT_TOKEN": "@Microsoft.KeyVault(SecretUri=https://x)"})


@pytest.mark.parametrize("limit", ["0", "1001", "abc"])
def test_config_rejects_bad_page_limit(limit):
    with pytest.raises(ConfigError):
        Config.from_env({**ENV, "PAGE_LIMIT": limit})


def test_start_must_be_utc_z_and_future_is_clamped():
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ConfigError):
        normalize_start("2026-09-01T00:00:00+00:00", now)
    with pytest.raises(ConfigError):
        normalize_start("not-a-date" "Z", now)
    assert normalize_start("2026-10-27T12:00:05Z", now) == "2026-10-27T12:00:00.000Z"
    assert normalize_start("2026-09-01T00:00:00Z", now) == "2026-09-01T00:00:00.000Z"
