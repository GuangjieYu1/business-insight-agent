"""Background execution support for observable Business Insight AgentRuns.

This module keeps the original synchronous service intact for compatibility,
while allowing Phase 5C clients to receive a Run immediately and watch its
persisted steps arrive over SSE.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
from typing import Any

from data_formulator.insight.cleaning import InsightCleaningError
from data_formulator.insight.domain import AgentRun, AgentStep, CleaningProposal, DatasetProfile, FinalSummary
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.run_service import (
    InsightRunConflictError,
    InsightRunError,
    InsightRunNotFoundError,
    RunSnapshot,
    _append_step,
    _record_failure,
    _resolve_dataset_version,
    _transition_run,
    _validate_goal,
    get_agent_run,
)
from data_formulator.insight.storage import DomainObjectNotFoundError, DomainStoreError, InsightStore, RunStore
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
    steps = run_store.list_steps(run_id)
    if not steps:
        raise InsightRunError("AgentRun is missing its creation step")
    dataset_id = steps[0].detail.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise InsightRunError("AgentRun creation metadata is missing dataset_id")
    return dataset_id


def create_background_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str | None = None,
    goal_id: str | None = None,
) -> BackgroundRunCreation:
    dataset, version = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    _validate_goal(store, workspace_id=workspace_id, goal_id=goal_id)

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
    if run.status == "cancelled":
        raise InsightRunConflictError("Cancelled AgentRun cannot be executed")
    if run.status in {"completed", "failed", "waiting_approval"}:
        raise InsightRunConflictError(
            f"AgentRun in state '{run.status}' cannot be executed again"
        )
    return run


def _stop_if_cancelled(run_store: RunStore, run_id: str) -> AgentRun | None:
    current = run_store.require(run_id)
    return current if current.status == "cancelled" else None


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
        run = _transition_run(
            run_store,
            run,
            status="context_building",
            current_stage=stage,
        )
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
        cancelled = _stop_if_cancelled(run_store, run.id)
        if cancelled:
            snapshot = get_agent_run(store, workspace_id=workspace_id, run_id=run.id)
            return BackgroundRunExecution(cancelled, snapshot.steps, None, [], snapshot.final_summary)

        stage = "profiling"
        run = _transition_run(
            run_store,
            run_store.require(run.id),
            status="profiling",
            current_stage=stage,
        )
        profile = generate_dataset_version_profile(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
        )
        if _stop_if_cancelled(run_store, run.id):
            snapshot = get_agent_run(store, workspace_id=workspace_id, run_id=run.id)
            return BackgroundRunExecution(snapshot.run, snapshot.steps, profile, [], snapshot.final_summary)
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
        run = _transition_run(
            run_store,
            run_store.require(run.id),
            status="planning",
            current_stage=stage,
        )
        proposals = generate_cleaning_proposals_for_version(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
        )
        if _stop_if_cancelled(run_store, run.id):
            snapshot = get_agent_run(store, workspace_id=workspace_id, run_id=run.id)
            return BackgroundRunExecution(snapshot.run, snapshot.steps, profile, proposals, snapshot.final_summary)
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
            run = _transition_run(
                run_store,
                run_store.require(run.id),
                status="waiting_approval",
                current_stage="waiting_approval",
            )
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
            final_summary = None
        else:
            run = _transition_run(
                run_store,
                run_store.require(run.id),
                status="completed",
                current_stage="completed",
                completed=True,
            )
            _append_step(
                run_store,
                run,
                step_type="progress",
                title="Analysis run completed",
                status="completed",
                progress_text="No deterministic cleaning approval is required for this version.",
                output_refs=[profile.id],
            )
            final_summary = _completed_summary(
                workspace_id=workspace_id,
                run=run,
                profile=profile,
            )
            run_store.write_final_summary(final_summary)
            run = run_store.require(run.id)

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
    runs = run_store.list()
    if dataset_id is not None:
        filtered: list[AgentRun] = []
        for run in runs:
            try:
                if _run_dataset_id(run_store, run.id) == dataset_id:
                    filtered.append(run)
            except InsightRunError:
                continue
        runs = filtered
    return sorted(runs, key=lambda item: (item.created_at, item.id), reverse=True)
