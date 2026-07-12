"""Dataset operation history and version Profile comparison services."""

from __future__ import annotations

import json
from typing import Any

from data_formulator.insight.domain import CleaningOperation, DatasetProfile
from data_formulator.insight.registry import InsightRegistryError, read_dataset, read_dataset_version
from data_formulator.insight.storage import InsightStore
from data_formulator.insight.version_profiling import generate_dataset_version_profile


class InsightHistoryError(ValueError):
    """Raised when history or comparison data cannot be read safely."""


def _require_dataset(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
):
    try:
        dataset = read_dataset(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightHistoryError(str(exc)) from exc
    if dataset is None:
        raise InsightHistoryError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightHistoryError("Dataset workspace_id does not match active workspace")
    return dataset


def list_dataset_operations(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
) -> list[CleaningOperation]:
    _require_dataset(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
    )
    operations: list[CleaningOperation] = []
    for relative_path in store.list("operations"):
        if not relative_path.endswith(".json"):
            continue
        operation = store.read_model(relative_path, CleaningOperation)
        if operation.workspace_id != workspace_id:
            continue
        if operation.parameters.get("dataset_id") != dataset_id:
            continue
        operations.append(operation)
    return sorted(operations, key=lambda item: (item.created_at, item.id))


def read_dataset_operation(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    operation_id: str,
) -> CleaningOperation | None:
    for operation in list_dataset_operations(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
    ):
        if operation.id == operation_id:
            return operation
    return None


def _issue_key(issue) -> str:
    return json.dumps(
        {
            "issue_type": issue.issue_type,
            "scope": issue.scope,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _profile_metrics(profile: DatasetProfile) -> dict[str, int]:
    return {
        "row_count": profile.row_count,
        "column_count": profile.column_count,
        "duplicate_excess_row_count": profile.duplicate_excess_row_count,
        "quality_issue_count": len(profile.quality_issues),
        "critical_issue_count": sum(issue.severity == "critical" for issue in profile.quality_issues),
        "high_issue_count": sum(issue.severity == "high" for issue in profile.quality_issues),
        "medium_issue_count": sum(issue.severity == "medium" for issue in profile.quality_issues),
        "low_issue_count": sum(issue.severity == "low" for issue in profile.quality_issues),
        "info_issue_count": sum(issue.severity == "info" for issue in profile.quality_issues),
    }


def compare_dataset_version_profiles(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    before_version_id: str,
    after_version_id: str,
) -> dict[str, Any]:
    dataset = _require_dataset(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
    )
    try:
        before_version = read_dataset_version(store, dataset.id, before_version_id)
        after_version = read_dataset_version(store, dataset.id, after_version_id)
    except InsightRegistryError as exc:
        raise InsightHistoryError(str(exc)) from exc
    if before_version is None:
        raise InsightHistoryError(
            f"Dataset version not found: {dataset.id}/{before_version_id}"
        )
    if after_version is None:
        raise InsightHistoryError(
            f"Dataset version not found: {dataset.id}/{after_version_id}"
        )
    if before_version.workspace_id != workspace_id or after_version.workspace_id != workspace_id:
        raise InsightHistoryError("Dataset version workspace_id does not match active workspace")

    before = generate_dataset_version_profile(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        version_id=before_version.id,
    )
    after = generate_dataset_version_profile(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        version_id=after_version.id,
    )

    before_issues = {_issue_key(issue): issue for issue in before.quality_issues}
    after_issues = {_issue_key(issue): issue for issue in after.quality_issues}
    before_keys = set(before_issues)
    after_keys = set(after_issues)

    before_metrics = _profile_metrics(before)
    after_metrics = _profile_metrics(after)
    metric_delta = {
        key: after_metrics[key] - before_metrics[key]
        for key in before_metrics
    }

    return {
        "datasetId": dataset.id,
        "beforeVersionId": before.version_id,
        "afterVersionId": after.version_id,
        "beforeProfile": before,
        "afterProfile": after,
        "beforeMetrics": before_metrics,
        "afterMetrics": after_metrics,
        "metricDelta": metric_delta,
        "resolvedIssues": [before_issues[key] for key in sorted(before_keys - after_keys)],
        "introducedIssues": [after_issues[key] for key in sorted(after_keys - before_keys)],
        "unchangedIssues": [
            {
                "before": before_issues[key],
                "after": after_issues[key],
            }
            for key in sorted(before_keys & after_keys)
        ],
    }
