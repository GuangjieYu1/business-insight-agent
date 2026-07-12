# Baseline Test Report

Baseline date: 2026-07-12

## Scope

This report records the validated Business Insight baseline through Phase 5.

Merged milestones include:

- deterministic dataset profiling and display
- immutable dataset versioning and cleaning Proposals
- reversible cleaning operations and Cleaning Suggestions UI
- version-specific Profile and Proposal APIs
- automatic output-version Profile and Proposal generation after Apply
- persistent Operation history and parent/child Profile comparison APIs
- version-aware Cleaning Suggestions with historical read-only mode and refresh-persistent Undo

The frozen Phase 4 release is tracked separately by Draft PR #12 from `release/phase4` to `main`. Phase 5 remains on `develop` until a later release is prepared.

## Supported environment

GitHub Actions uses:

- Ubuntu hosted runner
- Node setup through `actions/setup-node`
- Python 3.12 through `uv`
- Yarn dependencies from the repository lockfile

Local development commands:

```bash
uv sync
yarn
uv run data_formulator --dev --product-mode business_insight
yarn start
```

## CI validation commands

### Business Insight backend

```bash
uv run pytest tests/insight -q
```

Coverage includes:

- workspace boundaries and storage contracts
- project and dataset registration
- immutable Dataset Versions
- activation, branching, history, rollback, and Undo
- deterministic profiling for `version_000` and later versions
- resource limits, redaction, and detector coverage
- deterministic version-bound cleaning Proposals
- cleaning operation parameter validation
- privacy-safe Preview
- approval and rejection state transitions
- Apply idempotency and stale-version rejection
- concurrent Apply serialization
- automatic output-version Profile and Proposal generation
- failure isolation without cleaning-version rollback
- persistent Operation history
- parent/child Profile comparison and issue deltas
- route-level multi-version behavior

### Existing Insight frontend

```bash
yarn vitest run \
  tests/frontend/productConfig.test.ts \
  tests/frontend/unit/insight/InsightWorkspacePane.test.tsx \
  tests/frontend/unit/insight/insightClient.test.ts \
  tests/frontend/unit/insight/profilingSlice.test.ts
```

### Cleaning API client

```bash
yarn vitest run tests/frontend/unit/insight/cleaningClient.test.ts
```

### Cleaning workspace panels

```bash
yarn vitest run \
  tests/frontend/unit/insight/CleaningWorkspacePanel.test.tsx \
  tests/frontend/unit/insight/VersionedCleaningWorkspacePanel.test.tsx
```

### Production builds

```bash
yarn build
uv build
```

The workflow archives production artifacts. PyPI publishing remains disabled for pull-request runs.

## Latest validated Phase 5 runs

### Version-specific Profile and Proposal APIs

GitHub Actions run `29188982666` passed.

### Output-version analysis after Apply

GitHub Actions run `29189177573` passed.

### Operation history and Profile comparison APIs

GitHub Actions run `29189319431` passed.

### Version-aware Cleaning Suggestions workspace

GitHub Actions run `29189583311` passed.

Each run completed the backend suite, Insight frontend tests, cleaning client/panel tests, frontend production build, Python artifact build, and production artifact archive.

## Manual review coverage

The merged Phase 5 pull requests were reviewed for:

- exact dataset-version and workspace ownership checks
- current profiler/configuration reuse rules
- preservation of approved, rejected, and applied Proposal state
- compatibility of the existing `version_000` and legacy Apply APIs
- post-processing failure isolation after successful Apply
- immutable parent/child Profile comparison
- dataset-scoped Operation history
- historical-version read-only enforcement
- refresh-persistent Undo eligibility
- bounded PR scope and no new third-party runtime dependencies

## Known limitations

- The standalone Data Profile tab remains oriented around initial `version_000` registration; multi-version comparison lives in Cleaning Suggestions.
- The embedded legacy cleaning panel repeats some version-summary information.
- Higher-risk cast, imputation, value replacement, and row-filter operations remain disabled.
- Profile and Proposal generation remain synchronous HTTP operations.
- A real browser smoke test is still required before frozen Phase 4 PR #12 can merge into `main`.
- Merged Feature branches require manual deletion because the current connector cannot delete Git refs.

## Conclusion

The automated Phase 5 baseline is green on `develop`. The deterministic multi-version loop is complete:

```text
version_000 Profile
→ version_000 Proposals
→ Preview / Approve / Apply
→ version_001 Profile
→ version_001 Proposals
→ parent-child comparison
→ persistent Undo or continued cleaning
```

The next engineering stage is operational maturity: release smoke testing, UI consolidation, explicit stable issue identifiers, higher-risk operations with data-loss policies, and asynchronous Profile/Proposal jobs.
