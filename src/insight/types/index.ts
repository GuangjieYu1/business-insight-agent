export type InsightSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type ProfileIssueType =
    | 'empty_column'
    | 'constant_column'
    | 'near_constant_column'
    | 'high_missing_column'
    | 'duplicate_rows'
    | 'duplicate_columns'
    | 'mixed_type_column'
    | 'numeric_parse_conflict'
    | 'datetime_parse_conflict'
    | 'dirty_character_column'
    | 'high_cardinality_id_like'
    | 'outlier_warning'
    | 'invalid_header'
    | 'meaningless_header_candidate'
    | 'infinite_value'
    | 'whitespace_pollution';

export type InferredColumnType =
    | 'empty'
    | 'boolean'
    | 'numeric'
    | 'datetime'
    | 'text'
    | 'mixed'
    | 'unknown';

export type CleaningProposalStatus = 'pending' | 'approved' | 'rejected' | 'applied';
export type CleaningOperationStatus = 'previewed' | 'running' | 'completed' | 'failed' | 'undone';
export type SupportedCleaningOperation =
    | 'trim_string'
    | 'replace_invalid_character'
    | 'drop_duplicate_rows'
    | 'rename_column'
    | 'drop_column';

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

export type GoalType =
    | 'trend_analysis'
    | 'comparison'
    | 'data_quality_review'
    | 'descriptive_analysis'
    | 'group_comparison'
    | 'anomaly_detection'
    | 'driver_analysis'
    | 'segment_analysis'
    | 'distribution_analysis'
    | 'regression'
    | 'classification'
    | 'forecasting'
    | 'scenario_analysis'
    | 'causal_hypothesis';

export interface GoalFilter {
    column: string;
    operator: string;
    value: unknown;
}

export interface ClarificationOption {
    label: string;
    label_code: string | null;
}

export interface ClarificationQuestion {
    text: string;
    text_code: string | null;
    responseType: 'single_choice' | 'free_text';
    options: ClarificationOption[];
}

export interface IntentRequest extends InsightEntityBase {
    dataset_id: string;
    dataset_version_id: string;
    user_input: string;
    clarification_questions: ClarificationQuestion[];
    status: 'created' | 'awaiting_clarification' | 'candidates_ready' | 'confirmed';
}

export interface GoalCandidate extends InsightEntityBase {
    intent_id: string;
    dataset_id: string;
    dataset_version_id: string;
    title: string;
    description: string;
    goal_type: GoalType;
    target_metric: string | null;
    dimensions: string[];
    time_column: string | null;
    filters: GoalFilter[];
    confidence: number;
    assumptions: string[];
    missing_information: string[];
    requires_confirmation: boolean;
}

export interface AnalysisGoal extends InsightEntityBase {
    dataset_id: string | null;
    dataset_version_id: string | null;
    intent_id: string | null;
    source_candidate_id: string | null;
    goal_type: GoalType;
    title: string;
    target_column: string | null;
    target_metric: string | null;
    dimensions: string[];
    time_column: string | null;
    filters: GoalFilter[];
    task_type: 'descriptive' | 'regression' | 'classification' | 'forecasting' | 'anomaly';
    description: string;
    reasoning: string[];
    confidence: number;
    status: 'candidate' | 'confirmed' | 'rejected';
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
    issue_id: string;
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

export interface CleaningProposal extends InsightEntityBase {
    dataset_version_id: string;
    problem_type: ProfileIssueType | string;
    severity: InsightSeverity;
    confidence: number;
    scope: Record<string, unknown>;
    evidence: Record<string, unknown>;
    recommended_operation: string;
    alternatives: string[];
    requires_approval: boolean;
    status: CleaningProposalStatus;
}

export interface CleaningOperation extends InsightEntityBase {
    proposal_id: string | null;
    operation_type: string;
    input_version_id: string;
    output_version_id: string | null;
    parameters: Record<string, unknown>;
    reason: string;
    status: CleaningOperationStatus;
    reversible: boolean;
    before_metrics: Record<string, number>;
    after_metrics: Record<string, number>;
    metric_delta: Record<string, number>;
    animation_payload: {
        affected_rows?: number;
        affected_columns?: string[];
        sample_diff?: Array<Record<string, unknown>>;
        raw_values_included?: boolean;
        [key: string]: unknown;
    };
}

export interface CleaningPreviewResponse {
    proposal: CleaningProposal;
    operation: CleaningOperation;
    warnings: string[];
    sampleDiff: Array<Record<string, unknown>>;
}

export interface CleaningApplyResponse {
    proposal: CleaningProposal;
    dataset: Dataset;
    version: DatasetVersion;
    operation: CleaningOperation;
    idempotent: boolean;
}

export interface DatasetVersionsResponse {
    dataset: Dataset;
    versions: DatasetVersion[];
    activeVersionId: string;
}

export interface UndoOperationResponse {
    dataset: Dataset;
    activeVersion: DatasetVersion;
    previousVersion: DatasetVersion | null;
    operation: CleaningOperation;
    undoneOperation: CleaningOperation | null;
}

export interface RegisterDatasetResponse {
    project: InsightProject;
    dataset: Dataset;
    version: DatasetVersion;
    created: boolean;
}

export interface IntentSnapshotResponse {
    intent: IntentRequest;
    goalCandidates: GoalCandidate[];
    questions: ClarificationQuestion[];
}

export interface GoalMutationResponse {
    goal: AnalysisGoal;
    project: InsightProject;
    created: boolean;
}

export interface GoalReadResponse {
    goal: AnalysisGoal;
}

export interface ProjectReadResponse {
    project: InsightProject;
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

export type AgentRunStatus =
    | 'created'
    | 'context_building'
    | 'profiling'
    | 'waiting_goal_confirmation'
    | 'planning'
    | 'waiting_approval'
    | 'cleaning'
    | 'analyzing'
    | 'experimenting'
    | 'synthesizing'
    | 'waiting_user_input'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'interrupted';

export type AgentStepType =
    | 'progress'
    | 'tool_call'
    | 'observation'
    | 'approval'
    | 'artifact'
    | 'claim'
    | 'error';

export type AgentStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AgentRun extends InsightEntityBase {
    goal_id: string | null;
    dataset_version_id: string | null;
    execution_kind: string;
    source_table_refs: string[];
    interrupted_at: string | null;
    resume_cursor_hash: string | null;
    status: AgentRunStatus;
    current_stage: string;
    started_at: string | null;
    completed_at: string | null;
    final_summary_ref: string | null;
}

export interface AgentStep extends InsightEntityBase {
    run_id: string;
    type: AgentStepType;
    title: string;
    status: AgentStepStatus;
    started_at: string | null;
    completed_at: string | null;
    input_refs: string[];
    output_refs: string[];
    progress_text: string;
    detail: Record<string, unknown>;
    collapsed_by_default: boolean;
}

export interface FinalSummary extends InsightEntityBase {
    run_id: string;
    title: string;
    executive_summary: string;
    claim_refs: string[];
    operation_refs: string[];
    metric_changes: Array<Record<string, unknown>>;
    artifact_refs: string[];
    limitations: string[];
    next_steps: string[];
}

export interface AgentRunSnapshot {
    run: AgentRun;
    steps: AgentStep[];
    finalSummary: FinalSummary | null;
}

export interface CreateAgentRunResponse extends AgentRunSnapshot {
    profile: DatasetProfile | null;
    proposals: CleaningProposal[];
    executionMode: 'synchronous' | 'background';
}

export interface AgentRunEventPayload {
    eventType: string;
    runId: string;
    stepId?: string;
    stage?: string;
    status?: AgentStepStatus;
    runStatus?: AgentRunStatus;
    title?: string;
    progressText?: string;
    detail?: Record<string, unknown>;
    inputRefs?: string[];
    outputRefs?: string[];
    collapsedByDefault?: boolean;
    timestamp: string;
}
