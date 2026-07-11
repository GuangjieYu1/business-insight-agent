# Domain Model

The first stable contracts are implemented in `data_formulator.insight.domain.models`.

Core entities:

- `Project`
- `ProjectMaterial`
- `Dataset`
- `DatasetVersion`
- `CleaningProposal`
- `CleaningOperation`
- `AnalysisGoal`
- `AgentRun`
- `AgentStep`
- `Experiment`
- `EvidenceRef`
- `Claim`
- `Approval`

All entities are workspace-scoped and schema-versioned. Dataset versions are immutable references to physical data. Undo changes the active version and does not delete historical files.
