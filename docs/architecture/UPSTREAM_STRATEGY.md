# Upstream Synchronization Strategy

## Principles

1. Keep the Python package name `data_formulator` during early phases.
2. Keep existing route prefixes and workspace files compatible.
3. Add Business Insight features under `data_formulator.insight` and `/api/insight`.
4. Avoid expanding existing monolithic frontend state; use separate Insight slices when the TypeScript source is available.
5. Preserve the upstream MIT license and copyright notices.
6. Keep branding configurable through product mode rather than global source renaming.

## Remotes

The working repository is configured as:

```bash
origin   https://github.com/GuangjieYu1/business-insight-agent.git
upstream https://github.com/microsoft/data-formulator.git
```

## Sync workflow

```bash
git fetch upstream
git checkout develop
git merge upstream/main
```

Resolve conflicts in adapters and product-specific entry points rather than modifying upstream internals unnecessarily.

## Project-Owned Extension Areas

- `py-src/data_formulator/insight/`
- `py-src/data_formulator/product.py`
- `docs/architecture/*` Business Insight documents
- `docs/testing/*` Business Insight baseline and acceptance documents
- `tests/insight/`
- Frontend product-mode helpers and future `src/insight/` modules

## Avoided Conflict Areas

The first phases should avoid broad edits to `data_formulator` package names, `/api/sessions`, `dfSlice.tsx`, and the existing Data Formulator workspace file contract unless a small compatibility hook is required.
