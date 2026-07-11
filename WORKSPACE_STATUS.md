# Workspace Status

## Completed

- Restored the full Data Formulator source tree on `develop`.
- Initialized Git repository with `origin` and `upstream` remotes.
- Added configurable product modes: `data_formulator` and `business_insight`.
- Exposed brand metadata through `/api/app-config`.
- Wired frontend branding surfaces to backend product-mode metadata.
- Added versioned Business Insight domain contracts.
- Added workspace-confined atomic JSON and NDJSON storage.
- Added `GET /api/insight/health`.
- Added architecture and upstream strategy documents.
- Added tests for branding, contracts, storage, health routing, and frontend brand fallback.
- Created the private GitHub repository `GuangjieYu1/business-insight-agent`.

## Current limitations

- Full dependency installation and baseline test results are recorded in `docs/testing/BASELINE_TEST_REPORT.md`.
- `upstream/dev` is ahead of the stable `upstream/main` baseline and has not been merged in Phase 0.
- The `business_insight` product mode is a branding and extension hook only; the full analysis workflow starts in Phase 1.

## Next implementation target

Phase 1 continuation:

1. Project repository and service layer.
2. Dataset registration contract.
3. Immutable Dataset Version 0 creation.
4. `/api/insight/project` and `/api/insight/datasets` routes.
5. Keep all new persistent business-analysis data under workspace-scoped Insight storage.
