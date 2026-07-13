# Business Insight Data Egress Policy

Business Insight mode is fail-closed. By default, business data is stored only
in the local or ephemeral Workspace and is sent only to the model endpoint
selected by the user.

## Permanently blocked paths

- LiteLLM telemetry is disabled in every product mode.
- Business Insight mode clears LiteLLM success, failure, input, service,
  asynchronous, audit, and OpenTelemetry-compatible callback configuration.
- Azure Blob cannot be selected as the Business Insight Workspace backend.
  Azure Blob remains available as a user-selected input source.
- The Microsoft-hosted Chartifact viewer cannot receive Business Insight
  Markdown, CSV, chart specifications, or chart data. Local exports remain
  available.

## Administrator-enabled analysis services

Remote analysis services are disabled unless the server administrator defines
`BIA_REMOTE_ANALYSIS_SERVICES` as a JSON array. There is no browser API for
creating or editing these entries.

```json
[
  {
    "service_id": "tsfl",
    "display_name": "Forecast service",
    "endpoint": "https://forecast.example.com/api",
    "enabled": true,
    "allowed_data_types": ["time_series_rows", "artifact"],
    "timeout_seconds": 45,
    "workspace_scope": ["workspace_001"],
    "disable_behavior": "finish_in_flight"
  }
]
```

Allowed data types are `aggregated_metrics`, `artifact`,
`document_excerpt`, `profile_summary`, `table_rows`, `table_schema`, and
`time_series_rows`. A Workspace scope may contain explicit Workspace IDs or
`"*"`.

Every remote Adapter must call
`get_data_egress_policy().authorize(service_id=..., workspace_id=...,
data_type=...)` before sending data. Disabling a registry entry rejects every
new authorization immediately. `disable_behavior` records whether an Adapter
must finish or cancel a request that was already authorized.

The browser receives only enabled service IDs, display names, and target
domains. It never receives remote endpoints, credentials, allowed payload
details, or service configuration controls.

## Audit boundary

The authorization audit contains only the service ID, target domain, Workspace
ID, data type, time, and result. Request bodies, table values, prompts,
responses, credentials, and complete errors must not be logged.
