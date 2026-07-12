"""Version-aware deterministic cleaning proposal generation."""

from __future__ import annotations

from data_formulator.insight.cleaning import (
    InsightCleaningError,
    _proposal_from_issue,
    _proposal_path,
    list_cleaning_proposals,
)
from data_formulator.insight.domain import CleaningProposal
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.registry import InsightRegistryError, read_dataset, read_dataset_version
from data_formulator.insight.storage import InsightStore
from data_formulator.insight.version_profiling import (
    generate_dataset_version_profile,
    read_dataset_version_profile,
)


def generate_cleaning_proposals_for_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
) -> list[CleaningProposal]:
    """Generate deterministic proposals for the exact requested dataset version.

    Existing proposals are reused so approval, rejection, and applied states are
    never reset by a repeated generation request.
    """

    try:
        dataset = read_dataset(store, dataset_id)
        version = read_dataset_version(store, dataset_id, version_id)
    except InsightRegistryError as exc:
        raise InsightCleaningError(str(exc)) from exc

    if dataset is None:
        raise InsightCleaningError(f"Dataset not found: {dataset_id}")
    if version is None:
        raise InsightCleaningError(f"Dataset version not found: {dataset_id}/{version_id}")
    if dataset.workspace_id != workspace_id or version.workspace_id != workspace_id:
        raise InsightCleaningError("Dataset workspace_id does not match active workspace")
    if version.dataset_id != dataset.id:
        raise InsightCleaningError("Dataset version metadata is inconsistent")

    try:
        profile = read_dataset_version_profile(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            version_id=version_id,
        )
        if profile is None:
            profile = generate_dataset_version_profile(
                store,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                version_id=version_id,
            )
    except InsightProfileError as exc:
        raise InsightCleaningError(str(exc)) from exc

    columns_by_name = {column.name: column for column in profile.columns}
    generated: list[CleaningProposal] = []
    for issue in profile.quality_issues:
        proposal = _proposal_from_issue(
            dataset_id=dataset_id,
            version_id=version_id,
            profile=profile,
            issue=issue,
            columns_by_name=columns_by_name,
        )
        if proposal is not None:
            generated.append(proposal)

    proposals: list[CleaningProposal] = []
    with store.workspace_lock():
        for proposal in generated:
            path = _proposal_path(proposal.id)
            if store.exists(path):
                existing = store.read_model(path, CleaningProposal)
                if existing.workspace_id != workspace_id:
                    raise InsightCleaningError(
                        "Cleaning proposal workspace_id does not match active workspace"
                    )
                if existing.scope.get("dataset_id") != dataset_id:
                    raise InsightCleaningError(
                        "Cleaning proposal dataset metadata is inconsistent"
                    )
                if existing.dataset_version_id != version_id:
                    raise InsightCleaningError(
                        "Cleaning proposal version metadata is inconsistent"
                    )
                proposals.append(existing)
                continue
            store.write_json(path, proposal)
            proposals.append(proposal)

    return proposals


def list_cleaning_proposals_for_version(
    store: InsightStore,
    *,
    dataset_id: str,
    version_id: str,
) -> list[CleaningProposal]:
    return list_cleaning_proposals(
        store,
        dataset_id=dataset_id,
        version_id=version_id,
    )
