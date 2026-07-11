"""Business Insight project and dataset registration routes."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, request

from data_formulator.auth.identity import get_identity_id
from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
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
    return request.headers.get("X-Workspace-Id") or workspace.confined_root.root.name


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
