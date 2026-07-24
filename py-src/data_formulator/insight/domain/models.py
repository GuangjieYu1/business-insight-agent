"""Versioned domain contracts for Business Insight Agent.

These models are deliberately independent of Flask routes and persistence
backends. They form the stable boundary between agents, deterministic engines,
front-end state, and external integrations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class InsightModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)

    id: str
    schema_version: str = "1.0"
    workspace_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", "workspace_id", "schema_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(InsightModel):
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    default_language: str = "zh-CN"
    active_dataset_id: str | None = None
    active_goal_id: str | None = None


class MaterialType(StrEnum):
    XLS = "xls"
    XLSX = "xlsx"
    CSV = "csv"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"
    TEXT = "text"
    OTHER = "other"


class ProjectMaterial(InsightModel):
    type: MaterialType
    filename: str
    content_hash: str
    source: Literal["upload", "connector", "generated"] = "upload"
    ingestion_status: Literal["pending", "running", "completed", "failed"] = "pending"
    knowledge_status: Literal["pending", "indexed", "failed", "skipped"] = "pending"
    references: list[str] = Field(default_factory=list)


class Dataset(InsightModel):
    name: str
    source_material_id: str | None = None
    original_table_ref: str
    original_version_id: str
    active_version_id: str


class DatasetVersionStatus(StrEnum):
    ACTIVE = "active"
    HISTORICAL = "historical"
    INVALID = "invalid"


class DatasetVersion(InsightModel):
    dataset_id: str
    parent_version_id: str | None = None
    created_by_operation_id: str | None = None
    content_hash: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    file_ref: str
    status: DatasetVersionStatus = DatasetVersionStatus.ACTIVE

    @field_validator("file_ref")
    @classmethod
    def _relative_file_ref(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("file_ref must be a workspace-relative path")
        return normalized


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


ProfileIssueType = Literal[
    "empty_column",
    "constant_column",
    "near_constant_column",
    "high_missing_column",
    "duplicate_rows",
    "duplicate_columns",
    "mixed_type_column",
    "numeric_parse_conflict",
    "datetime_parse_conflict",
    "dirty_character_column",
    "high_cardinality_id_like",
    "outlier_warning",
    "invalid_header",
    "meaningless_header_candidate",
    "infinite_value",
    "whitespace_pollution",
]

PROFILE_ISSUE_ID_NAMESPACE = "profile-quality-issue:v1"
PROFILE_ISSUE_NON_IDENTITY_SCOPE_KEYS = frozenset(
    {
        "version_id",
        "dataset_version_id",
    }
)


def _normalize_profile_issue_scope(value: Any) -> Any:
    """Return a JSON-safe canonical representation for issue identity.

    Mapping key order is normalized. Dataset-version references are excluded
    because the same semantic issue must retain one identity across immutable
    versions. Sequence order is intentionally preserved because it may carry
    detector semantics; sets are sorted by canonical JSON.
    """

    if isinstance(value, dict):
        return {
            str(key): _normalize_profile_issue_scope(value[key])
            for key in sorted(value, key=lambda item: str(item))
            if str(key) not in PROFILE_ISSUE_NON_IDENTITY_SCOPE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_profile_issue_scope(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize_profile_issue_scope(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_profile_issue_id(issue_type: str, scope: dict[str, Any]) -> str:
    payload = {
        "namespace": PROFILE_ISSUE_ID_NAMESPACE,
        "issue_type": issue_type,
        "scope": _normalize_profile_issue_scope(scope),
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"issue_{digest[:32]}"


class ProfileQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)

    issue_id: str | None = None
    issue_type: ProfileIssueType
    severity: Severity = Severity.LOW
    scope: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    message: str

    @model_validator(mode="after")
    def _populate_and_validate_issue_id(self):
        expected = build_profile_issue_id(self.issue_type, self.scope)
        if self.issue_id is None:
            self.issue_id = expected
        elif self.issue_id != expected:
            raise ValueError("issue_id does not match issue_type and normalized scope")
        return self


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)

    name: str
    pandas_dtype: str
    inferred_type: Literal["empty", "boolean", "numeric", "datetime", "text", "mixed", "unknown"]
    row_count: int = Field(ge=0)
    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    null_ratio: float = Field(ge=0.0, le=1.0)
    distinct_count: int = Field(ge=0)
    distinct_ratio: float = Field(ge=0.0, le=1.0)
    value_storage_policy: Literal["stored", "omitted_high_cardinality", "redacted_sensitive"] = "stored"
    sensitive_data_detected: bool = False
    redaction_applied: bool = False
    top_values: list[dict[str, Any]] = Field(default_factory=list)
    sample_values: list[Any] = Field(default_factory=list)
    python_types: list[str] = Field(default_factory=list)
    numeric_parseable_count: int = Field(ge=0)
    numeric_parse_conflict_count: int = Field(ge=0)
    datetime_parseable_count: int = Field(ge=0)
    datetime_parse_conflict_count: int = Field(ge=0)
    quality_issue_types: list[ProfileIssueType] = Field(default_factory=list)


class DatasetProfile(InsightModel):
    dataset_id: str
    version_id: str
    source_content_hash: str
    profiler_version: str = "legacy"
    configuration_hash: str = ""
    file_ref: str
    profile_ref: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    duplicate_row_count: int = Field(default=0, ge=0)
    duplicate_row_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_group_member_count: int = Field(default=0, ge=0)
    duplicate_group_member_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_excess_row_count: int = Field(default=0, ge=0)
    duplicate_excess_row_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    sample_policy: Literal["disabled", "enabled"] = "disabled"
    redaction_applied: bool = False
    sensitive_data_detected: bool = False
    columns: list[ColumnProfile] = Field(default_factory=list)
    quality_issues: list[ProfileQualityIssue] = Field(default_factory=list)

    @field_validator("file_ref", "profile_ref")
    @classmethod
    def _relative_refs(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("profile references must be workspace-relative paths")
        return normalized


class CleaningProposal(InsightModel):
    dataset_version_id: str
    problem_type: str
    severity: Severity = Severity.INFO
    confidence: float = Field(ge=0.0, le=1.0)
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommended_operation: str
    alternatives: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    status: Literal["pending", "approved", "rejected", "applied"] = "pending"


class CleaningOperation(InsightModel):
    proposal_id: str | None = None
    operation_type: str
    input_version_id: str
    output_version_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    status: Literal["previewed", "running", "completed", "failed", "undone"] = "previewed"
    reversible: bool = True
    before_metrics: dict[str, Any] = Field(default_factory=dict)
    after_metrics: dict[str, Any] = Field(default_factory=dict)
    metric_delta: dict[str, Any] = Field(default_factory=dict)
    animation_payload: dict[str, Any] = Field(default_factory=dict)


class GoalType(StrEnum):
    TREND_ANALYSIS = "trend_analysis"
    COMPARISON = "comparison"
    DATA_QUALITY_REVIEW = "data_quality_review"
    DESCRIPTIVE_ANALYSIS = "descriptive_analysis"
    GROUP_COMPARISON = "group_comparison"
    ANOMALY_DETECTION = "anomaly_detection"
    DRIVER_ANALYSIS = "driver_analysis"
    SEGMENT_ANALYSIS = "segment_analysis"
    DISTRIBUTION_ANALYSIS = "distribution_analysis"
    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    FORECASTING = "forecasting"
    SCENARIO_ANALYSIS = "scenario_analysis"
    CAUSAL_HYPOTHESIS = "causal_hypothesis"


class GoalFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)

    column: str
    operator: str
    value: Any = None

    @field_validator("column", "operator")
    @classmethod
    def _non_empty_filter_field(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("filter fields must not be empty")
        return value.strip()


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str
    label_code: str | None = None

    @field_validator("label")
    @classmethod
    def _non_empty_label(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("label must not be empty")
        return value.strip()

    @field_validator("label_code")
    @classmethod
    def _optional_label_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str
    text_code: str | None = None
    response_type: Literal["single_choice", "free_text"] = Field(
        default="single_choice",
        alias="responseType",
        serialization_alias="responseType",
    )
    options: list[ClarificationOption] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("text must not be empty")
        return value.strip()

    @field_validator("text_code")
    @classmethod
    def _optional_text_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class IntentRequest(InsightModel):
    dataset_id: str
    dataset_version_id: str
    user_input: str = Field(min_length=1, max_length=2000)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    status: Literal["created", "awaiting_clarification", "candidates_ready", "confirmed"] = "created"

    @field_validator("dataset_id", "dataset_version_id", "user_input")
    @classmethod
    def _non_empty_intent_field(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("intent fields must not be empty")
        return value.strip()


class GoalCandidate(InsightModel):
    intent_id: str
    dataset_id: str
    dataset_version_id: str
    title: str
    description: str = ""
    goal_type: GoalType
    target_metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    time_column: str | None = None
    filters: list[GoalFilter] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True

    @field_validator("intent_id", "dataset_id", "dataset_version_id", "title")
    @classmethod
    def _non_empty_candidate_field(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("goal candidate fields must not be empty")
        return value.strip()

    @field_validator("target_metric", "time_column")
    @classmethod
    def _optional_candidate_column(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AnalysisGoal(InsightModel):
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    intent_id: str | None = None
    source_candidate_id: str | None = None
    goal_type: GoalType
    title: str
    target_column: str | None = None
    target_metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    time_column: str | None = None
    filters: list[GoalFilter] = Field(default_factory=list)
    task_type: Literal["descriptive", "regression", "classification", "forecasting", "anomaly"] = "descriptive"
    description: str = ""
    reasoning: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["candidate", "confirmed", "rejected"] = "candidate"

    @field_validator(
        "dataset_id",
        "dataset_version_id",
        "intent_id",
        "source_candidate_id",
        "target_column",
        "target_metric",
        "time_column",
    )
    @classmethod
    def _optional_goal_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AgentRunStatus(StrEnum):
    CREATED = "created"
    CONTEXT_BUILDING = "context_building"
    PROFILING = "profiling"
    WAITING_GOAL_CONFIRMATION = "waiting_goal_confirmation"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    CLEANING = "cleaning"
    ANALYZING = "analyzing"
    EXPERIMENTING = "experimenting"
    SYNTHESIZING = "synthesizing"
    WAITING_USER_INPUT = "waiting_user_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class AgentRun(InsightModel):
    goal_id: str | None = None
    dataset_version_id: str | None = None
    execution_kind: str = "deterministic_insight"
    source_table_refs: list[str] = Field(default_factory=list)
    interrupted_at: datetime | None = None
    resume_cursor_hash: str | None = None
    status: AgentRunStatus = AgentRunStatus.CREATED
    current_stage: str = "created"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    final_summary_ref: str | None = None


class AgentStep(InsightModel):
    run_id: str
    type: Literal["progress", "tool_call", "observation", "approval", "artifact", "claim", "error"]
    title: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    progress_text: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    collapsed_by_default: bool = True


class Experiment(InsightModel):
    experiment_type: str
    task_type: Literal["regression", "classification", "forecasting", "anomaly", "descriptive"]
    dataset_version_id: str
    target_column: str | None = None
    feature_columns: list[str] = Field(default_factory=list)
    excluded_columns: list[str] = Field(default_factory=list)
    metric: str | None = None
    validation_strategy: str
    seed: int = 42
    status: Literal["created", "running", "completed", "failed", "invalid"] = "created"
    manifest_ref: str | None = None
    result_ref: str | None = None


class ClaimType(StrEnum):
    DESCRIPTIVE = "descriptive"
    PREDICTIVE = "predictive"
    MODEL_ATTRIBUTION = "model_attribution"
    CAUSAL_HYPOTHESIS = "causal_hypothesis"
    DATA_QUALITY = "data_quality"


class SupportLevel(StrEnum):
    DIRECT = "direct"
    DERIVED = "derived"
    HYPOTHESIS = "hypothesis"
    UNSUPPORTED = "unsupported"


class EvidenceRef(InsightModel):
    source_type: Literal["dataset", "operation", "experiment", "artifact", "material", "knowledge"]
    source_id: str
    dataset_version_id: str | None = None
    artifact_id: str | None = None
    metric: str | None = None
    value: Any = None
    content_hash: str | None = None


class Claim(InsightModel):
    statement: str
    claim_type: ClaimType
    support_level: SupportLevel
    confidence: Literal["low", "medium", "high"]
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_or_unsupported(cls, value: list[str], info):
        support_level = info.data.get("support_level")
        if support_level != SupportLevel.UNSUPPORTED.value and not value:
            raise ValueError("supported claims must reference at least one evidence item")
        return value


class Approval(InsightModel):
    action_type: str
    action_ref: str
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    requested_by: str
    decided_by: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
