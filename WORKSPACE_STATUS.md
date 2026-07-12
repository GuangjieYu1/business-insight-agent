# Workspace Status

## Completed

- Restored the full Data Formulator source tree on `develop`.
- Initialized Git repository with `origin` and `upstream` remotes.
- Added configurable product modes: `data_formulator` and `business_insight`.
- Exposed brand metadata through `/api/app-config`.
- Wired frontend branding surfaces to backend product-mode metadata.
- Added versioned Business Insight domain contracts.
- Added workspace-confined Insight storage with atomic JSON, NDJSON, and Parquet persistence.
- Added `InsightStore` protocol boundaries and workspace locking to Business Insight persistence workflows.
- Added `GET /api/insight/health`.
- Added architecture and upstream strategy documents.
- Added tests for branding, contracts, storage, health routing, and frontend brand fallback.
- Created the private GitHub repository `GuangjieYu1/business-insight-agent`.
- Merged PR #3 into `main`.
- Fast-forwarded local and remote `develop` and `feature/dataset-profiling` from `main`.
- Added Phase 1 project registration, dataset registration, and immutable `version_000` snapshots.
- Added Phase 2 dataset version workflows: version creation, activation, history listing, undo, branching, and operation records.
- Added deterministic dataset profiling with content-idempotent profile IDs, profiler/config metadata, resource limits, privacy-safe value persistence, duplicate-row metrics, and the full current detector set.
- Added Phase 3A right-pane Business Insight profiling display with dataset registration, saved-profile loading, and `version_000` fallback generation.
- Added Phase 3B cleaning proposal generation with deterministic issue-to-operation mapping and `/api/insight/cleaning/proposals` routes.
- Restored the full frontend suite to green by fixing the five remaining profiling-branch regressions.

## Current limitations

- Full dependency installation and baseline test results are recorded in `docs/testing/BASELINE_TEST_REPORT.md`.
- `upstream/dev` is ahead of the stable `upstream/main` baseline and has not been merged in Phase 0.
- Dataset profiling, profiling display, and cleaning proposal generation still target `version_000`; multi-version profiling and proposal UX is not implemented yet.
- Profile generation and proposal generation are still synchronous HTTP work, with file size, row count, column count, and timeout guardrails as the first protection layer.
- Cleaning proposals are implemented, but approval-driven apply flows, before/after execution metrics, and reversible cleaning UI are still pending.

## Next implementation target

Post-Phase 3B follow-up sequence:

1. Build Phase 4 reversible cleaning operations on top of the new dataset version activation and undo primitives.
2. Extend profiling, proposal, and cleaning UX from `version_000` into multi-version before/after flows.
3. Add operation preview payloads, metric deltas, and version-aware before/after presentation.
4. Keep all new persistent business-analysis data under workspace-scoped Insight storage.
5. Defer async profiling jobs until the deterministic profiling/display path is stable.