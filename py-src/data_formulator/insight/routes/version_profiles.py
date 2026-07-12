"""Version-specific Business Insight profiling and cleaning proposal routes."""

from __future__ import annotations

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.cleaning import InsightCleaningError
from data_formulator.insight.profiling import InsightProfileError, InsightProfileNotFoundError
from data_formulator.insight.version_cleaning import (
    generate_cleaning_proposals_for_version,
    list_cleaning_proposals_for_version,
)
from data_formulator.insight.version_profiling import (
    generate_dataset_version_profile,
    read_dataset_version_profile,
)

from .project import insight_project_bp, _store_for, _workspace_context, _workspace_id


def _cleaning_error(exc: InsightCleaningError) -> AppError:
    message = str(exc)
    error_code = ErrorCode.TABLE_NOT_FOUND if "not found" in message.lower() else ErrorCode.INVALID_REQUEST
    return AppError(error_code, message)


@insight_project_bp.route(
    "/datasets/<dataset_id>/versions/<version_id>/profile",
    methods=["POST"],
)
def generate_dataset_version_profile_route(dataset_id: str, version_id: str):
    _, workspace = _workspace_context()
    try:
        profile = generate_dataset_version_profile(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
        )
    except InsightProfileNotFoundError as exc:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
    except InsightProfileError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    return json_ok({"profile": profile.model_dump(mode="json")})


@insight_project_bp.route(
    "/datasets/<dataset_id>/versions/<version_id>/profile",
    methods=["GET"],
)
def get_dataset_version_profile_route(dataset_id: str, version_id: str):
    _, workspace = _workspace_context()
    try:
        profile = read_dataset_version_profile(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
        )
    except InsightProfileNotFoundError as exc:
        raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
    except InsightProfileError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    if profile is None:
        raise AppError(
            ErrorCode.TABLE_NOT_FOUND,
            f"Dataset profile not found: {dataset_id}/{version_id}",
        )
    return json_ok({"profile": profile.model_dump(mode="json")})


@insight_project_bp.route(
    "/datasets/<dataset_id>/versions/<version_id>/cleaning/proposals",
    methods=["GET"],
)
def list_dataset_version_cleaning_proposals_route(dataset_id: str, version_id: str):
    _, workspace = _workspace_context()
    try:
        proposals = list_cleaning_proposals_for_version(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
        )
    except InsightCleaningError as exc:
        raise _cleaning_error(exc) from exc
    return json_ok({"proposals": [proposal.model_dump(mode="json") for proposal in proposals]})


@insight_project_bp.route(
    "/datasets/<dataset_id>/versions/<version_id>/cleaning/proposals",
    methods=["POST"],
)
def generate_dataset_version_cleaning_proposals_route(dataset_id: str, version_id: str):
    _, workspace = _workspace_context()
    try:
        proposals = generate_cleaning_proposals_for_version(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            dataset_id=dataset_id,
            version_id=version_id,
        )
    except InsightCleaningError as exc:
        raise _cleaning_error(exc) from exc
    return json_ok({"proposals": [proposal.model_dump(mode="json") for proposal in proposals]})
