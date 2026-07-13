"""Deterministic AgentRun orchestration for the first observable run slice.

Phase 5A deliberately orchestrates only existing trusted capabilities: dataset
inspection, version-aware profiling, and deterministic cleaning proposals. It
does not invoke an LLM, execute cleaning operations, or stream SSE events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from data_formulator.insight.registry import (
    InsightRegistryError,
    read_dataset,
    read_dataset_version,
)
from data_formulator.insight.storage import (
    DomainObjectNotFoundError,
    DomainStoreError,
    GoalStore,
    InsightStore,
    RunStore,
)
from data_formulator.insight.version_cleaning import generate_cleaning_proposals_for_version
from data_formulator.insight.version_profiling import generate_dataset_version_profile


class InsightRunError(ValueError):
    """Base error for deterministic AgentRun operations."""


class InsightRunNotFoundError(InsightRunError):
    """Raised when a requested Run, Dataset, Version, or Goal does not exist."""


class InsightRunConflictError(InsightRunError):
    """Raised when a Run transition is invalid for its current state."""


@dataclass(frozen=True)
class RunStartResult:
    run: AgentRun
    steps: list[AgentStep]
    profile: DatasetProfile
    proposals: list[CleaningProposal]


@dataclass(frozen=True)
class RunSnapshot:
    run: AgentRun
    steps: list[AgentStep]
    final_summary: FinalSummary | None


TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _resolve_dataset_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str | None,
):
    try:
        dataset = read_dataset(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightRunError(str(exc)) from exc
    if dataset is None:
        raise InsightRunNotFoundError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightRunError("Dataset workspace_id does not match active workspace")

    resolved_version_id = version_id or dataset.active_version_id
    try:
        version = read_dataset_version(store, dataset.id, resolved_version_id)
    except InsightRegistryError as exc:
        raise InsightRunError(str(exc)) from exc
    if version is None:
        raise InsightRunNotFoundError(
            f"Dataset version not found: {dataset.id}/{resolved_version_id}"
        )
    if version.workspace_id != workspace_id:
        raise InsightRunError("Dataset version workspace_id does not match active workspace")
    if version.dataset_id != dataset.id:
        raise InsightRunError("Dataset version metadata is inconsistent")
    return dataset, version


def _validate_goal(
    store: InsightStore,
    *,
    workspace_id: str,
    goal_id: str | None,
) -> None:
    if goal_id is None:
        return
    try:
        goal = GoalStore(store, workspace_id=workspace_id).read(goal_id)
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc
    if goal is None:
        raise InsightRunNotFoundError(f"AnalysisGoal not found: {goal_id}")


def _transition_run(
    run_store: RunStore,
    run: AgentRun,
    *,
    status: str,
    current_stage: str,
    completed: bool = False,
) -> AgentRun:
    now = utc_now()
    updated = run.model_copy(
        update={
            "status": status,
            "current_stage": current_stage,
            "updated_at": now,
            "completed_at": now if completed else None,
        }
    )
    return run_store.update(updated)


def _append_step(
    run_store: RunStore,
    run: AgentRun,
    *,
    step_type: str,
    title: str,
    status: str,
    progress_text: str,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> AgentStep:
    now = utc_now()
    step = AgentStep(
        id=new_id("step"),
        workspace_id=run.workspace_id,
        run_id=run.id,
        type=step_type,
        title=title,
        status=status,
        started_at=now,
        completed_at=now if status in {"completed", "failed", "cancelled"} else None,
        input_refs=input_refs or [],
        output_refs=output_refs or [],
        progress_text=progress_text,
        detail=detail or {},
        collapsed_by_default=True,
    )
    return run_store.append_step(step)


def _record_failure(
    run_store: RunStore,
    run: AgentRun,
    *,
    stage: str,
    message: str,
) -> AgentRun:
    try:
        failed = _transition_run(
            run_store,
            run,
            status="failed",
            current_stage=stage,
            completed=True,
        )
        _append_step(
            run_store,
            failed,
            step_type="error",
            title="Analysis run failed",
            status="failed",
            progress_text=message,
            detail={"stage": stage},
        )
        return failed
    except Exception:
        # Preserve the original execution error. A persistence failure here will
        # still surface through the original exception chain and server logs.
        return run


def start_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str | None = None,
    goal_id: str | None = None,
) -> RunStartResult:
    """Create and synchronously advance a Run to approval or completion.

    The function records only deterministic, replayable steps. If proposals are
    present, it stops at ``waiting_approval`` and never applies them automatically.
    """

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
        detail={"dataset_id": dataset.id, "version_id": version.id},
    )

    stage = "context_building"
    try:
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

        stage = "profiling"
        run = _transition_run(
            run_store,
            run,
            status="profiling",
            current_stage=stage,
        )
        profile = generate_dataset_version_profile(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
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
        run = _transition_run(
            run_store,
            run,
            status="planning",
            current_stage=stage,
        )
        proposals = generate_cleaning_proposals_for_version(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
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
            run = _transition_run(
                run_store,
                run,
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
        else:
            run = _transition_run(
                run_store,
                run,
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

        return RunStartResult(
            run=run,
            steps=run_store.list_steps(run.id),
            profile=profile,
            proposals=proposals,
        )
    except (InsightProfileError, InsightCleaningError, DomainStoreError) as exc:
        _record_failure(run_store, run, stage=stage, message=str(exc))
        raise InsightRunError(str(exc)) from exc
    except Exception as exc:
        _record_failure(
            run_store,
            run,
            stage=stage,
            message="The deterministic analysis run failed unexpectedly.",
        )
        raise InsightRunError(
            "The deterministic analysis run failed unexpectedly."
        ) from exc


def get_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
) -> RunSnapshot:
    run_store = RunStore(store, workspace_id=workspace_id)
    try:
        run = run_store.require(run_id)
        return RunSnapshot(
            run=run,
            steps=run_store.list_steps(run.id),
            final_summary=run_store.read_final_summary(run.id),
        )
    except DomainObjectNotFoundError as exc:
        raise InsightRunNotFoundError(str(exc)) from exc
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc


def cancel_agent_run(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
    reason: str = "Cancelled by user",
) -> RunSnapshot:
    run_store = RunStore(store, workspace_id=workspace_id)
    try:
        run = run_store.require(run_id)
    except DomainObjectNotFoundError as exc:
        raise InsightRunNotFoundError(str(exc)) from exc
    except DomainStoreError as exc:
        raise InsightRunError(str(exc)) from exc

    if run.status == "cancelled":
        return get_agent_run(
            store,
            workspace_id=workspace_id,
            run_id=run.id,
        )
    if run.status in {"completed", "failed"}:
        raise InsightRunConflictError(
            f"AgentRun in terminal state '{run.status}' cannot be cancelled"
        )

    cancelled = _transition_run(
        run_store,
        run,
        status="cancelled",
        current_stage="cancelled",
        completed=True,
    )
    _append_step(
        run_store,
        cancelled,
        step_type="progress",
        title="Analysis run cancelled",
        status="cancelled",
        progress_text=reason.strip() or "Cancelled by user",
        detail={"reason": reason.strip() or "Cancelled by user"},
    )
    return get_agent_run(
        store,
        workspace_id=workspace_id,
        run_id=cancelled.id,
    )
