# Innerlogic Azure Data Connectors

Open-source connectors that send Innerlogic audit log events to your own Azure environment.
Each connector runs in your subscription and pulls events from the Innerlogic audit API
with a read-only token that you create and control.

| Connector | What it does | Docs |
|---|---|---|
| [Microsoft Sentinel](sentinel/) | Streams audit events into your Sentinel / Log Analytics workspace | [Setup guide](sentinel/README.md) |

Questions or access help: contact your Innerlogic administrator.

## License

Apache License 2.0. See [LICENSE](LICENSE).
