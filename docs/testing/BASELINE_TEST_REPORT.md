# Baseline Test Report

Baseline date: 2026-07-12

## Scope

This report records the validated Phase 4 Business Insight baseline after merging:

- PR #4: deterministic dataset profiling hardening
- PR #5: profiling display, dataset versioning, and cleaning proposals
- PR #6: reversible cleaning operations
- PR #7: cleaning workspace UI
- PR #8: `main` history synchronization into `develop`

The Phase 4 product path now covers immutable dataset registration, deterministic profiling, cleaning proposals, privacy-safe Preview, approval-driven Apply, new dataset versions, version history, and Undo.

## Supported environment

GitHub Actions uses:

- Ubuntu hosted runner
- Node setup through `actions/setup-node`
- Python environment through `uv`
- Yarn dependencies from the repository lockfile

Local development commands remain:

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

- product mode and health routing
- workspace boundaries and storage contracts
- project and dataset registration
- immutable `version_000`
- dataset version creation, activation, branching, history, rollback, and Undo
- deterministic profiling, resource limits, redaction, and detector coverage
- deterministic cleaning proposal generation
- cleaning operation parameter validation
- privacy-safe Preview
- approval and rejection state transitions
- Apply idempotency
- stale-version rejection
- concurrent Apply serialization
- route-level reversible-cleaning behavior

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

### Cleaning workspace panel

```bash
yarn vitest run tests/frontend/unit/insight/CleaningWorkspacePanel.test.tsx
```

### Production builds

```bash
yarn build
uv build
```

The workflow also archives the production artifacts. PyPI publishing is skipped for pull-request runs.

## Latest validated runs

### Reversible cleaning backend

GitHub Actions run `29187495048` completed successfully for commit `ed31e64b4da82b457e1a0ca0114c4e00f1e25863`.

Successful gates:

- Business Insight backend tests
- Business Insight frontend tests
- frontend production build
- Python artifact build
- production artifact archive

### Cleaning workspace UI

GitHub Actions run `29187880062` completed successfully for commit `dcaa7bb515c6fa72d553d38b93fb3d9ebc14f1d3`.

Successful gates:

- Business Insight backend tests
- existing Insight frontend tests
- cleaning API client tests
- cleaning workspace panel tests
- frontend production build
- Python artifact build
- production artifact archive

## Manual review coverage

The merged Phase 4 pull requests were reviewed for:

- whitelist-only operation execution
- preservation of immutable source versions
- absence of raw before/after values in Preview responses
- explicit approval before Apply
- deterministic and idempotent execution
- stale and concurrent execution protection
- frontend request lifecycle safety
- parity between backend detector types and bilingual frontend labels
- bounded PR scope and no new third-party runtime dependencies

## Known limitations

- Profiling and proposal generation still default to `version_000`.
- Successful Apply does not yet automatically profile the output version.
- The frontend does not yet provide persistent Operation history after refresh.
- Higher-risk cast, imputation, and row-filter operations remain disabled.
- Profile and proposal generation remain synchronous HTTP operations.
- A real browser smoke test is still required before the Phase 4 release is merged into `main`; repository CI validates code and builds but does not exercise the complete user journey in a running browser.

## Conclusion

The automated Phase 4 baseline is green. The repository is ready for a `develop` to `main` release pull request after documentation review and a real-browser smoke test of:

```text
select table
→ open Data Profile
→ open Cleaning Suggestions
→ Preview
→ Approve
→ Apply
→ observe version_001
→ Undo
→ return to version_000
```
