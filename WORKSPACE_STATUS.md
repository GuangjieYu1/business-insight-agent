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
- Added Phase 3A right-pane Business Insight profiling display with dataset registration, saved-profile loading, and version_000 fallback generation.

## Current limitations

- Full dependency installation and baseline test results are recorded in `docs/testing/BASELINE_TEST_REPORT.md`.
- `upstream/dev` is ahead of the stable `upstream/main` baseline and has not been merged in Phase 0.
- Dataset Profiling currently supports only immutable `version_000`.
- Profile thresholds are fixed in code for the first pass: near-constant columns at 95% dominant value and high-missing columns at 50% missing values.
- Profile generation is still synchronous HTTP work, with file size, row count, column count, and timeout guardrails as the first protection layer.
- Only the right-pane profiling display is implemented in Phase 3A; cleaning recommendations, async jobs, and multi-version profile UX are still pending.

## Next implementation target

Post-Phase 3A follow-up sequence:

1. Backfill Phase 1 storage debt with InsightStore protocol boundaries and workspace locking.
2. Finish Phase 2 immutable dataset version workflows: activation, history, undo, and branching.
3. Return to Phase 3B for the remaining deterministic detectors and cleaning proposal generation.
4. Keep all new persistent business-analysis data under workspace-scoped Insight storage.
5. Defer async profiling jobs until the deterministic profiling/display path is stable.
