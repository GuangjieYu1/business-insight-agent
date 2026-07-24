"""Business Insight intent and goal routes."""

from __future__ import annotations

from typing import Any

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.goal_service import (
    InsightGoalConflictError,
    InsightGoalError,
    InsightGoalNotFoundError,
    InsightIntentNotFoundError,
    create_analysis_goal,
    create_intent_request,
    get_analysis_goal,
    get_intent_snapshot,
    update_analysis_goal,
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


def _goal_error(exc: InsightGoalError) -> AppError:
    if isinstance(exc, (InsightIntentNotFoundError, InsightGoalNotFoundError)):
        return AppError(ErrorCode.TABLE_NOT_FOUND, str(exc))
    if isinstance(exc, InsightGoalConflictError):
        return AppError(ErrorCode.VALIDATION_ERROR, str(exc))
    return AppError(ErrorCode.INVALID_REQUEST, str(exc))


@insight_project_bp.route("/intents", methods=["POST"])
def create_intent_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    dataset_id = _optional_string(payload, "datasetId", "dataset_id")
    user_input = _optional_string(payload, "userInput", "user_input")
    if dataset_id is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "datasetId is required")
    if user_input is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "userInput is required")

    goal_candidates = payload["goalCandidates"] if "goalCandidates" in payload else payload.get("goal_candidates")
    try:
        snapshot = create_intent_request(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            dataset_version_id=_optional_string(payload, "datasetVersionId", "dataset_version_id"),
            user_input=user_input,
            goal_candidates=goal_candidates,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc

    return json_ok(
        {
            "intent": snapshot.intent.model_dump(mode="json"),
            "goalCandidates": [candidate.model_dump(mode="json") for candidate in snapshot.goal_candidates],
            "questions": [question.model_dump(mode="json", by_alias=True) for question in snapshot.questions],
        }
    )


@insight_project_bp.route("/intents/<intent_id>", methods=["GET"])
def get_intent_route(intent_id: str):
    _, workspace = _workspace_context()
    try:
        snapshot = get_intent_snapshot(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            intent_id=intent_id,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc
    return json_ok(
        {
            "intent": snapshot.intent.model_dump(mode="json"),
            "goalCandidates": [candidate.model_dump(mode="json") for candidate in snapshot.goal_candidates],
            "questions": [question.model_dump(mode="json", by_alias=True) for question in snapshot.questions],
        }
    )


@insight_project_bp.route("/intents/<intent_id>/goal-candidates", methods=["GET"])
def list_goal_candidates_route(intent_id: str):
    _, workspace = _workspace_context()
    try:
        snapshot = get_intent_snapshot(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            intent_id=intent_id,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc
    return json_ok(
        {
            "intent": snapshot.intent.model_dump(mode="json"),
            "goalCandidates": [candidate.model_dump(mode="json") for candidate in snapshot.goal_candidates],
            "questions": [question.model_dump(mode="json", by_alias=True) for question in snapshot.questions],
        }
    )


@insight_project_bp.route("/goals", methods=["POST"])
def create_goal_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    dataset_id = _optional_string(payload, "datasetId", "dataset_id")
    if dataset_id is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "datasetId is required")
    try:
        result = create_analysis_goal(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            dataset_version_id=_optional_string(payload, "datasetVersionId", "dataset_version_id"),
            payload=payload,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc
    return json_ok(
        {
            "goal": result.goal.model_dump(mode="json"),
            "project": result.project.model_dump(mode="json"),
            "created": result.created,
        }
    )


@insight_project_bp.route("/goals/<goal_id>", methods=["GET"])
def get_goal_route(goal_id: str):
    _, workspace = _workspace_context()
    try:
        goal = get_analysis_goal(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            goal_id=goal_id,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc
    return json_ok({"goal": goal.model_dump(mode="json")})


@insight_project_bp.route("/goals/<goal_id>", methods=["PATCH"])
def update_goal_route(goal_id: str):
    _, workspace = _workspace_context()
    payload = _json_body()
    try:
        result = update_analysis_goal(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            goal_id=goal_id,
            payload=payload,
        )
    except InsightGoalError as exc:
        raise _goal_error(exc) from exc
    return json_ok(
        {
            "goal": result.goal.model_dump(mode="json"),
            "project": result.project.model_dump(mode="json"),
            "created": result.created,
        }
    )