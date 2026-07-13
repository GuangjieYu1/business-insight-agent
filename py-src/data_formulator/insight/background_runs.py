"""Background execution support for observable Business Insight AgentRuns.

This module keeps the original synchronous service intact for compatibility,
while allowing Phase 5C clients to receive a Run immediately and watch its
persisted steps arrive over SSE.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Thread

from data_formulator.insight.cleaning import InsightCleaningError
from data_formulator.insight.domain import (
    AgentRun,
    AgentStep,
    CleaningProposal,
    DatasetProfile,
    FinalSummary,
)
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.run_service import (
    InsightRunConflictError,
    InsightRunError,
    InsightRunNotFoundError,
    _append_step,
    _record_failure,
    _resolve_dataset_version,
    _validate_goal,
    get_agent_run,
)
from data_formulator.insight.storage import (
    DomainObjectNotFoundError,
    DomainStoreError,
    InsightStore,
    RunStore,
)
from data_formulator.insight.version_cleaning import generate_cleaning_proposals_for_version
from data_formulator.insight.version_profiling import generate_dataset_version_profile


@dataclass(frozen=True)
class BackgroundRunCreation:
    run: AgentRun
    steps: list[AgentStep]


@dataclass(frozen=True)
class BackgroundRunExecution:
    run: AgentRun
    steps: list[AgentStep]
    profile: DatasetProfile | None
    proposals: list[CleaningProposal]
    final_summary: FinalSummary | None


def _run_dataset_id(run_store: RunStore, run_id: str) -> str:
    try:
        steps = run_store.list_steps(run_id)
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc
    if not steps:
        raise InsightRunError("AgentRun is missing its creation step")
    dataset_id = steps[0].detail.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise InsightRunError("AgentRun creation metadata is missing dataset_id")
    return dataset_id


def _read_locked_run(run_store: RunStore, run_id: str) -> AgentRun:
    path = run_store._run_path(run_id)
    if not run_store.store.exists(path):
        raise DomainObjectNotFoundError(f"AgentRun not found: {run_id}")
    run = run_store.store.read_model(path, AgentRun)
    if run.workspace_id != run_store.workspace_id:
        raise DomainStoreError("AgentRun workspace_id does not match active workspace")
    return run


def _transition_background_run(
    run_store: RunStore,
    run_id: str,
    *,
    status: str,
    current_stage: str,
) -> AgentRun | None:
    """Atomically transition a Run unless a concurrent cancellation won."""

    with run_store.store.workspace_lock():
        current = _read_locked_run(run_store, run_id)
        if current.status == "cancelled":
            return None
        updated = current.model_copy(
            update={
                "status": status,
                "current_stage": current_stage,
                "updated_at": utc_now(),
                "completed_at": None,
            }
        )
        run_store.store.write_json(run_store._run_path(run_id), updated)
    return updated


def _complete_background_run(
    run_store: RunStore,
    *,
    run_id: str,
    summary: FinalSummary,
) -> AgentRun | None:
    """Atomically persist FinalSummary and completed state unless cancelled."""

    if summary.run_id != run_id:
        raise DomainStoreError("FinalSummary run_id does not match AgentRun")
    if summary.workspace_id != run_store.workspace_id:
        raise DomainStoreError("FinalSummary workspace_id does not match active workspace")

    with run_store.store.workspace_lock():
        current = _read_locked_run(run_store, run_id)
        if current.status == "cancelled":
            return None
        summary_path = run_store._summary_path(run_id)
        run_store.store.write_json(summary_path, summary)
        now = utc_now()
        completed = current.model_copy(
            update={
                "status": "completed",
                "current_stage": "completed",
                "completed_at": now,
                "updated_at": now,
                "final_summary_ref": summary_path,
            }
        )
        run_store.store.write_json(run_store._run_path(run_id), completed)
    return completed


def _cancelled_result(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
    profile: DatasetProfile | None,
    proposals: list[CleaningProposal],
) -> BackgroundRunExecution:
    snapshot = get_agent_run(store, workspace_id=workspace_id, run_id=run_id)
    return BackgroundRunExecution(
        snapshot.run,
        snapshot.steps,
        profile,
        proposals,
        snapshot.final_summary,
    )


def create_background_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str | None = None,
    goal_id: str,
) -> BackgroundRunCreation:
    dataset, version = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    _validate_goal(
        store,
        workspace_id=workspace_id,
        goal_id=goal_id,
        dataset_id=dataset.id,
        version_id=version.id,
        columns=[str(column) for column in store.read_parquet(version.file_ref).columns.tolist()],
    )

    started_at = utc_now()
    run = AgentRun(
        id=new_id("run"),
        workspace_id=workspace_id,
        goal_id=goal_id,
        dataset_version_id=version.id,
        status="created",
        current_stage="created",
        started_at=started_at,
    )
    run_store = RunStore(store, workspace_id=workspace_id)
    run_store.create(run)
    _append_step(
        run_store,
        run,
        step_type="progress",
        title="Analysis run started",
        status="completed",
        progress_text="The deterministic Business Insight run has started.",
        input_refs=[dataset.id, version.id],
        detail={
            "dataset_id": dataset.id,
            "version_id": version.id,
            "execution_mode": "background",
        },
    )
    return BackgroundRunCreation(run=run, steps=run_store.list_steps(run.id))


def _require_executable_run(run_store: RunStore, run_id: str) -> AgentRun:
    try:
        run = run_store.require(run_id)
    except DomainObjectNotFoundError as exc:
        raise InsightRunNotFoundError(str(exc)) from exc
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc
    if run.status == "cancelled":
        raise InsightRunConflictError("Cancelled AgentRun cannot be executed")
    if run.status in {"completed", "failed", "waiting_approval"}:
        raise InsightRunConflictError(
            f"AgentRun in state '{run.status}' cannot be executed again"
        )
    return run


def _completed_summary(
    *,
    workspace_id: str,
    run: AgentRun,
    profile: DatasetProfile,
) -> FinalSummary:
    return FinalSummary(
        id=new_id("summary"),
        workspace_id=workspace_id,
        run_id=run.id,
        title="Data quality review complete",
        executive_summary=(
            "The deterministic profile completed and no cleaning proposal requires approval "
            "for the selected dataset version."
        ),
        metric_changes=[
            {
                "metric": "quality_issue_count",
                "value": len(profile.quality_issues),
            },
            {"metric": "row_count", "value": profile.row_count},
            {"metric": "column_count", "value": profile.column_count},
        ],
        limitations=[
            "This result is a deterministic data-quality review, not a predictive or causal analysis."
        ],
        next_steps=[
            "Confirm an analysis goal before running experiments or generating business claims."
        ],
    )


def execute_background_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
) -> BackgroundRunExecution:
    run_store = RunStore(store, workspace_id=workspace_id)
    run = _require_executable_run(run_store, run_id)
    dataset_id = _run_dataset_id(run_store, run.id)
    version_id = run.dataset_version_id
    if not version_id:
        raise InsightRunError("AgentRun is missing dataset_version_id")

    stage = "context_building"
    profile: DatasetProfile | None = None
    proposals: list[CleaningProposal] = []
    try:
        dataset, version = _resolve_dataset_version(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            version_id=version_id,
        )
        transitioned = _transition_background_run(
            run_store,
            run.id,
            status="context_building",
            current_stage=stage,
        )
        if transitioned is None:
            return _cancelled_result(
                store,
                workspace_id=workspace_id,
                run_id=run.id,
                profile=None,
                proposals=[],
            )
        run = transitioned
        _append_step(
            run_store,
            run,
            step_type="tool_call",
            title="Inspect dataset version",
            status="completed",
            progress_text="The selected immutable dataset version was validated.",
            input_refs=[dataset.id, version.id],
            output_refs=[version.file_ref],
            detail={
                "dataset_id": dataset.id,
                "version_id": version.id,
                "row_count": version.row_count,
                "column_count": version.column_count,
                "content_hash": version.content_hash,
            },
        )

        stage = "profiling"
        transitioned = _transition_background_run(
            run_store,
            run.id,
            status="profiling",
            current_stage=stage,
        )
        if transitioned is None:
            return _cancelled_result(
                store,
                workspace_id=workspace_id,
                run_id=run.id,
                profile=None,
                proposals=[],
            )
        run = transitioned
        profile = generate_dataset_version_profile(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
        )
        if run_store.require(run.id).status == "cancelled":
            return _cancelled_result(
                store,
                workspace_id=workspace_id,
                run_id=run.id,
                profile=profile,
                proposals=[],
            )
        _append_step(
            run_store,
            run,
            step_type="tool_call",
            title="Profile dataset version",
            status="completed",
            progress_text=f"Detected {len(profile.quality_issues)} deterministic quality issues.",
            input_refs=[version.id],
            output_refs=[profile.id, profile.profile_ref],
            detail={
                "profile_id": profile.id,
                "quality_issue_count": len(profile.quality_issues),
                "row_count": profile.row_count,
                "column_count": profile.column_count,
            },
        )

        stage = "planning"
        transitioned = _transition_background_run(
            run_store,
            run.id,
            status="planning",
            current_stage=stage,
        )
        if transitioned is None:
            return _cancelled_result(
                store,
                workspace_id=workspace_id,
                run_id=run.id,
                profile=profile,
                proposals=[],
            )
        run = transitioned
        proposals = generate_cleaning_proposals_for_version(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
        )
        if run_store.require(run.id).status == "cancelled":
            return _cancelled_result(
                store,
                workspace_id=workspace_id,
                run_id=run.id,
                profile=profile,
                proposals=proposals,
            )
        _append_step(
            run_store,
            run,
            step_type="tool_call",
            title="Generate cleaning proposals",
            status="completed",
            progress_text=f"Generated {len(proposals)} deterministic cleaning proposals.",
            input_refs=[profile.id],
            output_refs=[proposal.id for proposal in proposals],
            detail={
                "proposal_count": len(proposals),
                "proposal_ids": [proposal.id for proposal in proposals],
            },
        )

        if proposals:
            transitioned = _transition_background_run(
                run_store,
                run.id,
                status="waiting_approval",
                current_stage="waiting_approval",
            )
            if transitioned is None:
                return _cancelled_result(
                    store,
                    workspace_id=workspace_id,
                    run_id=run.id,
                    profile=profile,
                    proposals=proposals,
                )
            run = transitioned
            _append_step(
                run_store,
                run,
                step_type="approval",
                title="Cleaning approval required",
                status="pending",
                progress_text="Review the proposed deterministic cleaning operations before any data change.",
                input_refs=[proposal.id for proposal in proposals],
                detail={
                    "proposal_ids": [proposal.id for proposal in proposals],
                    "requires_user_approval": True,
                },
            )
        else:
            final_summary = _completed_summary(
                workspace_id=workspace_id,
                run=run_store.require(run.id),
                profile=profile,
            )
            completed = _complete_background_run(
                run_store,
                run_id=run.id,
                summary=final_summary,
            )
            if completed is None:
                return _cancelled_result(
                    store,
                    workspace_id=workspace_id,
                    run_id=run.id,
                    profile=profile,
                    proposals=[],
                )
            run = completed
            _append_step(
                run_store,
                run,
                step_type="progress",
                title="Analysis run completed",
                status="completed",
                progress_text="No deterministic cleaning approval is required for this version.",
                output_refs=[profile.id, final_summary.id],
                detail={"final_summary_id": final_summary.id},
            )

        snapshot = get_agent_run(store, workspace_id=workspace_id, run_id=run.id)
        return BackgroundRunExecution(
            run=snapshot.run,
            steps=snapshot.steps,
            profile=profile,
            proposals=proposals,
            final_summary=snapshot.final_summary,
        )
    except InsightRunConflictError:
        raise
    except (InsightProfileError, InsightCleaningError, DomainStoreError) as exc:
        current = run_store.require(run.id)
        if current.status != "cancelled":
            _record_failure(run_store, current, stage=stage, message=str(exc))
        raise InsightRunError(str(exc)) from exc
    except Exception as exc:
        current = run_store.require(run.id)
        if current.status != "cancelled":
            _record_failure(
                run_store,
                current,
                stage=stage,
                message="The deterministic analysis run failed unexpectedly.",
            )
        raise InsightRunError(
            "The deterministic analysis run failed unexpectedly."
        ) from exc


def launch_background_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
) -> Thread:
    def target() -> None:
        try:
            execute_background_agent_run(
                store,
                workspace_id=workspace_id,
                run_id=run_id,
            )
        except InsightRunError:
            # The Run and error Step are persisted by execute_background_agent_run.
            return

    thread = Thread(
        target=target,
        name=f"business-insight-{run_id}",
        daemon=True,
    )
    thread.start()
    return thread


def list_agent_runs(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str | None = None,
) -> list[AgentRun]:
    run_store = RunStore(store, workspace_id=workspace_id)
    try:
        runs = run_store.list()
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc
    if dataset_id is not None:
        filtered: list[AgentRun] = []
        for run in runs:
            try:
                if _run_dataset_id(run_store, run.id) == dataset_id:
                    filtered.append(run)
            except InsightRunError:
                # A corrupt legacy Run must not prevent recovery of healthy
                # Runs for the same Dataset.
                continue
        runs = filtered
    return sorted(runs, key=lambda item: (item.created_at, item.id), reverse=True)
