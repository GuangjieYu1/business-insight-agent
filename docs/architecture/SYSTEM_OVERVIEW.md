# Business Insight Agent — System Overview

Business Insight Agent extends Data Formulator into an evidence-driven business analysis system.

## Responsibilities

- Data Formulator core: workspace, loading, data thread, charting, sandbox.
- Business Insight domain: projects, immutable dataset versions, cleaning operations, analysis goals, agent runs, experiments, claims, and evidence.
- RAGFlow adapter: multimodal project knowledge.
- Tabular engine: deterministic profiling and reproducible sklearn/FLAML experiments.
- TSFL adapter: time-series backtests and forecasts.
- Hermes adapter: remote orchestration only.

## Governing rule

The language model may understand intent, propose plans, and synthesize conclusions. Canonical data modification, metrics, model execution, versioning, and evidence creation must be performed by deterministic services.
