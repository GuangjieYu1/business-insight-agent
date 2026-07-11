# Upstream Synchronization Strategy

## Principles

1. Keep the Python package name `data_formulator` during early phases.
2. Keep existing route prefixes and workspace files compatible.
3. Add Business Insight features under `data_formulator.insight` and `/api/insight`.
4. Avoid expanding existing monolithic frontend state; use separate Insight slices when the TypeScript source is available.
5. Preserve the upstream MIT license and copyright notices.
6. Keep branding configurable through product mode rather than global source renaming.

## Remotes for a local checkout

```bash
git remote add origin git@github.com:GuangjieYu1/business-insight-agent.git
git remote add upstream https://github.com/microsoft/data-formulator.git
```

## Sync workflow

```bash
git fetch upstream
git checkout develop
git merge upstream/main
```

Resolve conflicts in adapters and product-specific entry points rather than modifying upstream internals unnecessarily.
