"""Apply cleaning operations and analyze their immutable output versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_formulator.insight.cleaning import InsightCleaningError
from data_formulator.insight.cleaning_operations import (
    CleaningApplyResult,
    apply_cleaning_proposal,
)
from data_formulator.insight.domain import CleaningProposal, DatasetProfile
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.storage import InsightStore
from data_formulator.insight.version_cleaning import generate_cleaning_proposals_for_version
from data_formulator.insight.version_profiling import generate_dataset_version_profile


@dataclass(frozen=True)
class CleaningOutputAnalysisResult:
    apply_result: CleaningApplyResult
    profile: DatasetProfile | None
    next_proposals: list[CleaningProposal]
    profile_status: str
    proposal_status: str
    warnings: list[str] = field(default_factory=list)


def apply_cleaning_proposal_with_output_analysis(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
    operation_type: str | None = None,
    parameters: dict[str, Any] | None = None,
    reason: str | None = None,
) -> CleaningOutputAnalysisResult:
    """Apply a proposal, then profile and propose against its output version.

    Cleaning/version creation is the primary transaction. Output analysis is
    best-effort and never rolls back an already-created immutable version.
    Repeated idempotent Apply calls also repair missing output analysis.
    """

    applied = apply_cleaning_proposal(
        store,
        workspace_id=workspace_id,
        proposal_id=proposal_id,
        operation_type=operation_type,
        parameters=parameters,
        reason=reason,
    )

    warnings: list[str] = []
    try:
        profile = generate_dataset_version_profile(
            store,
            workspace_id=workspace_id,
            dataset_id=applied.dataset.id,
            version_id=applied.version.id,
        )
    except InsightProfileError as exc:
        warnings.append(f"Output version profile failed: {exc}")
        return CleaningOutputAnalysisResult(
            apply_result=applied,
            profile=None,
            next_proposals=[],
            profile_status="failed",
            proposal_status="skipped",
            warnings=warnings,
        )

    try:
        proposals = generate_cleaning_proposals_for_version(
            store,
            workspace_id=workspace_id,
            dataset_id=applied.dataset.id,
            version_id=applied.version.id,
        )
    except InsightCleaningError as exc:
        warnings.append(f"Output version proposal generation failed: {exc}")
        return CleaningOutputAnalysisResult(
            apply_result=applied,
            profile=profile,
            next_proposals=[],
            profile_status="completed",
            proposal_status="failed",
            warnings=warnings,
        )

    return CleaningOutputAnalysisResult(
        apply_result=applied,
        profile=profile,
        next_proposals=proposals,
        profile_status="completed",
        proposal_status="completed",
        warnings=warnings,
    )
