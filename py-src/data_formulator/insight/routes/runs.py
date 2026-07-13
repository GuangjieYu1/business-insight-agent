"""Business Insight AgentRun REST and SSE routes."""

from __future__ import annotations

from typing import Any

from flask import Response, request, stream_with_context

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.background_runs import (
    create_background_agent_run,
    launch_background_agent_run,
    list_agent_runs,
)
from data_formulator.insight.run_events import (
    events_after_cursor,
    parse_event_cursor,
    project_run_events,
    stream_agent_run_events,
)
from data_formulator.insight.run_service import (
    InsightRunConflictError,
    InsightRunError,
    InsightRunNotFoundError,
    cancel_agent_run,
    get_agent_run,
    start_agent_run,
)

from .project import (
    _json_body,
    _store_for,
    _workspace_context,
    _workspace_id,
    insight_project_bp,
)


def _optional_string(payload: dict[str, Any], camel_key: str, snake_key: str) -> str | None:
    value = payload.get(camel_key)
    if value is None:
        value = payload.get(snake_key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, f"{camel_key} must be a non-empty string")
    return value.strip()


def _run_error(exc: InsightRunError) -> AppError:
    if isinstance(exc, InsightRunNotFoundError):
        return AppError(ErrorCode.TABLE_NOT_FOUND, str(exc))
    if isinstance(exc, InsightRunConflictError):
        return AppError(ErrorCode.VALIDATION_ERROR, str(exc))
    return AppError(ErrorCode.AGENT_ERROR, str(exc))


def _snapshot_payload(snapshot) -> dict[str, Any]:
    return {
        "run": snapshot.run.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in snapshot.steps],
        "finalSummary": (
            snapshot.final_summary.model_dump(mode="json")
            if snapshot.final_summary is not None
            else None
        ),
    }


@insight_project_bp.route("/runs", methods=["GET"])
def list_agent_runs_route():
    _, workspace = _workspace_context()
    dataset_id = request.args.get("datasetId") or request.args.get("dataset_id")
    if dataset_id is not None and not dataset_id.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "datasetId must be a non-empty string")
    try:
        runs = list_agent_runs(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id.strip() if dataset_id else None,
        )
    except InsightRunError as exc:
        raise _run_error(exc) from exc
    return json_ok({"runs": [run.model_dump(mode="json") for run in runs]})


@insight_project_bp.route("/runs", methods=["POST"])
def create_agent_run_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    dataset_id = _optional_string(payload, "datasetId", "dataset_id")
    if dataset_id is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "datasetId is required")

    execution_mode = payload.get("executionMode") or payload.get("execution_mode") or "synchronous"
    if execution_mode not in {"synchronous", "background"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "executionMode must be 'synchronous' or 'background'",
        )

    store = _store_for(workspace)
    workspace_id = _workspace_id(workspace)
    version_id = _optional_string(payload, "versionId", "version_id")
    goal_id = _optional_string(payload, "goalId", "goal_id")
    if goal_id is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "goalId is required")

    try:
        if execution_mode == "background":
            created = create_background_agent_run(
                store,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                version_id=version_id,
                goal_id=goal_id,
            )
            launch_background_agent_run(
                store,
                workspace_id=workspace_id,
                run_id=created.run.id,
            )
            return json_ok(
                {
                    "run": created.run.model_dump(mode="json"),
                    "steps": [step.model_dump(mode="json") for step in created.steps],
                    "finalSummary": None,
                    "profile": None,
                    "proposals": [],
                    "executionMode": "background",
                }
            )

        result = start_agent_run(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            version_id=version_id,
            goal_id=goal_id,
        )
    except InsightRunError as exc:
        raise _run_error(exc) from exc

    return json_ok(
        {
            "run": result.run.model_dump(mode="json"),
            "steps": [step.model_dump(mode="json") for step in result.steps],
            "finalSummary": None,
            "profile": result.profile.model_dump(mode="json"),
            "proposals": [
                proposal.model_dump(mode="json") for proposal in result.proposals
            ],
            "executionMode": "synchronous",
        }
    )


@insight_project_bp.route("/runs/<run_id>", methods=["GET"])
def get_agent_run_route(run_id: str):
    _, workspace = _workspace_context()
    try:
        snapshot = get_agent_run(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            run_id=run_id,
        )
    except InsightRunError as exc:
        raise _run_error(exc) from exc
    return json_ok(_snapshot_payload(snapshot))


@insight_project_bp.route("/runs/<run_id>/steps", methods=["GET"])
def get_agent_run_steps_route(run_id: str):
    _, workspace = _workspace_context()
    try:
        snapshot = get_agent_run(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            run_id=run_id,
        )
    except InsightRunError as exc:
        raise _run_error(exc) from exc
    return json_ok(
        {
            "runId": snapshot.run.id,
            "steps": [step.model_dump(mode="json") for step in snapshot.steps],
        }
    )


@insight_project_bp.route("/runs/<run_id>/events", methods=["GET"])
def stream_agent_run_events_route(run_id: str):
    _, workspace = _workspace_context()
    store = _store_for(workspace)
    workspace_id = _workspace_id(workspace)

    cursor_value = (
        request.headers.get("Last-Event-ID")
        or request.args.get("afterEventId")
        or request.args.get("after_event_id")
    )
    try:
        after_event_id = parse_event_cursor(cursor_value)
    except ValueError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    try:
        # Validate ownership, existence, and cursor before streaming begins so
        # protocol errors retain the normal JSON error envelope.
        snapshot = get_agent_run(
            store,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        events_after_cursor(project_run_events(snapshot), after_event_id)
    except InsightRunError as exc:
        raise _run_error(exc) from exc
    except ValueError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    def generate():
        yield "retry: 3000\n\n"
        yield from stream_agent_run_events(
            store,
            workspace_id=workspace_id,
            run_id=run_id,
            after_event_id=after_event_id,
        )

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@insight_project_bp.route("/runs/<run_id>/cancel", methods=["POST"])
def cancel_agent_run_route(run_id: str):
    _, workspace = _workspace_context()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "JSON object body is required")
    reason = payload.get("reason") or "Cancelled by user"
    if not isinstance(reason, str):
        raise AppError(ErrorCode.INVALID_REQUEST, "reason must be a string")

    try:
        snapshot = cancel_agent_run(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            run_id=run_id,
            reason=reason,
        )
    except InsightRunError as exc:
        raise _run_error(exc) from exc
    return json_ok(_snapshot_payload(snapshot))
