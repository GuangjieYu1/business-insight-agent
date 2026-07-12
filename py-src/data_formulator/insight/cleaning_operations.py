"""Preview, approve, and apply deterministic reversible cleaning operations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

import pandas as pd

from data_formulator.insight.domain import CleaningOperation, CleaningProposal, Dataset, DatasetVersion
from data_formulator.insight.domain.models import utc_now
from data_formulator.insight.registry import read_dataset, read_dataset_version
from data_formulator.insight.storage import InsightStore
from data_formulator.insight.versioning import create_dataset_version


class InsightCleaningOperationError(ValueError):
    """Raised when a cleaning operation cannot be previewed or applied safely."""


@dataclass(frozen=True)
class CleaningPreviewResult:
    proposal: CleaningProposal
    operation: CleaningOperation
    warnings: list[str]
    sample_diff: list[dict[str, Any]]


@dataclass(frozen=True)
class CleaningApplyResult:
    proposal: CleaningProposal
    dataset: Dataset
    version: DatasetVersion
    operation: CleaningOperation
    idempotent: bool = False


SUPPORTED_OPERATIONS = {
    "drop_column",
    "drop_duplicate_rows",
    "rename_column",
    "replace_invalid_character",
    "trim_string",
}

_DESTRUCTIVE_OPERATIONS = {"drop_column", "drop_duplicate_rows"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DIRTY_CHARACTER_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFD]")


def _proposal_path(proposal_id: str) -> str:
    return f"proposals/{proposal_id}.json"


def _operation_path(operation_id: str) -> str:
    return f"operations/{operation_id}.json"


def _validate_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or not _ID_RE.fullmatch(normalized):
        raise InsightCleaningOperationError(f"Invalid {field_name}: {value!r}")
    return normalized


def read_cleaning_proposal(store: InsightStore, proposal_id: str) -> CleaningProposal | None:
    proposal_id = _validate_id(proposal_id, "proposal_id")
    path = _proposal_path(proposal_id)
    if not store.exists(path):
        return None
    return store.read_model(path, CleaningProposal)


def _require_proposal(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
) -> CleaningProposal:
    proposal = read_cleaning_proposal(store, proposal_id)
    if proposal is None:
        raise InsightCleaningOperationError(f"Cleaning proposal not found: {proposal_id}")
    if proposal.workspace_id != workspace_id:
        raise InsightCleaningOperationError("Cleaning proposal workspace_id does not match active workspace")
    return proposal


def _dataset_id(proposal: CleaningProposal) -> str:
    dataset_id = proposal.scope.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise InsightCleaningOperationError("Cleaning proposal is missing dataset_id metadata")
    return _validate_id(dataset_id, "dataset_id")


def _require_dataset_and_version(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal: CleaningProposal,
    require_active: bool,
) -> tuple[Dataset, DatasetVersion]:
    dataset_id = _dataset_id(proposal)
    dataset = read_dataset(store, dataset_id)
    if dataset is None:
        raise InsightCleaningOperationError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightCleaningOperationError("Dataset workspace_id does not match active workspace")

    version = read_dataset_version(store, dataset.id, proposal.dataset_version_id)
    if version is None:
        raise InsightCleaningOperationError(
            f"Dataset version not found: {dataset.id}/{proposal.dataset_version_id}"
        )
    if version.workspace_id != workspace_id:
        raise InsightCleaningOperationError("Dataset version workspace_id does not match active workspace")
    if require_active and dataset.active_version_id != version.id:
        raise InsightCleaningOperationError(
            "Cleaning proposal is stale because its input version is no longer active"
        )
    return dataset, version


def _column_name(proposal: CleaningProposal) -> str:
    column = proposal.scope.get("column")
    if not isinstance(column, str) or not column:
        raise InsightCleaningOperationError(
            f"Operation {proposal.recommended_operation!r} requires a column-scoped proposal"
        )
    return column


def _resolve_operation(proposal: CleaningProposal, operation_type: str | None) -> str:
    selected = (operation_type or proposal.recommended_operation).strip()
    allowed = {proposal.recommended_operation, *proposal.alternatives}
    if selected not in allowed:
        raise InsightCleaningOperationError(
            f"Operation {selected!r} is not an allowed choice for proposal {proposal.id}"
        )
    if selected not in SUPPORTED_OPERATIONS:
        raise InsightCleaningOperationError(
            f"Operation {selected!r} is not supported by the reversible-cleaning MVP"
        )
    return selected


def _normalize_parameters(
    dataframe: pd.DataFrame,
    *,
    proposal: CleaningProposal,
    operation_type: str,
    parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    supplied = dict(parameters or {})
    normalized: dict[str, Any] = {}

    if operation_type == "drop_duplicate_rows":
        if supplied:
            raise InsightCleaningOperationError("drop_duplicate_rows does not accept parameters")
        return normalized

    column = _column_name(proposal)
    if column not in dataframe.columns:
        raise InsightCleaningOperationError(f"Column not found: {column}")
    normalized["column"] = column

    if operation_type == "rename_column":
        suggested = proposal.evidence.get("suggested_name")
        new_name = supplied.pop("new_name", suggested)
        if not isinstance(new_name, str) or not new_name.strip():
            raise InsightCleaningOperationError("rename_column requires a non-empty new_name")
        new_name = new_name.strip()
        if new_name == column:
            raise InsightCleaningOperationError("rename_column new_name must differ from the source column")
        if new_name in dataframe.columns:
            raise InsightCleaningOperationError(f"Target column already exists: {new_name}")
        normalized["new_name"] = new_name
    elif operation_type == "replace_invalid_character":
        replacement = supplied.pop("replacement", "")
        if not isinstance(replacement, str) or len(replacement) > 16:
            raise InsightCleaningOperationError("replacement must be a string of at most 16 characters")
        normalized["replacement"] = replacement

    if supplied:
        unknown = ", ".join(sorted(supplied))
        raise InsightCleaningOperationError(f"Unsupported operation parameters: {unknown}")
    return normalized


def _basic_metrics(dataframe: pd.DataFrame) -> dict[str, int]:
    return {
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "null_cell_count": int(dataframe.isna().sum().sum()),
        "duplicate_excess_row_count": int(dataframe.duplicated(keep="first").sum()),
    }


def _metric_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: int(after[key] - before[key]) for key in before}


def _changed_mask(before: pd.Series, after: pd.Series) -> pd.Series:
    same = before.eq(after) | (before.isna() & after.isna())
    return ~same.fillna(False)


def _execute_operation(
    dataframe: pd.DataFrame,
    *,
    operation_type: str,
    parameters: dict[str, Any],
) -> tuple[pd.DataFrame, int, list[str], list[dict[str, Any]]]:
    result = dataframe.copy(deep=True)

    if operation_type == "drop_duplicate_rows":
        duplicate_mask = result.duplicated(keep="first")
        changed_indices = result.index[duplicate_mask].tolist()
        result = result.loc[~duplicate_mask].reset_index(drop=True)
        sample_diff = [
            {"change_type": "row_removed", "row_index": str(index)}
            for index in changed_indices[:10]
        ]
        return result, int(duplicate_mask.sum()), list(dataframe.columns), sample_diff

    column = parameters["column"]
    if operation_type == "drop_column":
        result = result.drop(columns=[column])
        return result, int(len(dataframe)), [column], [
            {"change_type": "column_removed", "column": column}
        ]

    if operation_type == "rename_column":
        new_name = parameters["new_name"]
        result = result.rename(columns={column: new_name})
        return result, int(len(dataframe)), [column, new_name], [
            {"change_type": "column_renamed", "column": column, "new_column": new_name}
        ]

    before = result[column].copy()
    if operation_type == "trim_string":
        result[column] = result[column].map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
    elif operation_type == "replace_invalid_character":
        replacement = parameters["replacement"]
        result[column] = result[column].map(
            lambda value: _DIRTY_CHARACTER_RE.sub(replacement, value)
            if isinstance(value, str)
            else value
        )
    else:  # pragma: no cover - guarded by _resolve_operation
        raise InsightCleaningOperationError(f"Unsupported operation: {operation_type}")

    mask = _changed_mask(before, result[column])
    changed_indices = result.index[mask].tolist()
    sample_diff = [
        {
            "change_type": "cell_updated",
            "row_index": str(index),
            "changed_columns": [column],
        }
        for index in changed_indices[:10]
    ]
    return result, int(mask.sum()), [column], sample_diff


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _idempotency_key(
    *,
    proposal: CleaningProposal,
    operation_type: str,
    parameters: dict[str, Any],
    source_content_hash: str,
) -> str:
    digest = _canonical_hash(
        {
            "operation_type": operation_type,
            "parameters": parameters,
            "proposal_id": proposal.id,
            "source_content_hash": source_content_hash,
            "version_id": proposal.dataset_version_id,
        }
    )
    return f"sha256:{digest}"


def _preview_operation_id(idempotency_key: str) -> str:
    return f"operation_preview_{idempotency_key.removeprefix('sha256:')[:24]}"


def _find_completed_operation(
    store: InsightStore,
    *,
    idempotency_key: str | None = None,
    proposal_id: str | None = None,
) -> CleaningOperation | None:
    for relative_path in store.list("operations"):
        if not relative_path.endswith(".json"):
            continue
        operation = store.read_model(relative_path, CleaningOperation)
        if operation.status != "completed" or not operation.output_version_id:
            continue
        matches_key = (
            idempotency_key is not None
            and operation.parameters.get("idempotency_key") == idempotency_key
        )
        matches_proposal = (
            proposal_id is not None
            and (
                operation.proposal_id == proposal_id
                or operation.parameters.get("proposal_id") == proposal_id
            )
        )
        if matches_key or matches_proposal:
            return operation
    return None


def _result_from_existing_operation(
    store: InsightStore,
    *,
    proposal: CleaningProposal,
    operation: CleaningOperation,
) -> CleaningApplyResult:
    dataset_id = _dataset_id(proposal)
    dataset = read_dataset(store, dataset_id)
    if dataset is None:
        raise InsightCleaningOperationError(f"Dataset not found: {dataset_id}")
    version = read_dataset_version(store, dataset.id, str(operation.output_version_id))
    if version is None:
        raise InsightCleaningOperationError(
            "Completed cleaning operation references a missing output version"
        )
    if proposal.status != "applied":
        proposal = proposal.model_copy(update={"status": "applied", "updated_at": utc_now()})
        with store.workspace_lock():
            store.write_json(_proposal_path(proposal.id), proposal)
    return CleaningApplyResult(
        proposal=proposal,
        dataset=dataset,
        version=version,
        operation=operation,
        idempotent=True,
    )


def _build_preview(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal: CleaningProposal,
    operation_type: str | None,
    parameters: dict[str, Any] | None,
) -> tuple[CleaningOperation, list[str], list[dict[str, Any]], pd.DataFrame]:
    _, version = _require_dataset_and_version(
        store,
        workspace_id=workspace_id,
        proposal=proposal,
        require_active=True,
    )
    dataframe = store.read_parquet(version.file_ref)
    selected_operation = _resolve_operation(proposal, operation_type)
    normalized_parameters = _normalize_parameters(
        dataframe,
        proposal=proposal,
        operation_type=selected_operation,
        parameters=parameters,
    )
    output, affected_rows, affected_columns, sample_diff = _execute_operation(
        dataframe,
        operation_type=selected_operation,
        parameters=normalized_parameters,
    )
    before_metrics = _basic_metrics(dataframe)
    after_metrics = _basic_metrics(output)
    key = _idempotency_key(
        proposal=proposal,
        operation_type=selected_operation,
        parameters=normalized_parameters,
        source_content_hash=version.content_hash,
    )
    operation_parameters = {
        **normalized_parameters,
        "dataset_id": _dataset_id(proposal),
        "proposal_id": proposal.id,
        "idempotency_key": key,
    }
    warnings = []
    if selected_operation in _DESTRUCTIVE_OPERATIONS:
        warnings.append(
            "This operation removes data but remains reversible through dataset version history."
        )

    operation = CleaningOperation(
        id=_preview_operation_id(key),
        workspace_id=workspace_id,
        created_at=proposal.updated_at,
        updated_at=proposal.updated_at,
        proposal_id=proposal.id,
        operation_type=selected_operation,
        input_version_id=version.id,
        output_version_id=None,
        parameters=operation_parameters,
        reason=f"Preview cleaning proposal {proposal.id}",
        status="previewed",
        reversible=True,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        metric_delta=_metric_delta(before_metrics, after_metrics),
        animation_payload={
            "affected_rows": affected_rows,
            "affected_columns": affected_columns,
            "sample_diff": sample_diff,
            "raw_values_included": False,
        },
    )
    return operation, warnings, sample_diff, output


def preview_cleaning_proposal(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
    operation_type: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> CleaningPreviewResult:
    proposal = _require_proposal(store, workspace_id=workspace_id, proposal_id=proposal_id)
    operation, warnings, sample_diff, _ = _build_preview(
        store,
        workspace_id=workspace_id,
        proposal=proposal,
        operation_type=operation_type,
        parameters=parameters,
    )
    return CleaningPreviewResult(
        proposal=proposal,
        operation=operation,
        warnings=warnings,
        sample_diff=sample_diff,
    )


def approve_cleaning_proposal(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
) -> CleaningProposal:
    with store.workspace_lock():
        proposal = _require_proposal(store, workspace_id=workspace_id, proposal_id=proposal_id)
        if proposal.status == "rejected":
            raise InsightCleaningOperationError("Rejected cleaning proposals cannot be approved")
        if proposal.status in {"approved", "applied"}:
            return proposal
        updated = proposal.model_copy(update={"status": "approved", "updated_at": utc_now()})
        store.write_json(_proposal_path(proposal.id), updated)
        return updated


def reject_cleaning_proposal(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
) -> CleaningProposal:
    with store.workspace_lock():
        proposal = _require_proposal(store, workspace_id=workspace_id, proposal_id=proposal_id)
        if proposal.status == "applied":
            raise InsightCleaningOperationError("Applied cleaning proposals cannot be rejected")
        if proposal.status == "rejected":
            return proposal
        updated = proposal.model_copy(update={"status": "rejected", "updated_at": utc_now()})
        store.write_json(_proposal_path(proposal.id), updated)
        return updated


def apply_cleaning_proposal(
    store: InsightStore,
    *,
    workspace_id: str,
    proposal_id: str,
    operation_type: str | None = None,
    parameters: dict[str, Any] | None = None,
    reason: str | None = None,
) -> CleaningApplyResult:
    proposal = _require_proposal(store, workspace_id=workspace_id, proposal_id=proposal_id)
    if proposal.status not in {"approved", "applied"}:
        raise InsightCleaningOperationError("Cleaning proposal must be approved before apply")

    existing_for_proposal = _find_completed_operation(store, proposal_id=proposal.id)
    if existing_for_proposal is not None:
        return _result_from_existing_operation(
            store,
            proposal=proposal,
            operation=existing_for_proposal,
        )

    dataset, source_version = _require_dataset_and_version(
        store,
        workspace_id=workspace_id,
        proposal=proposal,
        require_active=True,
    )
    preview_operation, _, _, output = _build_preview(
        store,
        workspace_id=workspace_id,
        proposal=proposal,
        operation_type=operation_type,
        parameters=parameters,
    )
    key = str(preview_operation.parameters["idempotency_key"])

    existing_for_key = _find_completed_operation(store, idempotency_key=key)
    if existing_for_key is not None:
        return _result_from_existing_operation(
            store,
            proposal=proposal,
            operation=existing_for_key,
        )

    mutation = create_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        dataframe=output,
        reason=reason or f"Apply cleaning proposal {proposal.id}",
        parent_version_id=source_version.id,
        operation_type=preview_operation.operation_type,
        parameters=dict(preview_operation.parameters),
        activate=True,
    )
    completed_operation = mutation.operation.model_copy(
        update={
            "proposal_id": proposal.id,
            "before_metrics": preview_operation.before_metrics,
            "after_metrics": preview_operation.after_metrics,
            "metric_delta": preview_operation.metric_delta,
            "animation_payload": preview_operation.animation_payload,
            "updated_at": utc_now(),
        }
    )
    applied_proposal = proposal.model_copy(update={"status": "applied", "updated_at": utc_now()})

    with store.workspace_lock():
        store.write_json(_operation_path(completed_operation.id), completed_operation)
        store.write_json(_proposal_path(applied_proposal.id), applied_proposal)

    return CleaningApplyResult(
        proposal=applied_proposal,
        dataset=mutation.dataset,
        version=mutation.version,
        operation=completed_operation,
        idempotent=False,
    )
