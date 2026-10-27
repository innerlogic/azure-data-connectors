# Innerlogic Audit Log for Microsoft Sentinel

Streams your Innerlogic audit events into your own Microsoft Sentinel (Log Analytics) workspace.
An Azure Function in **your** subscription polls the Innerlogic audit API and writes events to the
`InnerlogicAudit_CL` table. Innerlogic never receives Azure credentials and needs no access to your tenant.

```
Innerlogic API  <--HTTPS poll (ilaudit_ token)--  Azure Function  --Logs Ingestion API-->  DCE/DCR  -->  InnerlogicAudit_CL
 (audit-events:read)                              (your subscription)                       (your workspace)
```

## Before you start

1. **Innerlogic token.** A user with the `security.audit_logs` permission opens the **Audit Log** area of the
   Innerlogic app and creates a SIEM access token (name it, set an expiry; 90 days is a good start). Copy it
   when shown; it starts with `ilaudit_` and is displayed once.
2. **Azure permissions.** The person deploying needs **Owner** on the resource group (or Contributor plus
   User Access Administrator), because the template creates role assignments.
3. **Resource group and region.** Deploy into the resource group that contains your Sentinel workspace, and set
   `location` to the workspace's region. That region must also offer Azure Functions **Flex Consumption**
   (check [Flex Consumption regions](https://learn.microsoft.com/azure/azure-functions/flex-consumption-how-to);
   the deployment fails otherwise).

## Deploy

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Finnerlogic%2Fazure-data-connectors%2Fmain%2Fsentinel%2Finfra%2Fazuredeploy.json)

| Parameter | Meaning |
|---|---|
| `workspaceName` | Existing Log Analytics workspace used by Sentinel (same resource group) |
| `location` | Same region as the workspace |
| `innerlogicAuditToken` | The `ilaudit_...` token (stored in Key Vault, never in app settings) |
| `startUtc` | Collect events recorded from this UTC time, ending in `Z`. Defaults to now; set earlier to backfill (retention is 13 months) |
| `packageUri` | Connector package, pinned to a release version (default `v1.0.0`). Redeploying never changes code unless you change this |
| `pollSchedule` | NCRONTAB, default every minute |

The template creates: the `InnerlogicAudit_CL` table, a data collection endpoint and rule, a function app
on the **Flex Consumption** plan with its storage account and Application Insights, a Key Vault holding the
token, and one managed identity. Nothing uses shared keys or client secrets: the storage account has key access
disabled, and the identity holds only the roles it needs (*Key Vault Secrets User* on the vault, *Monitoring
Metrics Publisher* on the rule, and the Blob/Queue/Table data roles on the function's own storage account).

## Verify

After a couple of minutes, in Sentinel > Logs:

```kusto
InnerlogicAudit_CL | sort by TimeGenerated desc | take 10
```

Initial table creation can take several minutes to appear in the Logs UI. If nothing arrives, check the
function app's **Monitor** blade / Application Insights for errors (see Troubleshooting).

## Working with the data

Delivery is at least once, so a replayed page can produce duplicate rows. De-duplicate on `EventId`:

```kusto
InnerlogicAudit_CL
| summarize arg_max(TimeGenerated, *) by EventId
```

`TimeGenerated` is the time Innerlogic recorded the event (`RecordedAt`); the time the activity happened is
`OccurredAt`. The complete original event, including any new fields Innerlogic adds later, is in `RawEvent`.
Events contain names, email addresses and IP addresses of the people performing activities.

## How checkpointing works

Per page: fetch, send every event to Azure, and only then save the returned cursor (Azure Table
`innerlogiccheckpoint` in the function's storage account). A failure at any step keeps the previous cursor,
so the next run replays the page. The first run uses `startUtc`; later runs use only the saved cursor.
To re-collect from an earlier time, stop the function, delete the cursor row, set `INNERLOGIC_START_UTC`, restart.

## Troubleshooting

| Symptom (function logs) | Cause and fix |
|---|---|
| HTTP 401 | Token invalid, expired or revoked. Create a new token in the Innerlogic app, update the `innerlogic-audit-token` secret in the Key Vault, then restart the function app. The checkpoint is kept. |
| HTTP 403 | Audit Log access unavailable for your organization. Contact your Innerlogic administrator. |
| HTTP 400 | Bad `startUtc` (must be UTC ending in `Z`, not in the future) or a damaged cursor. Do not reset to the current time. |
| HTTP 429 / 5xx / timeouts | Retried automatically with backoff (honours `Retry-After`); the run resumes from the last checkpoint. |
| Deployment fails on the function app | The chosen region may not offer Flex Consumption, or `packageUri` is unreachable (it must be a public URL). |
| `unresolved Key Vault reference` | The function's identity cannot read the secret, or the vault is firewalled. Confirm *Key Vault Secrets User* on the vault. |
| Azure rejected upload chunk | Check the DCR/table exist and the identity has *Monitoring Metrics Publisher* on the rule. Role assignments can take a few minutes to propagate. |

**Upgrading the connector:** redeploy the same template with `packageUri` set to the newer release's URL. The
existing checkpoint is kept.

**Rotating a token:** create the new token, update the Key Vault secret, restart the function app, confirm events
still arrive, then revoke the old token. Keep the existing checkpoint.

## Development

```bash
cd sentinel
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q tests
bash scripts/package.sh                       # builds dist/innerlogic-sentinel-connector.zip
az bicep build --file infra/main.bicep --outfile infra/azuredeploy.json   # regenerate after editing main.bicep
```

- `schema/` is the single source for the table and the DCR stream; Bicep loads it directly.
- Release: push a `vX.Y.Z` tag. The workflow runs tests, builds the package and publishes it as a release asset.
  Update the `packageUri` default in `main.bicep` (and recompile `azuredeploy.json`) to point at the new tag.
- Local run: copy `local.settings.sample.json` to `local.settings.json` and use Azure Functions Core Tools.
