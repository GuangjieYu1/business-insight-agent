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
- Merged PR #3 into `main`.
- Fast-forwarded local and remote `develop` and `feature/dataset-profiling` from `main`.
- Added Phase 1 project registration, dataset registration, and immutable `version_000` snapshots.
- Started Dataset Profiling with `DatasetProfile`, `ColumnProfile`, read-only profile generation, profile persistence, and profile API routes.
- Hardened Dataset Profiling with content-idempotent profile IDs, profiler/config metadata, resource limits, privacy-safe value persistence, clearer duplicate-row metrics, and develop-aware CI triggers.

## Current limitations

- Full dependency installation and baseline test results are recorded in `docs/testing/BASELINE_TEST_REPORT.md`.
- `upstream/dev` is ahead of the stable `upstream/main` baseline and has not been merged in Phase 0.
- Dataset Profiling currently supports only immutable `version_000`.
- Profile thresholds are fixed in code for the first pass: near-constant columns at 95% dominant value and high-missing columns at 50% missing values.
- Profile generation is still synchronous HTTP work, with file size, row count, column count, and timeout guardrails as the first protection layer.
- UI integration, asynchronous profile jobs, and cleaning recommendations are not implemented yet.

## Next implementation target

Phase 1 Dataset Profiling continuation:

1. Harden profile issue evidence and severity calibration.
2. Add frontend API client and profile display surface.
3. Feed profile output into cleaning proposal generation.
4. Split profile generation into asynchronous jobs for larger datasets.
5. Add configurable profile thresholds after the first deterministic pass stabilizes.
6. Keep all new persistent business-analysis data under workspace-scoped Insight storage.
