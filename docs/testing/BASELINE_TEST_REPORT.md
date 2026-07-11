# Baseline Test Report

## Bootstrap source

Official `data_formulator==0.7.0` source distribution.

## Source availability

- Python backend: available
- Compiled frontend assets: available
- TypeScript frontend source: unavailable in source distribution
- Upstream test suite: unavailable in source distribution

## Consequence

A complete upstream `yarn test`, `yarn build`, and original pytest baseline cannot be claimed from this bootstrap package. New backend contract and storage tests are run locally. Full upstream baseline must be repeated after the GitHub fork is available.
