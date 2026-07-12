export type InsightSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type ProfileIssueType =
    | 'empty_column'
    | 'constant_column'
    | 'near_constant_column'
    | 'high_missing_column'
    | 'duplicate_rows'
    | 'mixed_type_column'
    | 'numeric_parse_conflict'
    | 'datetime_parse_conflict';

export type InferredColumnType =
    | 'empty'
    | 'boolean'
    | 'numeric'
    | 'datetime'
    | 'text'
    | 'mixed'
    | 'unknown';

export interface InsightEntityBase {
    id: string;
    schema_version: string;
    workspace_id: string;
    created_at: string;
    updated_at: string;
}

export interface InsightProject extends InsightEntityBase {
    name: string;
    description: string;
    status: 'active' | 'archived';
    default_language: string;
    active_dataset_id: string | null;
    active_goal_id: string | null;
}

export interface Dataset extends InsightEntityBase {
    name: string;
    source_material_id: string | null;
    original_table_ref: string;
    original_version_id: string;
    active_version_id: string;
}

export interface DatasetVersion extends InsightEntityBase {
    dataset_id: string;
    parent_version_id: string | null;
    created_by_operation_id: string | null;
    content_hash: string;
    row_count: number;
    column_count: number;
    file_ref: string;
    status: 'active' | 'historical' | 'invalid';
}

export interface ProfileQualityIssue {
    issue_type: ProfileIssueType;
    severity: InsightSeverity;
    scope: Record<string, unknown>;
    metrics: Record<string, unknown>;
    message: string;
}

export interface ColumnProfile {
    name: string;
    pandas_dtype: string;
    inferred_type: InferredColumnType;
    row_count: number;
    non_null_count: number;
    null_count: number;
    null_ratio: number;
    distinct_count: number;
    distinct_ratio: number;
    value_storage_policy: 'stored' | 'omitted_high_cardinality' | 'redacted_sensitive';
    sensitive_data_detected: boolean;
    redaction_applied: boolean;
    top_values: Array<Record<string, unknown>>;
    sample_values: unknown[];
    python_types: string[];
    numeric_parseable_count: number;
    numeric_parse_conflict_count: number;
    datetime_parseable_count: number;
    datetime_parse_conflict_count: number;
    quality_issue_types: ProfileIssueType[];
}

export interface DatasetProfile extends InsightEntityBase {
    dataset_id: string;
    version_id: string;
    source_content_hash: string;
    profiler_version: string;
    configuration_hash: string;
    file_ref: string;
    profile_ref: string;
    row_count: number;
    column_count: number;
    duplicate_row_count: number;
    duplicate_row_ratio: number;
    duplicate_group_member_count: number;
    duplicate_group_member_ratio: number;
    duplicate_excess_row_count: number;
    duplicate_excess_row_ratio: number;
    sample_policy: 'disabled' | 'enabled';
    redaction_applied: boolean;
    sensitive_data_detected: boolean;
    columns: ColumnProfile[];
    quality_issues: ProfileQualityIssue[];
}

export interface RegisterDatasetResponse {
    project: InsightProject;
    dataset: Dataset;
    version: DatasetVersion;
    created: boolean;
}

export interface ReadDatasetProfileResponse {
    profile: DatasetProfile;
}

export interface InsightError {
    code: string;
    message: string;
    detail?: string;
    retryable: boolean;
    httpStatus?: number;
    requestId?: string;
}
