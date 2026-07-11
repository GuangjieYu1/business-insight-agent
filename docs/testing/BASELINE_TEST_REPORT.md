# Baseline Test Report

Baseline date: 2026-07-12

## Environment

- Branch: `develop`
- Upstream baseline: `upstream/main` at `00d0f5e1655e2a5bb02fda289f73960bbac62027`
- Python: 3.11.15
- Node: 24.16.0
- Package manager notes:
  - `uv sync` could not run because `uv` is not installed in this environment.
  - Backend dependencies were installed with a local `.venv` fallback: `python -m venv .venv && .venv/bin/python -m pip install -e . pytest`.
  - `yarn` was provided through Corepack as Yarn 1.22.22.
  - `corepack yarn install --frozen-lockfile` failed because the lockfile needs an update.
  - `corepack yarn install --pure-lockfile` completed without modifying `yarn.lock`.

## Backend Baseline

Command:

```bash
.venv/bin/python -m pytest
```

Result:

- 1900 passed
- 12 skipped
- 1 xpassed
- 2 failed
- 3 errors
- 16 warnings

Failures and errors:

- `tests/backend/data/test_all_loader_verification.py::TestStaticMethods::test_all_loaders_have_list_params`
- `tests/backend/data/test_all_loader_verification.py::TestStaticMethods::test_all_loaders_have_required_host_or_identifier`
- Both failures assert that `sample_datasets` must expose required connection parameters.
- `tests/backend/data/test_sync_catalog_cross_db.py::TestMSSQLSyncCatalogMetadata::*`
- The three MSSQL errors fail while importing `pyodbc` because the host is missing `libodbc.so.2`.

## Business Insight Backend Tests

Command:

```bash
.venv/bin/python -m pytest tests/insight -q
```

Result:

- 9 passed

## Frontend Baseline

Install command:

```bash
corepack yarn install --pure-lockfile
```

Result:

- Completed in 74.49s
- Warnings: peer dependency warnings for MUI, TipTap, gofish, Vega packages, plus Node `url.parse()` deprecation warning.

Test command:

```bash
corepack yarn test
```

Result:

- 27 test files passed
- 5 test files failed
- 251 tests passed
- 12 tests failed
- 1 suite failed during setup

Failing areas:

- `tests/frontend/unit/views/DataSourceSidebar.test.tsx` mock is missing `dataFormulatorReducer`.
- `tests/frontend/unit/app/agentMetadataTimeout.test.ts` expects a `configured` status while the reducer returns `unknown`.
- `tests/frontend/unit/app/getAccessToken.test.ts` token refresh expectations return `null`.
- `tests/frontend/unit/components/ConnectorTablePreview.test.tsx` cannot find the expected source metadata text.
- `tests/frontend/unit/app/IdentityMigrationDialog.test.tsx` renders an empty dialog body in several cases.

## Business Insight Frontend Test

Command:

```bash
corepack yarn vitest run tests/frontend/productConfig.test.ts
```

Result:

- 1 test file passed
- 2 tests passed

## Frontend Build

Command:

```bash
corepack yarn build
```

Result:

- Passed
- Warnings:
  - `perf_hooks` externalized for browser compatibility through TypeScript.
  - `vm-browserify` uses `eval`.
  - Some dynamic imports are also statically imported and cannot move into separate chunks.
  - Several chunks exceed the configured 1000 kB warning threshold.

## Conclusion

The Phase 0 Business Insight additions pass their focused backend and frontend tests, and the production frontend build succeeds. The full upstream pytest and Vitest baselines are not clean in this host environment; failures are recorded above and should be triaged separately from Phase 0 product-mode and Insight foundation work.
