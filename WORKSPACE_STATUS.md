# Workspace Status

## Current stage

Phase 4 reversible cleaning workflow is complete on `develop`.

The current Business Insight flow is:

```text
register dataset
→ immutable version_000
→ deterministic profile
→ cleaning proposals
→ privacy-safe preview
→ approve or reject
→ apply as a new dataset version
→ inspect version history
→ undo
```

## Completed

- Restored the full Data Formulator source tree and retained upstream-compatible package, route, and Redux boundaries.
- Added configurable `data_formulator` and `business_insight` product modes with backend-provided branding.
- Added versioned Business Insight domain contracts and workspace-confined Insight storage.
- Added `InsightStore` protocol boundaries, atomic JSON/NDJSON/Parquet writes, and workspace locking.
- Added project registration, dataset registration, and immutable `version_000` snapshots.
- Added dataset version creation, activation, history listing, branching, operation records, and Undo.
- Added deterministic dataset profiling with profiler/config metadata, content-idempotent profile IDs, resource limits, privacy-safe value persistence, and duplicate-row metrics.
- Added the full current detector set: empty, constant, near-constant, high-missing, duplicate rows/columns, mixed types, numeric/date parse conflicts, dirty characters, high-cardinality identifiers, outliers, invalid or unclear headers, infinite values, and whitespace pollution.
- Added the Business Insight profiling display with dataset registration, saved-profile loading, and `version_000` fallback generation.
- Added deterministic cleaning proposal generation with issue-to-operation mapping.
- Added whitelist-based reversible cleaning operations for `trim_string`, `replace_invalid_character`, `drop_duplicate_rows`, `rename_column`, and `drop_column`.
- Added privacy-safe Preview, Approve, Reject, Apply, idempotency, stale-version rejection, and per-input-version concurrency serialization.
- Added the bilingual Cleaning Suggestions workspace with proposal status, Preview metrics, Apply, version history, and latest-operation Undo.
- Expanded CI gates to cover Business Insight backend tests, existing Insight frontend tests, cleaning API client tests, cleaning workspace panel tests, production frontend build, Python artifact build, and artifact archive.
- Synchronized the former `main`-only temporary workflow commits into `develop` through PR #8 without changing the product tree.

## Current limitations

- Profiling, the profiling display, and automatic proposal generation still default to `version_000`; arbitrary-version profiling is not implemented yet.
- Apply creates and activates a new immutable dataset version but does not automatically profile that output version or generate its next proposal set.
- The Cleaning Suggestions panel displays version history, but its proposal context is not yet an interactive version selector.
- Undo is fully persisted on the backend, but the frontend only exposes Undo for the latest operation returned in the current UI session.
- Casting, imputation, conditional row deletion, and other higher-risk cleaning operations remain deferred.
- Profile and proposal generation remain synchronous HTTP work, protected by file-size, row-count, column-count, and timeout guardrails.
- `upstream/dev` remains ahead of the stable `upstream/main` baseline and has not been merged into the product fork.

## Next implementation target

Phase 5 should close the multi-version analysis loop:

1. Add version-specific Profile APIs and preserve the current `version_000` routes as compatibility aliases.
2. Profile each successful cleaning output version and generate proposals for that exact version.
3. Add version-aware Profile and Proposal selection in the frontend.
4. Add before/after Profile comparison with resolved, introduced, and unchanged issues plus metric deltas.
5. Add persistent Operation history APIs so Undo remains available after a page refresh.
6. Keep all persistent business-analysis data inside workspace-scoped Insight storage.
7. Defer asynchronous profiling jobs until the deterministic multi-version workflow is stable.
