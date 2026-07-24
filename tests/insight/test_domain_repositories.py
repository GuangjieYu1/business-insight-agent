from pathlib import Path

import pytest
from pydantic import ValidationError

from data_formulator.insight.domain import (
    AgentRun,
    AgentStep,
    AnalysisGoal,
    Approval,
    Artifact,
    Claim,
    EvidenceRef,
    Experiment,
    FinalSummary,
    ProjectMaterial,
)
from data_formulator.insight.storage import (
    ApprovalStore,
    ArtifactStore,
    DomainObjectAlreadyExistsError,
    DomainObjectNotFoundError,
    DomainStoreError,
    EvidenceStore,
    ExperimentStore,
    GoalStore,
    LocalInsightStore,
    MaterialStore,
    RunStore,
)


WORKSPACE_ID = "workspace_1"


def _local_store(tmp_path: Path) -> LocalInsightStore:
    return LocalInsightStore(tmp_path)


def _material(workspace_id: str = WORKSPACE_ID) -> ProjectMaterial:
    return ProjectMaterial(
        id="material_1",
        workspace_id=workspace_id,
        type="xlsx",
        filename="sales.xlsx",
        content_hash="sha256:material",
        ingestion_status="completed",
    )


def _goal(workspace_id: str = WORKSPACE_ID) -> AnalysisGoal:
    return AnalysisGoal(
        id="goal_1",
        workspace_id=workspace_id,
        goal_type="driver_analysis",
        title="Analyze sales drivers",
        target_column="sales",
        task_type="regression",
        confidence=0.9,
    )


def _run(run_id: str = "run_1", workspace_id: str = WORKSPACE_ID) -> AgentRun:
    return AgentRun(
        id=run_id,
        workspace_id=workspace_id,
        goal_id="goal_1",
        dataset_version_id="version_000",
    )


def test_material_and_goal_stores_are_atomic_and_backward_compatible(tmp_path: Path):
    store = _local_store(tmp_path)
    materials = MaterialStore(store, workspace_id=WORKSPACE_ID)
    goals = GoalStore(store, workspace_id=WORKSPACE_ID)

    # Old workspaces have no domain directories yet and must remain readable.
    assert materials.list() == []
    assert goals.list() == []
    assert materials.read("material_missing") is None

    material = materials.create(_material())
    goal = goals.create(_goal())

    assert materials.read(material.id) == material
    assert goals.read(goal.id) == goal
    assert store.exists("materials/material_1.json")
    assert store.exists("goals/goal_1.json")

    updated_goal = goal.model_copy(
        update={
            "status": "confirmed",
            "updated_at": goal.updated_at,
        }
    )
    assert goals.update(updated_goal).status == "confirmed"
    assert goals.list() == [updated_goal]

    with pytest.raises(DomainObjectAlreadyExistsError):
        materials.create(material)
    with pytest.raises(DomainObjectNotFoundError):
        goals.update(_goal().model_copy(update={"id": "goal_missing"}))


def test_domain_stores_reject_cross_workspace_objects_and_corruption(tmp_path: Path):
    store = _local_store(tmp_path)
    materials = MaterialStore(store, workspace_id=WORKSPACE_ID)

    with pytest.raises(DomainStoreError, match="workspace_id"):
        materials.create(_material(workspace_id="workspace_2"))

    # A foreign object inside this workspace root is treated as corruption, not
    # silently returned or skipped.
    store.write_json("materials/material_1.json", _material(workspace_id="workspace_2"))
    with pytest.raises(DomainStoreError, match="workspace_id"):
        materials.read("material_1")
    with pytest.raises(DomainStoreError, match="workspace_id"):
        materials.list()

    with pytest.raises(DomainStoreError):
        materials.read("../material_1")


def test_experiment_artifact_and_approval_stores(tmp_path: Path):
    store = _local_store(tmp_path)
    experiments = ExperimentStore(store, workspace_id=WORKSPACE_ID)
    artifacts = ArtifactStore(store, workspace_id=WORKSPACE_ID)
    approvals = ApprovalStore(store, workspace_id=WORKSPACE_ID)

    experiment = Experiment(
        id="experiment_1",
        workspace_id=WORKSPACE_ID,
        experiment_type="baseline",
        task_type="regression",
        dataset_version_id="version_000",
        target_column="sales",
        validation_strategy="kfold",
    )
    artifact = Artifact(
        id="artifact_1",
        workspace_id=WORKSPACE_ID,
        artifact_type="chart",
        title="Sales distribution",
        experiment_id=experiment.id,
        dataset_version_id="version_000",
        file_ref="artifacts/artifact_1/chart.json",
        content_hash="sha256:artifact",
    )
    approval = Approval(
        id="approval_1",
        workspace_id=WORKSPACE_ID,
        action_type="cleaning_operation",
        action_ref="proposal_1",
        requested_by="user_1",
    )

    experiments.create(experiment)
    artifacts.create(artifact)
    approvals.create(approval)

    assert experiments.read(experiment.id) == experiment
    assert experiments.list() == [experiment]
    assert artifacts.read(artifact.id) == artifact
    assert approvals.read(approval.id) == approval
    assert store.exists("experiments/experiment_1/spec.json")

    approved = approval.model_copy(
        update={
            "status": "approved",
            "decided_by": "user_1",
            "updated_at": approval.updated_at,
        }
    )
    assert approvals.update(approved).status == "approved"

    with pytest.raises(ValidationError):
        Artifact(
            id="artifact_bad",
            workspace_id=WORKSPACE_ID,
            artifact_type="file",
            title="bad",
            file_ref="../outside.txt",
        )


def test_evidence_store_requires_existing_workspace_evidence(tmp_path: Path):
    store = _local_store(tmp_path)
    evidence_store = EvidenceStore(store, workspace_id=WORKSPACE_ID)

    evidence = EvidenceRef(
        id="evidence_1",
        workspace_id=WORKSPACE_ID,
        source_type="experiment",
        source_id="experiment_1",
        dataset_version_id="version_000",
        metric="mae",
        value=12.4,
        content_hash="sha256:evidence",
    )
    evidence_store.create_evidence(evidence)

    claim = Claim(
        id="claim_1",
        workspace_id=WORKSPACE_ID,
        statement="The feature provides stable incremental model information.",
        claim_type="model_attribution",
        support_level="derived",
        confidence="medium",
        evidence_refs=[evidence.id],
        limitations=["This does not establish causality."],
    )
    evidence_store.create_claim(claim)

    assert evidence_store.read_evidence(evidence.id) == evidence
    assert evidence_store.read_claim(claim.id) == claim
    assert evidence_store.list_evidence() == [evidence]
    assert evidence_store.list_claims() == [claim]

    missing_evidence_claim = claim.model_copy(
        update={
            "id": "claim_missing",
            "evidence_refs": ["evidence_missing"],
        }
    )
    with pytest.raises(DomainStoreError, match="missing evidence"):
        evidence_store.create_claim(missing_evidence_claim)

    unsupported = Claim(
        id="claim_unsupported",
        workspace_id=WORKSPACE_ID,
        statement="Insufficient evidence is available.",
        claim_type="descriptive",
        support_level="unsupported",
        confidence="low",
        evidence_refs=[],
    )
    assert evidence_store.create_claim(unsupported) == unsupported


def test_run_store_persists_steps_and_final_summary(tmp_path: Path):
    store = _local_store(tmp_path)
    runs = RunStore(store, workspace_id=WORKSPACE_ID)
    run = runs.create(_run())

    first_step = AgentStep(
        id="step_1",
        workspace_id=WORKSPACE_ID,
        run_id=run.id,
        type="progress",
        title="Inspect dataset",
        status="completed",
        progress_text="Dataset structure inspected",
    )
    second_step = AgentStep(
        id="step_2",
        workspace_id=WORKSPACE_ID,
        run_id=run.id,
        type="observation",
        title="Profile completed",
        status="completed",
        output_refs=["profile_1"],
    )

    runs.append_step(first_step)
    runs.append_step(second_step)

    assert runs.list_steps(run.id) == [first_step, second_step]
    assert store.exists("runs/run_1/steps.ndjson")
    with pytest.raises(DomainObjectAlreadyExistsError):
        runs.append_step(first_step)

    with pytest.raises(DomainStoreError, match="workspace_id"):
        runs.append_step(
            first_step.model_copy(
                update={"id": "step_foreign", "workspace_id": "workspace_2"}
            )
        )
    with pytest.raises(DomainObjectNotFoundError):
        runs.append_step(first_step.model_copy(update={"id": "step_missing", "run_id": "run_missing"}))

    summary = FinalSummary(
        id="summary_1",
        workspace_id=WORKSPACE_ID,
        run_id=run.id,
        title="Sales quality review",
        executive_summary="Two deterministic quality issues were found.",
        claim_refs=["claim_1"],
        operation_refs=["operation_1"],
        artifact_refs=["artifact_1"],
        limitations=["No causal inference was performed."],
        next_steps=["Confirm the analysis goal."],
    )
    runs.write_final_summary(summary)

    assert runs.read_final_summary(run.id) == summary
    persisted_run = runs.require(run.id)
    assert persisted_run.final_summary_ref == "runs/run_1/final_summary.json"
    assert store.exists(persisted_run.final_summary_ref)


def test_run_store_recovers_legacy_run_without_steps_or_summary(tmp_path: Path):
    store = _local_store(tmp_path)
    legacy_run = _run(run_id="run_legacy")
    store.write_json("runs/run_legacy/run.json", legacy_run)

    runs = RunStore(store, workspace_id=WORKSPACE_ID)
    assert runs.read(legacy_run.id) == legacy_run
    assert runs.list_steps(legacy_run.id) == []
    assert runs.read_final_summary(legacy_run.id) is None
    assert runs.list() == [legacy_run]

    foreign_runs = RunStore(store, workspace_id="workspace_2")
    with pytest.raises(DomainStoreError, match="workspace_id"):
        foreign_runs.read(legacy_run.id)
