# Workspace Status

## Current stage

Phase 5 multi-version profiling and continuous cleaning workflow is complete on `develop`.

The current Business Insight flow is:

```text
register dataset
→ immutable version_000
→ deterministic Profile
→ version-bound cleaning Proposals
→ privacy-safe Preview
→ approve or reject
→ Apply as version_001
→ automatically Profile version_001
→ generate the next version_001 Proposals
→ compare parent and child Profiles
→ continue cleaning or Undo from persistent Operation history
```

The frozen Phase 4 release remains on `release/phase4` and is tracked by Draft PR #12. It intentionally excludes Phase 5 and still requires a real-browser smoke test before merging into `main`.

## Completed

- Retained upstream-compatible package, API-prefix, and Redux boundaries from Microsoft Data Formulator.
- Added configurable `data_formulator` and `business_insight` product modes.
- Added workspace-confined Insight storage, atomic JSON/NDJSON/Parquet writes, and workspace locking.
- Added project and dataset registration with immutable `version_000` snapshots.
- Added dataset version creation, activation, branching, history, Operation records, and Undo.
- Added deterministic, privacy-safe Profiling with resource limits and the complete current detector set.
- Added bilingual Profiling display and deterministic cleaning Proposal generation.
- Added whitelist-based reversible operations for `trim_string`, `replace_invalid_character`, `drop_duplicate_rows`, `rename_column`, and `drop_column`.
- Added privacy-safe Preview, Approve, Reject, idempotent Apply, stale-version rejection, and per-input-version concurrency serialization.
- Added version-specific Profile GET/POST APIs and version-specific Proposal GET/POST APIs while preserving `version_000` compatibility routes.
- Added best-effort output analysis: successful Apply profiles the immutable output version and generates its next Proposal set; post-processing failures never roll back a successful version.
- Added persistent dataset Operation history and Profile comparison APIs.
- Added deterministic resolved, introduced, and unchanged issue classification plus before/after metric deltas.
- Added a bilingual dataset version selector in Cleaning Suggestions.
- Historical versions are read-only; only the active version exposes executable cleaning controls.
- Added persistent Undo recovery after page refresh by loading backend Operation history.
- Added automatic version-context refresh after successful Apply or Undo.
- Expanded CI to cover the version-aware API client and versioned cleaning workspace panel.

## Current limitations

- The standalone Data Profile tab still opens through the original selected-table `version_000` registration flow; multi-version comparison is currently presented in Cleaning Suggestions.
- The embedded legacy cleaning panel retains a small amount of duplicate version-summary information beneath the new version context card.
- Casting, date conversion, imputation, value replacement, conditional row deletion, and other higher-risk operations remain disabled.
- Profile and Proposal generation remain synchronous HTTP work, protected by file-size, row-count, column-count, and timeout guardrails.
- Profile comparison currently uses issue type plus Scope as issue identity; future detector revisions may require an explicit stable issue key.
- The frozen Phase 4 release cannot merge into `main` until its real-browser journey is verified.
- Old merged Feature branches still exist remotely because the available connector cannot delete Git refs.
- `upstream/dev` remains ahead of the stable `upstream/main` baseline and has not been merged into the product fork.

## Next implementation target

Phase 6 should focus on operational maturity rather than widening the deterministic core too quickly:

1. Run and record the Phase 4 real-browser smoke test, then merge frozen PR #12 into `main`.
2. Remove duplicate version-summary presentation from the embedded cleaning panel.
3. Add explicit stable issue identifiers for long-lived cross-profiler comparisons.
4. Add higher-risk cleaning operations with explicit error and data-loss policies.
5. Move Profile and Proposal generation to asynchronous jobs with queued/running/completed/failed/cancelled states.
6. Add task polling or SSE, cancellation, retry, and persisted job history.
7. Continue keeping all business-analysis data under workspace-scoped Insight storage.
8. Clean up merged Feature branches manually after release verification.
