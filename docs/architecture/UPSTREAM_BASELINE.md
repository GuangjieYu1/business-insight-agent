# Upstream Baseline

## Source

- Upstream repository: `https://github.com/microsoft/data-formulator.git`
- Fork repository: `https://github.com/GuangjieYu1/business-insight-agent.git`
- Package license: MIT
- Baseline branch: `upstream/main`
- Baseline commit: `00d0f5e1655e2a5bb02fda289f73960bbac62027`
- Observed upstream `dev` head: `5b908ee2f3571f28ac88b1d6b5c383e4475d9343`
- Fork integration branch: `develop`
- Current Phase 0 head: `5f2c88d40e86a2537e61a9f7fd81386b6ca945f0` before the local Phase 0 completion edits
- Baseline date: 2026-07-12

## Merge Base

`develop` is based on `upstream/main` at `00d0f5e1655e2a5bb02fda289f73960bbac62027`.

## Source Availability

The workspace now contains the full Data Formulator source tree, including Python backend code, editable TypeScript frontend source, upstream tests, `uv.lock`, and `yarn.lock`.

## Notes

`upstream/dev` is ahead of `upstream/main`. Phase 0 records the stable `upstream/main` baseline and does not merge `upstream/dev`; future upstream sync work should use a dedicated `upstream-sync/*` branch.
