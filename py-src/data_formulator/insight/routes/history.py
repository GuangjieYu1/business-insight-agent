"""Dataset operation history and Profile comparison routes."""

from __future__ import annotations

from flask import request

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.history import (
    InsightHistoryError,
    compare_dataset_version_profiles,
    list_dataset_operations,
    read_dataset_operation,
)

from .project import insight_project_bp, _store_for, _workspace_context, _workspace_id


def _history_error(exc: InsightHistoryError) -> AppError:
    message = str(exc)
    code = ErrorCode.TABLE_NOT_FOUND if "not found" in message.lower() else ErrorCode.INVALID_REQUEST
    return AppError(code, message)


@insight_project_bp.route("/datasets/<dataset_id>/operations", methods=["GET"])
def list_dataset_operations_route(dataset_id: str):
    _, workspace = _workspace_context()
    try:
        operations = list_dataset_operations(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
        )
    except InsightHistoryError as exc:
        raise _history_error(exc) from exc
    return json_ok(
        {"operations": [operation.model_dump(mode="json") for operation in operations]}
    )


@insight_project_bp.route(
    "/datasets/<dataset_id>/operations/<operation_id>",
    methods=["GET"],
)
def get_dataset_operation_route(dataset_id: str, operation_id: str):
    _, workspace = _workspace_context()
    try:
        operation = read_dataset_operation(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            operation_id=operation_id,
        )
    except InsightHistoryError as exc:
        raise _history_error(exc) from exc
    if operation is None:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, f"Operation not found: {operation_id}")
    return json_ok({"operation": operation.model_dump(mode="json")})


@insight_project_bp.route(
    "/datasets/<dataset_id>/profiles/compare",
    methods=["GET"],
)
def compare_dataset_profiles_route(dataset_id: str):
    _, workspace = _workspace_context()
    before_version_id = request.args.get("beforeVersionId") or request.args.get(
        "before_version_id"
    )
    after_version_id = request.args.get("afterVersionId") or request.args.get(
        "after_version_id"
    )
    if not before_version_id or not after_version_id:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "beforeVersionId and afterVersionId are required",
        )
    try:
        comparison = compare_dataset_version_profiles(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            before_version_id=before_version_id,
            after_version_id=after_version_id,
        )
    except InsightHistoryError as exc:
        raise _history_error(exc) from exc

    return json_ok(
        {
            **comparison,
            "beforeProfile": comparison["beforeProfile"].model_dump(mode="json"),
            "afterProfile": comparison["afterProfile"].model_dump(mode="json"),
            "resolvedIssues": [
                issue.model_dump(mode="json") for issue in comparison["resolvedIssues"]
            ],
            "introducedIssues": [
                issue.model_dump(mode="json")
                for issue in comparison["introducedIssues"]
            ],
            "unchangedIssues": [
                {
                    "before": item["before"].model_dump(mode="json"),
                    "after": item["after"].model_dump(mode="json"),
                }
                for item in comparison["unchangedIssues"]
            ],
        }
    )
