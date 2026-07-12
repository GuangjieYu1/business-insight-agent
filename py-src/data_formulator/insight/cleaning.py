"""Deterministic cleaning proposal generation for Business Insight."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from data_formulator.insight.domain import CleaningProposal, ColumnProfile, DatasetProfile
from data_formulator.insight.domain.models import ProfileQualityIssue, Severity
from data_formulator.insight.profiling import (
    InsightProfileError,
    generate_dataset_profile,
    read_dataset_profile,
)
from data_formulator.insight.registry import VERSION_ZERO_ID, InsightRegistryError, read_dataset
from data_formulator.insight.storage import InsightStore


class InsightCleaningError(ValueError):
    """Raised when cleaning proposals cannot be generated safely."""


def _proposal_path(proposal_id: str) -> str:
    return f"proposals/{proposal_id}.json"


def _proposal_id(*, dataset_id: str, version_id: str, problem_type: str, scope: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "problem_type": problem_type,
                "scope": scope,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"proposal_{digest[:24]}"


def _confidence_for_issue(issue_type: str) -> float:
    if issue_type in {"empty_column", "constant_column", "duplicate_columns", "duplicate_rows", "high_cardinality_id_like"}:
        return 1.0
    if issue_type in {"dirty_character_column", "whitespace_pollution", "numeric_parse_conflict", "datetime_parse_conflict", "high_missing_column"}:
        return 0.9
    if issue_type in {"near_constant_column", "mixed_type_column", "infinite_value"}:
        return 0.8
    if issue_type in {"invalid_header", "meaningless_header_candidate", "outlier_warning"}:
        return 0.7
    return 0.75


def _suggest_header_name(column_name: str) -> str:
    normalized = re.sub(r"\s+", "_", column_name.strip())
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", normalized).strip("_").lower()
    if normalized and not normalized.startswith("unnamed"):
        return normalized
    return "column_needs_name"


def _proposal_from_issue(
    *,
    dataset_id: str,
    version_id: str,
    profile: DatasetProfile,
    issue: ProfileQualityIssue,
    columns_by_name: dict[str, ColumnProfile],
) -> CleaningProposal | None:
    scope = {"dataset_id": dataset_id, "version_id": version_id, **issue.scope}
    evidence = {**issue.metrics}
    problem_type = issue.issue_type
    recommended_operation = "keep_rows"
    alternatives: list[str] = ["keep_rows"]

    column_name = scope.get("column")
    column_profile = columns_by_name.get(column_name) if isinstance(column_name, str) else None

    if problem_type == "empty_column":
        recommended_operation = "drop_column"
        alternatives = ["keep_column", "mark_column_as_metadata"]
    elif problem_type == "constant_column":
        recommended_operation = "drop_column"
        alternatives = ["keep_column", "mark_column_as_metadata"]
        if column_profile and column_profile.top_values:
            evidence["constant_value"] = column_profile.top_values[0]["value"]
    elif problem_type == "near_constant_column":
        recommended_operation = "mark_column_as_metadata"
        alternatives = ["keep_column", "drop_column"]
    elif problem_type == "high_missing_column":
        if column_profile and column_profile.inferred_type == "numeric":
            recommended_operation = "fill_missing_median"
            alternatives = ["fill_missing_mean", "keep_column", "drop_rows"]
        else:
            recommended_operation = "fill_missing_mode"
            alternatives = ["fill_missing_constant", "keep_column", "drop_rows"]
    elif problem_type == "duplicate_rows":
        recommended_operation = "drop_duplicate_rows"
        alternatives = ["keep_rows"]
    elif problem_type == "duplicate_columns":
        recommended_operation = "drop_column"
        alternatives = ["keep_column", "mark_column_as_metadata"]
    elif problem_type == "mixed_type_column":
        recommended_operation = "cast_numeric" if column_profile and column_profile.numeric_parseable_count else "trim_string"
        alternatives = ["cast_datetime", "keep_column"]
    elif problem_type == "numeric_parse_conflict":
        recommended_operation = "cast_numeric"
        alternatives = ["trim_string", "keep_column"]
    elif problem_type == "datetime_parse_conflict":
        recommended_operation = "cast_datetime"
        alternatives = ["trim_string", "keep_column"]
    elif problem_type == "dirty_character_column":
        recommended_operation = "replace_invalid_character"
        alternatives = ["trim_string", "keep_column"]
    elif problem_type == "whitespace_pollution":
        recommended_operation = "trim_string"
        alternatives = ["replace_invalid_character", "keep_column"]
    elif problem_type == "high_cardinality_id_like":
        recommended_operation = "mark_column_as_id"
        alternatives = ["mark_column_as_metadata", "keep_column"]
    elif problem_type == "invalid_header":
        recommended_operation = "rename_column"
        alternatives = ["keep_column"]
        if isinstance(column_name, str):
            evidence["suggested_name"] = _suggest_header_name(column_name)
    elif problem_type == "meaningless_header_candidate":
        recommended_operation = "rename_column"
        alternatives = ["keep_column", "mark_column_as_metadata"]
        if isinstance(column_name, str):
            evidence["suggested_name"] = _suggest_header_name(column_name)
    elif problem_type == "infinite_value":
        recommended_operation = "fill_missing_median"
        alternatives = ["fill_missing_constant", "drop_rows", "keep_rows"]
    elif problem_type == "outlier_warning":
        recommended_operation = "keep_rows"
        alternatives = ["drop_rows"]
    else:
        return None

    proposal_scope = {key: value for key, value in scope.items() if value is not None}
    proposal_id = _proposal_id(
        dataset_id=dataset_id,
        version_id=version_id,
        problem_type=problem_type,
        scope=proposal_scope,
    )
    return CleaningProposal(
        id=proposal_id,
        workspace_id=profile.workspace_id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        dataset_version_id=version_id,
        problem_type=problem_type,
        severity=issue.severity,
        confidence=_confidence_for_issue(problem_type),
        scope=proposal_scope,
        evidence=evidence,
        recommended_operation=recommended_operation,
        alternatives=alternatives,
        requires_approval=True,
        status="pending",
    )


def generate_cleaning_proposals(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str = VERSION_ZERO_ID,
) -> list[CleaningProposal]:
    if version_id != VERSION_ZERO_ID:
        raise InsightCleaningError("Cleaning proposals currently support only version_000 profiles")

    try:
        dataset = read_dataset(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightCleaningError(str(exc)) from exc
    if dataset is None:
        raise InsightCleaningError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightCleaningError("Dataset workspace_id does not match active workspace")

    try:
        profile = read_dataset_profile(store, dataset_id=dataset_id, version_id=version_id)
    except InsightProfileError as exc:
        raise InsightCleaningError(str(exc)) from exc
    if profile is None:
        try:
            profile = generate_dataset_profile(
                store,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                version_id=version_id,
            )
        except InsightProfileError as exc:
            raise InsightCleaningError(str(exc)) from exc

    columns_by_name = {column.name: column for column in profile.columns}
    proposals: list[CleaningProposal] = []
    for issue in profile.quality_issues:
        proposal = _proposal_from_issue(
            dataset_id=dataset_id,
            version_id=version_id,
            profile=profile,
            issue=issue,
            columns_by_name=columns_by_name,
        )
        if proposal is not None:
            proposals.append(proposal)

    with store.workspace_lock():
        for proposal in proposals:
            store.write_json(_proposal_path(proposal.id), proposal)

    return proposals


def list_cleaning_proposals(
    store: InsightStore,
    *,
    dataset_id: str | None = None,
    version_id: str | None = None,
) -> list[CleaningProposal]:
    proposals: list[CleaningProposal] = []
    for relative_path in store.list("proposals"):
        if relative_path.endswith(".json"):
            proposal = store.read_model(relative_path, CleaningProposal)
            if dataset_id is not None and proposal.scope.get("dataset_id") != dataset_id:
                continue
            if version_id is not None and proposal.dataset_version_id != version_id:
                continue
            proposals.append(proposal)
    return sorted(proposals, key=lambda proposal: (proposal.dataset_version_id, proposal.problem_type, proposal.id))