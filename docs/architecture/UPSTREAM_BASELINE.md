# Upstream Baseline

## Source

- Upstream repository: `microsoft/data-formulator`
- Imported package: `data_formulator==0.7.0` source distribution from PyPI
- Package license: MIT
- Observed upstream `main` head during bootstrap: `00d0f5e1655e2a5bb02fda289f73960bbac62027`
- Bootstrap date: 2026-07-12

## Important limitation

The execution sandbox could not resolve `github.com` for a normal `git clone`. The initial local workspace was therefore created from the official PyPI source distribution. The source distribution includes the Python backend and compiled frontend assets, but not the editable TypeScript source tree or the upstream test suite.

Before frontend implementation or publication, replace/merge this bootstrap workspace with a full GitHub fork and retain this document for provenance.
