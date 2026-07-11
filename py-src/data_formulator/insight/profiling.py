"""Read-only profiling for immutable Business Insight dataset versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import time
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
from data_formulator.insight.domain.models import Severity
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
TOP_VALUE_MAX_STRING_LENGTH = 64
HIGH_CARDINALITY_MIN_DISTINCT = 100
HIGH_CARDINALITY_RATIO = 0.80
SENSITIVE_VALUE_SAMPLE_LIMIT = 100
PROFILER_VERSION = "dataset-profiler-v1"
SAMPLE_POLICY = "disabled"
CANONICAL_PROFILE_TIMESTAMP = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class ProfileLimits:
    max_file_bytes: int = 50 * 1024 * 1024
    max_rows: int = 200_000
    max_columns: int = 200
    timeout_seconds: float = 15.0


DEFAULT_PROFILE_LIMITS = ProfileLimits(
    max_file_bytes=_env_int("INSIGHT_PROFILE_MAX_FILE_BYTES", 50 * 1024 * 1024),
    max_rows=_env_int("INSIGHT_PROFILE_MAX_ROWS", 200_000),
    max_columns=_env_int("INSIGHT_PROFILE_MAX_COLUMNS", 200),
    timeout_seconds=_env_float("INSIGHT_PROFILE_TIMEOUT_SECONDS", 15.0),
)

PROFILE_CONFIGURATION = {
    "high_missing_threshold": HIGH_MISSING_THRESHOLD,
    "high_cardinality_min_distinct": HIGH_CARDINALITY_MIN_DISTINCT,
    "high_cardinality_ratio": HIGH_CARDINALITY_RATIO,
    "near_constant_threshold": NEAR_CONSTANT_THRESHOLD,
    "sample_policy": SAMPLE_POLICY,
    "sensitive_value_sample_limit": SENSITIVE_VALUE_SAMPLE_LIMIT,
    "top_value_limit": TOP_VALUE_LIMIT,
    "top_value_max_string_length": TOP_VALUE_MAX_STRING_LENGTH,
}
PROFILE_CONFIGURATION_HASH = "sha256:" + hashlib.sha256(
    json.dumps(PROFILE_CONFIGURATION, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

SENSITIVE_COLUMN_NAME_RE = re.compile(
    r"(^|[_\-\s])(?:id|identifier|ssn|sin|email|e-mail|phone|mobile|tel|"
    r"name|full_name|address|addr|contact|customer|client|account|remark|comment|note)([_\-\s]|$)|"
    r"(身份证|手机号|手机|电话|邮箱|姓名|名字|地址|客户|联系人|备注|订单备注)",
    re.IGNORECASE,
)
EMAIL_VALUE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ID_VALUE_RE = re.compile(r"^\d{15}$|^\d{17}[\dXx]$")

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


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _profile_id(
    *,
    dataset_id: str,
    version_id: str,
    source_content_hash: str,
    profiler_version: str,
    configuration_hash: str,
) -> str:
    digest = _canonical_hash(
        {
            "configuration_hash": configuration_hash,
            "dataset_id": dataset_id,
            "profiler_version": profiler_version,
            "source_content_hash": source_content_hash,
            "version_id": version_id,
        }
    )
    return f"profile_{digest[:32]}"


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise InsightProfileError("Dataset profiling exceeded the configured timeout")


def _validate_dataframe_limits(dataframe: pd.DataFrame, limits: ProfileLimits) -> None:
    row_count = int(len(dataframe))
    column_count = int(len(dataframe.columns))
    if row_count > limits.max_rows:
        raise InsightProfileError(
            f"Dataset profiling row limit exceeded: {row_count} > {limits.max_rows}"
        )
    if column_count > limits.max_columns:
        raise InsightProfileError(
            f"Dataset profiling column limit exceeded: {column_count} > {limits.max_columns}"
        )


def _validate_source_limits(store: LocalInsightStore, file_ref: str, limits: ProfileLimits) -> None:
    file_size = store.file_size(file_ref)
    if file_size > limits.max_file_bytes:
        raise InsightProfileError(
            f"Dataset profiling file size limit exceeded: {file_size} > {limits.max_file_bytes} bytes"
        )

    try:
        row_count, column_count = store.parquet_shape(file_ref)
    except Exception as exc:
        raise InsightProfileError(f"Unable to inspect parquet metadata: {exc}") from exc
    if row_count > limits.max_rows:
        raise InsightProfileError(
            f"Dataset profiling row limit exceeded: {row_count} > {limits.max_rows}"
        )
    if column_count > limits.max_columns:
        raise InsightProfileError(
            f"Dataset profiling column limit exceeded: {column_count} > {limits.max_columns}"
        )


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


def _truncate_profile_value(value: Any) -> Any:
    jsonable = _jsonable(value)
    if isinstance(jsonable, str) and len(jsonable) > TOP_VALUE_MAX_STRING_LENGTH:
        return f"{jsonable[:TOP_VALUE_MAX_STRING_LENGTH]}..."
    return jsonable


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


def _is_phone_like(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10 or len(digits) > 15:
        return False
    return bool(re.search(r"\d", value))


def _has_sensitive_values(series: pd.Series) -> bool:
    sample = series.dropna().head(SENSITIVE_VALUE_SAMPLE_LIMIT).map(lambda value: str(value).strip())
    for value in sample:
        if EMAIL_VALUE_RE.fullmatch(value) or ID_VALUE_RE.fullmatch(value) or _is_phone_like(value):
            return True
    return False


def _has_sensitive_column_name(column_name: str) -> bool:
    return bool(SENSITIVE_COLUMN_NAME_RE.search(column_name))


def _is_high_cardinality(*, non_null_count: int, distinct_count: int) -> bool:
    if non_null_count == 0:
        return False
    return (
        distinct_count >= HIGH_CARDINALITY_MIN_DISTINCT
        and (distinct_count / non_null_count) >= HIGH_CARDINALITY_RATIO
    )


def _value_storage_policy(
    *,
    column_name: str,
    series: pd.Series,
    non_null_count: int,
    distinct_count: int,
) -> tuple[str, bool]:
    sensitive = _has_sensitive_column_name(column_name) or _has_sensitive_values(series)
    if sensitive:
        return "redacted_sensitive", True
    if _is_high_cardinality(non_null_count=non_null_count, distinct_count=distinct_count):
        return "omitted_high_cardinality", False
    return "stored", False


def _value_counts(series: pd.Series) -> pd.Series:
    return series.dropna().value_counts()


def _top_values(value_counts: pd.Series, *, storage_policy: str) -> list[dict[str, Any]]:
    if storage_policy != "stored":
        return []

    values = []
    for value, count in value_counts.head(TOP_VALUE_LIMIT).items():
        values.append({"value": _truncate_profile_value(value), "count": int(count)})
    return values


def _sample_values() -> list[Any]:
    return []


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

    elif row_count > 0 and null_ratio >= HIGH_MISSING_THRESHOLD:
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
    profiler_version: str = PROFILER_VERSION,
    configuration_hash: str = PROFILE_CONFIGURATION_HASH,
    limits: ProfileLimits = DEFAULT_PROFILE_LIMITS,
    deadline: float | None = None,
    profile_timestamp: datetime | None = None,
) -> DatasetProfile:
    """Build a deterministic profile from a dataframe without mutating it."""

    _validate_dataframe_limits(dataframe, limits)
    _check_deadline(deadline)

    row_count = int(len(dataframe))
    column_count = int(len(dataframe.columns))
    if row_count > 0:
        duplicate_group_member_count = int(dataframe.duplicated(keep=False).sum())
        duplicate_excess_row_count = int(dataframe.duplicated(keep="first").sum())
    else:
        duplicate_group_member_count = 0
        duplicate_excess_row_count = 0
    duplicate_group_member_ratio = duplicate_group_member_count / row_count if row_count else 0.0
    duplicate_excess_row_ratio = duplicate_excess_row_count / row_count if row_count else 0.0
    duplicate_row_count = duplicate_excess_row_count
    duplicate_row_ratio = duplicate_excess_row_ratio
    _check_deadline(deadline)

    quality_issues: list[ProfileQualityIssue] = []
    columns: list[ColumnProfile] = []
    profile_redaction_applied = False
    profile_sensitive_data_detected = False

    if duplicate_excess_row_count > 0:
        quality_issues.append(
            ProfileQualityIssue(
                issue_type="duplicate_rows",
                severity=Severity.MEDIUM,
                scope={"dataset_id": dataset_id, "version_id": version_id},
                metrics={
                    "duplicate_group_member_count": duplicate_group_member_count,
                    "duplicate_group_member_ratio": duplicate_group_member_ratio,
                    "duplicate_excess_row_count": duplicate_excess_row_count,
                    "duplicate_excess_row_ratio": duplicate_excess_row_ratio,
                    "duplicate_row_count": duplicate_row_count,
                    "duplicate_row_ratio": duplicate_row_ratio,
                },
                message="The dataset contains duplicate rows.",
            )
        )

    for column in dataframe.columns:
        _check_deadline(deadline)
        column_name = str(column)
        series = dataframe[column]
        non_null_count = int(series.notna().sum())
        null_count = int(row_count - non_null_count)
        null_ratio = null_count / row_count if row_count else 0.0
        distinct_count = int(series.nunique(dropna=True))
        distinct_ratio = distinct_count / non_null_count if non_null_count else 0.0
        high_cardinality = _is_high_cardinality(
            non_null_count=non_null_count,
            distinct_count=distinct_count,
        )
        value_storage_policy, sensitive_data_detected = _value_storage_policy(
            column_name=column_name,
            series=series,
            non_null_count=non_null_count,
            distinct_count=distinct_count,
        )
        if high_cardinality:
            value_counts = pd.Series(dtype="int64")
        else:
            value_counts = _value_counts(series)
        top_values = _top_values(value_counts, storage_policy=value_storage_policy)
        top_count = int(value_counts.iloc[0]) if not value_counts.empty else 0
        redaction_applied = value_storage_policy != "stored"
        profile_redaction_applied = profile_redaction_applied or redaction_applied
        profile_sensitive_data_detected = profile_sensitive_data_detected or sensitive_data_detected
        python_types = _python_types(series)
        numeric_stats = _numeric_parse_stats(series)
        datetime_stats = _datetime_parse_stats(series)
        column_issues = _column_issues(
            column_name=column_name,
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
                name=column_name,
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
                value_storage_policy=value_storage_policy,
                sensitive_data_detected=sensitive_data_detected,
                redaction_applied=redaction_applied,
                top_values=top_values,
                sample_values=_sample_values(),
                python_types=python_types,
                numeric_parseable_count=numeric_stats.parseable_count,
                numeric_parse_conflict_count=numeric_stats.conflict_count,
                datetime_parseable_count=datetime_stats.parseable_count,
                datetime_parse_conflict_count=datetime_stats.conflict_count,
                quality_issue_types=[issue.issue_type for issue in column_issues],
            )
        )
        _check_deadline(deadline)

    profile_time = profile_timestamp or CANONICAL_PROFILE_TIMESTAMP

    return DatasetProfile(
        id=_profile_id(
            dataset_id=dataset_id,
            version_id=version_id,
            source_content_hash=source_content_hash,
            profiler_version=profiler_version,
            configuration_hash=configuration_hash,
        ),
        workspace_id=workspace_id,
        created_at=profile_time,
        updated_at=profile_time,
        dataset_id=dataset_id,
        version_id=version_id,
        source_content_hash=source_content_hash,
        profiler_version=profiler_version,
        configuration_hash=configuration_hash,
        file_ref=file_ref,
        profile_ref=profile_ref,
        row_count=row_count,
        column_count=column_count,
        duplicate_row_count=duplicate_row_count,
        duplicate_row_ratio=duplicate_row_ratio,
        duplicate_group_member_count=duplicate_group_member_count,
        duplicate_group_member_ratio=duplicate_group_member_ratio,
        duplicate_excess_row_count=duplicate_excess_row_count,
        duplicate_excess_row_ratio=duplicate_excess_row_ratio,
        sample_policy=SAMPLE_POLICY,
        redaction_applied=profile_redaction_applied,
        sensitive_data_detected=profile_sensitive_data_detected,
        columns=columns,
        quality_issues=quality_issues,
    )


def _matches_current_profile(
    profile: DatasetProfile,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
    source_content_hash: str,
    file_ref: str,
    profile_ref: str,
) -> bool:
    return (
        profile.id
        == _profile_id(
            dataset_id=dataset_id,
            version_id=version_id,
            source_content_hash=source_content_hash,
            profiler_version=PROFILER_VERSION,
            configuration_hash=PROFILE_CONFIGURATION_HASH,
        )
        and profile.workspace_id == workspace_id
        and profile.dataset_id == dataset_id
        and profile.version_id == version_id
        and profile.source_content_hash == source_content_hash
        and profile.profiler_version == PROFILER_VERSION
        and profile.configuration_hash == PROFILE_CONFIGURATION_HASH
        and profile.file_ref == file_ref
        and profile.profile_ref == profile_ref
    )


def generate_dataset_profile(
    store: LocalInsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str = VERSION_ZERO_ID,
    limits: ProfileLimits = DEFAULT_PROFILE_LIMITS,
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

    profile_ref = _profile_path(dataset.id, version_id)
    if store.exists(profile_ref):
        try:
            existing_profile = store.read_model(profile_ref, DatasetProfile)
        except Exception:
            existing_profile = None
        if existing_profile is not None and _matches_current_profile(
            existing_profile,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
            source_content_hash=version.content_hash,
            file_ref=version.file_ref,
            profile_ref=profile_ref,
        ):
            return existing_profile

    deadline = time.monotonic() + limits.timeout_seconds if limits.timeout_seconds > 0 else None
    _validate_source_limits(store, version.file_ref, limits)
    _check_deadline(deadline)
    dataframe = store.read_parquet(version.file_ref)
    _check_deadline(deadline)
    profile = profile_dataframe(
        dataframe,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        version_id=version.id,
        source_content_hash=version.content_hash,
        file_ref=version.file_ref,
        profile_ref=profile_ref,
        profiler_version=PROFILER_VERSION,
        configuration_hash=PROFILE_CONFIGURATION_HASH,
        limits=limits,
        deadline=deadline,
        profile_timestamp=version.created_at,
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
