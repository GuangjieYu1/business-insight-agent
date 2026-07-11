"""Read-only profiling for immutable Business Insight dataset versions."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

from data_formulator.insight.domain import (
    ColumnProfile,
    DatasetProfile,
    ProfileQualityIssue,
)
from data_formulator.insight.domain.models import Severity, new_id
from data_formulator.insight.registry import (
    VERSION_ZERO_ID,
    InsightRegistryError,
    read_dataset,
    read_dataset_version_zero,
)
from data_formulator.insight.storage import LocalInsightStore

NEAR_CONSTANT_THRESHOLD = 0.95
HIGH_MISSING_THRESHOLD = 0.50
TOP_VALUE_LIMIT = 5
SAMPLE_VALUE_LIMIT = 5

_DATE_HINT_RE = re.compile(
    r"(\d{1,4}[-/]\d{1,2})|(\d{1,2}[-/]\d{1,4})|(\d{1,2}:\d{2})|[年月日]|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)


class InsightProfileError(ValueError):
    """Raised when a dataset profile cannot be generated or read safely."""


class InsightProfileNotFoundError(InsightProfileError):
    """Raised when a requested dataset profile or source dataset is missing."""


@dataclass(frozen=True)
class _ParseStats:
    parseable_count: int
    conflict_count: int


def _profile_path(dataset_id: str, version_id: str = VERSION_ZERO_ID) -> str:
    return f"datasets/{dataset_id}/profiles/{version_id}.json"


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _string_values(series: pd.Series) -> pd.Series:
    return series.dropna().map(lambda value: str(value).strip())


def _numeric_parse_stats(series: pd.Series) -> _ParseStats:
    non_null = _string_values(series)
    if len(non_null) == 0:
        return _ParseStats(parseable_count=0, conflict_count=0)
    parsed = pd.to_numeric(non_null, errors="coerce")
    parseable_count = int(parsed.notna().sum())
    conflict_count = int(len(non_null) - parseable_count) if 0 < parseable_count < len(non_null) else 0
    return _ParseStats(parseable_count=parseable_count, conflict_count=conflict_count)


def _datetime_parse_stats(series: pd.Series) -> _ParseStats:
    non_null = _string_values(series)
    if len(non_null) == 0:
        return _ParseStats(parseable_count=0, conflict_count=0)

    candidate_mask = non_null.map(lambda value: bool(_DATE_HINT_RE.search(value)))
    if int(candidate_mask.sum()) == 0:
        return _ParseStats(parseable_count=0, conflict_count=0)

    candidates = non_null.where(candidate_mask, None)
    parsed = pd.to_datetime(candidates, errors="coerce", utc=False)
    parseable_count = int(parsed.notna().sum())
    conflict_count = int(len(non_null) - parseable_count) if 0 < parseable_count < len(non_null) else 0
    return _ParseStats(parseable_count=parseable_count, conflict_count=conflict_count)


def _normalized_python_type(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "boolean"
    if isinstance(value, (int, float, complex, np.number)) and not isinstance(value, (bool, np.bool_)):
        return "number"
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return "datetime"
    return type(value).__name__


def _python_types(series: pd.Series) -> list[str]:
    return sorted({_normalized_python_type(value) for value in series.dropna().tolist()})


def _top_values(series: pd.Series) -> list[dict[str, Any]]:
    values = []
    for value, count in series.dropna().value_counts().head(TOP_VALUE_LIMIT).items():
        values.append({"value": _jsonable(value), "count": int(count)})
    return values


def _sample_values(series: pd.Series) -> list[Any]:
    return [_jsonable(value) for value in series.dropna().head(SAMPLE_VALUE_LIMIT).tolist()]


def _infer_type(
    series: pd.Series,
    *,
    non_null_count: int,
    python_types: list[str],
    numeric_stats: _ParseStats,
    datetime_stats: _ParseStats,
) -> str:
    if non_null_count == 0:
        return "empty"
    if is_bool_dtype(series):
        return "boolean"
    if is_numeric_dtype(series):
        return "numeric"
    if is_datetime64_any_dtype(series):
        return "datetime"
    if len(python_types) > 1:
        return "mixed"
    if numeric_stats.parseable_count == non_null_count:
        return "numeric"
    if datetime_stats.parseable_count == non_null_count:
        return "datetime"
    return "text"


def _column_issues(
    *,
    column_name: str,
    row_count: int,
    non_null_count: int,
    null_count: int,
    null_ratio: float,
    distinct_count: int,
    top_count: int,
    python_types: list[str],
    numeric_stats: _ParseStats,
    datetime_stats: _ParseStats,
) -> list[ProfileQualityIssue]:
    issues: list[ProfileQualityIssue] = []

    if non_null_count == 0:
        issues.append(
            ProfileQualityIssue(
                issue_type="empty_column",
                severity=Severity.MEDIUM,
                scope={"column": column_name},
                metrics={"row_count": row_count, "null_count": null_count},
                message=f"Column '{column_name}' has no non-null values.",
            )
        )

    if row_count > 0 and null_ratio >= HIGH_MISSING_THRESHOLD:
        issues.append(
            ProfileQualityIssue(
                issue_type="high_missing_column",
                severity=Severity.HIGH if null_ratio >= 0.80 else Severity.MEDIUM,
                scope={"column": column_name},
                metrics={"null_ratio": null_ratio, "null_count": null_count, "row_count": row_count},
                message=f"Column '{column_name}' has a high missing-value ratio.",
            )
        )

    if non_null_count > 0 and distinct_count == 1:
        issues.append(
            ProfileQualityIssue(
                issue_type="constant_column",
                severity=Severity.LOW,
                scope={"column": column_name},
                metrics={"non_null_count": non_null_count},
                message=f"Column '{column_name}' has the same value for every non-null row.",
            )
        )
    elif non_null_count > 0 and distinct_count > 1:
        dominant_ratio = top_count / non_null_count
        if dominant_ratio >= NEAR_CONSTANT_THRESHOLD:
            issues.append(
                ProfileQualityIssue(
                    issue_type="near_constant_column",
                    severity=Severity.LOW,
                    scope={"column": column_name},
                    metrics={"dominant_ratio": dominant_ratio, "non_null_count": non_null_count},
                    message=f"Column '{column_name}' is dominated by a single value.",
                )
            )

    if len(python_types) > 1:
        issues.append(
            ProfileQualityIssue(
                issue_type="mixed_type_column",
                severity=Severity.MEDIUM,
                scope={"column": column_name},
                metrics={"python_types": python_types},
                message=f"Column '{column_name}' contains multiple runtime value types.",
            )
        )

    if numeric_stats.conflict_count > 0:
        issues.append(
            ProfileQualityIssue(
                issue_type="numeric_parse_conflict",
                severity=Severity.MEDIUM,
                scope={"column": column_name},
                metrics={
                    "parseable_count": numeric_stats.parseable_count,
                    "conflict_count": numeric_stats.conflict_count,
                    "non_null_count": non_null_count,
                },
                message=f"Column '{column_name}' mixes numeric-looking and non-numeric values.",
            )
        )

    if datetime_stats.conflict_count > 0:
        issues.append(
            ProfileQualityIssue(
                issue_type="datetime_parse_conflict",
                severity=Severity.MEDIUM,
                scope={"column": column_name},
                metrics={
                    "parseable_count": datetime_stats.parseable_count,
                    "conflict_count": datetime_stats.conflict_count,
                    "non_null_count": non_null_count,
                },
                message=f"Column '{column_name}' mixes datetime-looking and non-datetime values.",
            )
        )

    return issues


def profile_dataframe(
    dataframe: pd.DataFrame,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
    source_content_hash: str,
    file_ref: str,
    profile_ref: str,
) -> DatasetProfile:
    """Build a deterministic profile from a dataframe without mutating it."""

    row_count = int(len(dataframe))
    column_count = int(len(dataframe.columns))
    duplicate_row_count = int(dataframe.duplicated(keep=False).sum()) if row_count > 0 else 0
    duplicate_row_ratio = duplicate_row_count / row_count if row_count else 0.0

    quality_issues: list[ProfileQualityIssue] = []
    columns: list[ColumnProfile] = []

    if duplicate_row_count > 0:
        quality_issues.append(
            ProfileQualityIssue(
                issue_type="duplicate_rows",
                severity=Severity.MEDIUM,
                scope={"dataset_id": dataset_id, "version_id": version_id},
                metrics={"duplicate_row_count": duplicate_row_count, "duplicate_row_ratio": duplicate_row_ratio},
                message="The dataset contains duplicate rows.",
            )
        )

    for column in dataframe.columns:
        series = dataframe[column]
        non_null_count = int(series.notna().sum())
        null_count = int(row_count - non_null_count)
        null_ratio = null_count / row_count if row_count else 0.0
        distinct_count = int(series.nunique(dropna=True))
        distinct_ratio = distinct_count / non_null_count if non_null_count else 0.0
        top_values = _top_values(series)
        top_count = int(top_values[0]["count"]) if top_values else 0
        python_types = _python_types(series)
        numeric_stats = _numeric_parse_stats(series)
        datetime_stats = _datetime_parse_stats(series)
        column_issues = _column_issues(
            column_name=str(column),
            row_count=row_count,
            non_null_count=non_null_count,
            null_count=null_count,
            null_ratio=null_ratio,
            distinct_count=distinct_count,
            top_count=top_count,
            python_types=python_types,
            numeric_stats=numeric_stats,
            datetime_stats=datetime_stats,
        )
        quality_issues.extend(column_issues)
        columns.append(
            ColumnProfile(
                name=str(column),
                pandas_dtype=str(series.dtype),
                inferred_type=_infer_type(
                    series,
                    non_null_count=non_null_count,
                    python_types=python_types,
                    numeric_stats=numeric_stats,
                    datetime_stats=datetime_stats,
                ),
                row_count=row_count,
                non_null_count=non_null_count,
                null_count=null_count,
                null_ratio=null_ratio,
                distinct_count=distinct_count,
                distinct_ratio=distinct_ratio,
                top_values=top_values,
                sample_values=_sample_values(series),
                python_types=python_types,
                numeric_parseable_count=numeric_stats.parseable_count,
                numeric_parse_conflict_count=numeric_stats.conflict_count,
                datetime_parseable_count=datetime_stats.parseable_count,
                datetime_parse_conflict_count=datetime_stats.conflict_count,
                quality_issue_types=[issue.issue_type for issue in column_issues],
            )
        )

    return DatasetProfile(
        id=new_id("profile"),
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
        source_content_hash=source_content_hash,
        file_ref=file_ref,
        profile_ref=profile_ref,
        row_count=row_count,
        column_count=column_count,
        duplicate_row_count=duplicate_row_count,
        duplicate_row_ratio=duplicate_row_ratio,
        columns=columns,
        quality_issues=quality_issues,
    )


def generate_dataset_profile(
    store: LocalInsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str = VERSION_ZERO_ID,
) -> DatasetProfile:
    if version_id != VERSION_ZERO_ID:
        raise InsightProfileError("Only immutable version_000 profiling is supported")

    try:
        dataset = read_dataset(store, dataset_id)
        version = read_dataset_version_zero(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightProfileError(str(exc)) from exc

    if dataset is None:
        raise InsightProfileNotFoundError(f"Dataset not found: {dataset_id}")
    if version is None:
        raise InsightProfileNotFoundError(f"Dataset version not found: {dataset_id}/{version_id}")
    if dataset.workspace_id != workspace_id or version.workspace_id != workspace_id:
        raise InsightProfileError("Dataset workspace_id does not match active workspace")
    if dataset.original_version_id != version_id or version.dataset_id != dataset.id:
        raise InsightProfileError("Dataset Version 0 metadata is inconsistent")

    dataframe = store.read_parquet(version.file_ref)
    profile_ref = _profile_path(dataset.id, version_id)
    profile = profile_dataframe(
        dataframe,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        version_id=version.id,
        source_content_hash=version.content_hash,
        file_ref=version.file_ref,
        profile_ref=profile_ref,
    )
    store.write_json(profile_ref, profile)
    return profile


def read_dataset_profile(
    store: LocalInsightStore,
    *,
    dataset_id: str,
    version_id: str = VERSION_ZERO_ID,
) -> DatasetProfile | None:
    if version_id != VERSION_ZERO_ID:
        raise InsightProfileError("Only immutable version_000 profiles are supported")

    try:
        dataset = read_dataset(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightProfileError(str(exc)) from exc
    if dataset is None:
        raise InsightProfileNotFoundError(f"Dataset not found: {dataset_id}")

    profile_ref = _profile_path(dataset.id, version_id)
    if not store.exists(profile_ref):
        return None
    return store.read_model(profile_ref, DatasetProfile)
