"""Business Insight project, dataset, profiling, and versioning routes."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, request
from werkzeug.utils import secure_filename

from data_formulator.auth.identity import get_identity_id
from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.cleaning import (
    InsightCleaningError,
    generate_cleaning_proposals,
    list_cleaning_proposals,
)
from data_formulator.insight.profiling import (
    InsightProfileError,
    InsightProfileNotFoundError,
    generate_dataset_profile,
    read_dataset_profile,
)
from data_formulator.insight.registry import (
    InsightAlreadyRegisteredError,
    InsightRegistryError,
    ensure_project,
    list_datasets,
    read_dataset,
    read_dataset_version_zero,
    read_project,
    register_dataset_version_zero,
)
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import (
    InsightVersioningError,
    activate_dataset_version,
    list_dataset_versions,
    undo_dataset_version_by_operation,
)
from data_formulator.workspace_factory import get_workspace

insight_project_bp = Blueprint("insight_project", __name__, url_prefix="/api/insight")


def _json_body() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "JSON object body is required")
    return payload


def _workspace_context() -> tuple[str, Workspace]:
    try:
        identity_id = get_identity_id()
        return identity_id, get_workspace(identity_id)
    except ValueError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc


def _workspace_id(workspace: Workspace) -> str:
    server_workspace_id = workspace.confined_root.root.name
    supplied_workspace_id = request.headers.get("X-Workspace-Id")
    if supplied_workspace_id:
        supplied_safe_id = secure_filename(supplied_workspace_id)
        if supplied_safe_id != server_workspace_id:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "X-Workspace-Id does not match the active workspace",
            )
    return server_workspace_id


def _optional_bool(payload: dict[str, Any], camel_key: str, snake_key: str) -> bool:
    value = payload.get(camel_key)
    if value is None:
        value = payload.get(snake_key)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise AppError(ErrorCode.INVALID_REQUEST, f"{camel_key} must be a boolean")


def _store_for(workspace: Workspace) -> LocalInsightStore:
    return LocalInsightStore(workspace.confined_root.root)


@insight_project_bp.route("/project", methods=["GET"])
def get_project_route():
    _, workspace = _workspace_context()
    project = read_project(_store_for(workspace))
    if project is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "No Business Insight project registered")
    return json_ok({"project": project.model_dump(mode="json")})


@insight_project_bp.route("/project", methods=["POST"])
def ensure_project_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    registration = ensure_project(
        _store_for(workspace),
        workspace_id=_workspace_id(workspace),
        name=payload.get("name") or payload.get("projectName") or "Business Insight Project",
        description=payload.get("description") or "",
        default_language=payload.get("defaultLanguage") or payload.get("default_language") or "zh-CN",
    )
    return json_ok(
        {
            "project": registration.project.model_dump(mode="json"),
            "created": registration.created,
        }
    )


@insight_project_bp.route("/datasets", methods=["GET"])
def list_datasets_route():
    _, workspace = _workspace_context()
    datasets = list_datasets(_store_for(workspace))
    return json_ok({"datasets": [dataset.model_dump(mode="json") for dataset in datasets]})


@insight_project_bp.route("/datasets", methods=["POST"])
def register_dataset_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    table_name = payload.get("tableName") or payload.get("table_name")
    if not isinstance(table_name, str) or not table_name.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "tableName is required")

    try:
        dataframe = workspace.read_data_as_df(table_name)
        table_meta = workspace.get_table_metadata(table_name)
        dataset_name = payload.get("datasetName") or payload.get("dataset_name")
        if not dataset_name and table_meta is not None:
            dataset_name = table_meta.original_name or table_meta.name
        registration = register_dataset_version_zero(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataframe=dataframe,
            original_table_ref=table_meta.name if table_meta is not None else table_name,
            dataset_name=dataset_name,
            dataset_id=payload.get("datasetId") or payload.get("dataset_id"),
            source_material_id=payload.get("sourceMaterialId") or payload.get("source_material_id"),
            project_name=payload.get("projectName") or payload.get("project_name") or "Business Insight Project",
            allow_duplicate=_optional_bool(payload, "allowDuplicate", "allow_duplicate"),
        )
    except FileNotFoundError as exc:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
    except InsightAlreadyRegisteredError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    except InsightRegistryError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    return json_ok(
        {
            "project": registration.project.model_dump(mode="json"),
            "dataset": registration.dataset.model_dump(mode="json"),
            "version": registration.version.model_dump(mode="json"),
            "created": registration.created,
        }
    )


@insight_project_bp.route("/datasets/<dataset_id>", methods=["GET"])
def get_dataset_route(dataset_id: str):
    _, workspace = _workspace_context()
    store = _store_for(workspace)
    try:
        dataset = read_dataset(store, dataset_id)
        version = read_dataset_version_zero(store, dataset_id)
    except InsightRegistryError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    if dataset is None:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, f"Dataset not found: {dataset_id}")
    return json_ok(
        {
            "dataset": dataset.model_dump(mode="json"),
            "originalVersion": version.model_dump(mode="json") if version else None,
        }
    )


@insight_project_bp.route("/datasets/<dataset_id>/versions", methods=["GET"])
def list_dataset_versions_route(dataset_id: str):
    _, workspace = _workspace_context()
    store = _store_for(workspace)
    try:
        dataset = read_dataset(store, dataset_id)
        if dataset is None:
            raise AppError(ErrorCode.TABLE_NOT_FOUND, f"Dataset not found: {dataset_id}")
        versions = list_dataset_versions(store, dataset_id)
    except InsightRegistryError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    return json_ok(
        {
            "dataset": dataset.model_dump(mode="json"),
            "versions": [version.model_dump(mode="json") for version in versions],
            "activeVersionId": dataset.active_version_id,
        }
    )


@insight_project_bp.route("/datasets/<dataset_id>/activate-version", methods=["POST"])
def activate_dataset_version_route(dataset_id: str):
    _, workspace = _workspace_context()
    payload = _json_body()
    version_id = payload.get("versionId") or payload.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "versionId is required")

    try:
        activation = activate_dataset_version(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
            reason=payload.get("reason") or "Activate dataset version",
        )
    except InsightVersioningError as exc:
        message = str(exc)
        error_code = ErrorCode.TABLE_NOT_FOUND if "not found" in message.lower() else ErrorCode.INVALID_REQUEST
        raise AppError(error_code, message) from exc

    return json_ok(
        {
            "dataset": activation.dataset.model_dump(mode="json"),
            "activeVersion": activation.active_version.model_dump(mode="json"),
            "previousVersion": activation.previous_version.model_dump(mode="json") if activation.previous_version else None,
            "operation": activation.operation.model_dump(mode="json"),
        }
    )


@insight_project_bp.route("/operations/<operation_id>/undo", methods=["POST"])
def undo_operation_route(operation_id: str):
    _, workspace = _workspace_context()
    payload = _json_body()

    try:
        activation = undo_dataset_version_by_operation(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            operation_id=operation_id,
            reason=payload.get("reason") or "Undo dataset operation",
        )
    except InsightVersioningError as exc:
        message = str(exc)
        error_code = ErrorCode.TABLE_NOT_FOUND if "not found" in message.lower() else ErrorCode.INVALID_REQUEST
        raise AppError(error_code, message) from exc

    return json_ok(
        {
            "dataset": activation.dataset.model_dump(mode="json"),
            "activeVersion": activation.active_version.model_dump(mode="json"),
            "previousVersion": activation.previous_version.model_dump(mode="json") if activation.previous_version else None,
            "operation": activation.operation.model_dump(mode="json"),
            "undoneOperation": activation.undone_operation.model_dump(mode="json") if activation.undone_operation else None,
        }
    )


@insight_project_bp.route("/cleaning/proposals", methods=["GET"])
def list_cleaning_proposals_route():
    _, workspace = _workspace_context()
    dataset_id = request.args.get("datasetId") or request.args.get("dataset_id")
    version_id = request.args.get("versionId") or request.args.get("version_id")
    proposals = list_cleaning_proposals(
        _store_for(workspace),
        dataset_id=dataset_id,
        version_id=version_id,
    )
    return json_ok({"proposals": [proposal.model_dump(mode="json") for proposal in proposals]})


@insight_project_bp.route("/cleaning/proposals", methods=["POST"])
def generate_cleaning_proposals_route():
    _, workspace = _workspace_context()
    payload = _json_body()
    dataset_id = payload.get("datasetId") or payload.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "datasetId is required")
    version_id = payload.get("versionId") or payload.get("version_id") or "version_000"
    if not isinstance(version_id, str) or not version_id.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "versionId must be a string")

    try:
        proposals = generate_cleaning_proposals(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
        )
    except InsightCleaningError as exc:
        message = str(exc)
        error_code = ErrorCode.TABLE_NOT_FOUND if "not found" in message.lower() else ErrorCode.INVALID_REQUEST
        raise AppError(error_code, message) from exc

    return json_ok({"proposals": [proposal.model_dump(mode="json") for proposal in proposals]})


@insight_project_bp.route("/datasets/<dataset_id>/profile", methods=["POST"])
def generate_dataset_profile_route(dataset_id: str):
    _, workspace = _workspace_context()
    try:
        profile = generate_dataset_profile(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
        )
    except InsightProfileNotFoundError as exc:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
    except InsightProfileError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    return json_ok({"profile": profile.model_dump(mode="json")})


@insight_project_bp.route("/datasets/<dataset_id>/profiles/version_000", methods=["GET"])
def get_dataset_profile_route(dataset_id: str):
    _, workspace = _workspace_context()
    workspace_id = _workspace_id(workspace)
    try:
        profile = read_dataset_profile(_store_for(workspace), dataset_id=dataset_id)
    except InsightProfileNotFoundError as exc:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
    except InsightProfileError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    if profile is None:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, f"Dataset profile not found: {dataset_id}/version_000")
    if profile.workspace_id != workspace_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "Profile workspace_id does not match active workspace")
    return json_ok({"profile": profile.model_dump(mode="json")})