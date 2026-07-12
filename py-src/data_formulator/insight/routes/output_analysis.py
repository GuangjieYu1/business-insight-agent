"""Cleaning Apply route with best-effort output-version analysis."""

from __future__ import annotations

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.insight.cleaning_operations import InsightCleaningOperationError
from data_formulator.insight.output_analysis import (
    apply_cleaning_proposal_with_output_analysis,
)
from data_formulator.insight.versioning import InsightVersioningError

from .project import (
    _cleaning_error,
    _json_body,
    _store_for,
    _workspace_context,
    _workspace_id,
    insight_project_bp,
)


@insight_project_bp.route(
    "/cleaning/proposals/<proposal_id>/apply-with-analysis",
    methods=["POST"],
)
def apply_cleaning_proposal_with_analysis_route(proposal_id: str):
    _, workspace = _workspace_context()
    payload = _json_body()
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "parameters must be an object")

    try:
        result = apply_cleaning_proposal_with_output_analysis(
            _store_for(workspace),
            workspace_id=_workspace_id(workspace),
            proposal_id=proposal_id,
            operation_type=payload.get("operationType") or payload.get("operation_type"),
            parameters=parameters,
            reason=payload.get("reason"),
        )
    except InsightCleaningOperationError as exc:
        raise _cleaning_error(exc) from exc
    except InsightVersioningError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    applied = result.apply_result
    return json_ok(
        {
            "proposal": applied.proposal.model_dump(mode="json"),
            "dataset": applied.dataset.model_dump(mode="json"),
            "version": applied.version.model_dump(mode="json"),
            "operation": applied.operation.model_dump(mode="json"),
            "idempotent": applied.idempotent,
            "profile": result.profile.model_dump(mode="json") if result.profile else None,
            "nextProposals": [
                proposal.model_dump(mode="json") for proposal in result.next_proposals
            ],
            "postProcessing": {
                "profileStatus": result.profile_status,
                "proposalStatus": result.proposal_status,
                "warnings": result.warnings,
            },
        }
    )
