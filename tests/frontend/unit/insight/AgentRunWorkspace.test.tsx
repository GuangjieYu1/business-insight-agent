import React from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const translate = (key: string, params?: Record<string, unknown>) => {
    if (key === 'insight.run.processDrawer.subtitle') return `Run ${params?.runId}`;
    if (key === 'insight.run.final.runReference') return `Run reference: ${params?.runId}`;
    return key;
};

vi.mock('react-i18next', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react-i18next')>();
    return {
        ...actual,
        useTranslation: () => ({ t: translate }),
    };
});

vi.mock('../../../../src/insight/api/agentRunClient', () => ({
    cancelAgentRun: vi.fn(),
    createAgentRun: vi.fn(),
    listAgentRuns: vi.fn(),
    readAgentRun: vi.fn(),
    subscribeToAgentRunEvents: vi.fn(() => ({ close: vi.fn() })),
}));

vi.mock('../../../../src/insight/api/goalClient', () => ({
    createAnalysisGoal: vi.fn(),
    createIntentSnapshot: vi.fn(),
    readAnalysisGoal: vi.fn(),
    readInsightProject: vi.fn(),
    readIntentSnapshot: vi.fn(),
}));

import { createAgentRun } from '../../../../src/insight/api/agentRunClient';
import { AgentRunWorkspace } from '../../../../src/insight/components/AgentRunWorkspace';
import { ProcessDrawer } from '../../../../src/insight/components/ProcessDrawer';
import {
    agentRunReducer,
    type AgentRunResourceState,
} from '../../../../src/insight/store/agentRunSlice';
import {
    goalReducer,
    type GoalResourceState,
} from '../../../../src/insight/store/goalSlice';
import type { AgentRun, AgentStep, AnalysisGoal, DatasetProfile, FinalSummary } from '../../../../src/insight/types';

const profile: DatasetProfile = {
    id: 'profile_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    dataset_id: 'dataset_sales',
    version_id: 'version_000',
    source_content_hash: 'hash_1',
    profiler_version: '1.0',
    configuration_hash: 'config_1',
    file_ref: 'profiles/version_000.json',
    profile_ref: 'profiles/version_000.json',
    row_count: 3,
    column_count: 4,
    duplicate_row_count: 0,
    duplicate_row_ratio: 0,
    duplicate_group_member_count: 0,
    duplicate_group_member_ratio: 0,
    duplicate_excess_row_count: 0,
    duplicate_excess_row_ratio: 0,
    sample_policy: 'disabled',
    redaction_applied: false,
    sensitive_data_detected: false,
    columns: [
        {
            name: 'date',
            pandas_dtype: 'object',
            inferred_type: 'datetime',
            row_count: 3,
            non_null_count: 3,
            null_count: 0,
            null_ratio: 0,
            distinct_count: 3,
            distinct_ratio: 1,
            value_storage_policy: 'stored',
            sensitive_data_detected: false,
            redaction_applied: false,
            top_values: [],
            sample_values: [],
            python_types: ['str'],
            numeric_parseable_count: 0,
            numeric_parse_conflict_count: 0,
            datetime_parseable_count: 3,
            datetime_parse_conflict_count: 0,
            quality_issue_types: [],
        },
        {
            name: 'revenue',
            pandas_dtype: 'float64',
            inferred_type: 'numeric',
            row_count: 3,
            non_null_count: 3,
            null_count: 0,
            null_ratio: 0,
            distinct_count: 3,
            distinct_ratio: 1,
            value_storage_policy: 'stored',
            sensitive_data_detected: false,
            redaction_applied: false,
            top_values: [],
            sample_values: [],
            python_types: ['float'],
            numeric_parseable_count: 3,
            numeric_parse_conflict_count: 0,
            datetime_parseable_count: 0,
            datetime_parse_conflict_count: 0,
            quality_issue_types: [],
        },
        {
            name: 'region',
            pandas_dtype: 'object',
            inferred_type: 'text',
            row_count: 3,
            non_null_count: 3,
            null_count: 0,
            null_ratio: 0,
            distinct_count: 2,
            distinct_ratio: 0.67,
            value_storage_policy: 'stored',
            sensitive_data_detected: false,
            redaction_applied: false,
            top_values: [],
            sample_values: [],
            python_types: ['str'],
            numeric_parseable_count: 0,
            numeric_parse_conflict_count: 0,
            datetime_parseable_count: 0,
            datetime_parse_conflict_count: 0,
            quality_issue_types: [],
        },
    ],
    quality_issues: [],
};

const baseRun: AgentRun = {
    id: 'run_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:01Z',
    goal_id: null,
    dataset_version_id: 'version_000',
    status: 'completed',
    current_stage: 'completed',
    started_at: '2026-07-13T00:00:00Z',
    completed_at: '2026-07-13T00:00:01Z',
    final_summary_ref: 'runs/run_1/final_summary.json',
};

const completedStep: AgentStep = {
    id: 'step_completed',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:01Z',
    run_id: 'run_1',
    type: 'progress',
    title: 'Analysis run completed',
    status: 'completed',
    started_at: '2026-07-13T00:00:00Z',
    completed_at: '2026-07-13T00:00:01Z',
    input_refs: [],
    output_refs: ['summary_1'],
    progress_text: 'No approval is required.',
    detail: {},
    collapsed_by_default: true,
};

const summary: FinalSummary = {
    id: 'summary_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:01Z',
    updated_at: '2026-07-13T00:00:01Z',
    run_id: 'run_1',
    title: 'Data quality review complete',
    executive_summary: 'No deterministic cleaning approval is required.',
    claim_refs: [],
    operation_refs: [],
    metric_changes: [{ metric: 'quality_issue_count', value: 0 }],
    artifact_refs: [],
    limitations: ['This is not a causal result.'],
    next_steps: ['Confirm a business goal.'],
};

const confirmedGoal: AnalysisGoal = {
    id: 'goal_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    dataset_id: 'dataset_sales',
    dataset_version_id: 'version_000',
    intent_id: 'intent_1',
    source_candidate_id: 'goal_candidate_1',
    goal_type: 'driver_analysis',
    title: 'Analyze revenue decline drivers',
    target_column: 'revenue',
    target_metric: 'revenue',
    dimensions: ['region'],
    time_column: 'date',
    filters: [],
    task_type: 'descriptive',
    description: '',
    reasoning: [],
    confidence: 0.82,
    status: 'confirmed',
};

function emptyAgentResource(): AgentRunResourceState {
    return {
        datasetId: 'dataset_sales',
        run: null,
        steps: [],
        finalSummary: null,
        status: 'ready',
        connectionStatus: 'closed',
        lastEventId: null,
        processOpen: false,
        error: null,
        currentRequestId: null,
    };
}

function readyGoalResource(goal: AnalysisGoal | null): GoalResourceState {
    return {
        resourceKey: 'dataset_sales::version_000',
        datasetId: 'dataset_sales',
        versionId: 'version_000',
        project: {
            id: 'project_1',
            schema_version: '1.0',
            workspace_id: 'workspace_1',
            created_at: '2026-07-13T00:00:00Z',
            updated_at: '2026-07-13T00:00:00Z',
            name: 'Project',
            description: '',
            status: 'active',
            default_language: 'zh-CN',
            active_dataset_id: 'dataset_sales',
            active_goal_id: goal?.id || null,
        },
        activeGoal: goal,
        intent: null,
        goalCandidates: [],
        questions: [],
        status: 'ready',
        error: null,
        currentRequestId: null,
    };
}

function resourceFor(
    run: AgentRun,
    steps: AgentStep[],
    finalSummary: FinalSummary | null,
): AgentRunResourceState {
    return {
        datasetId: 'dataset_sales',
        run,
        steps,
        finalSummary,
        status: 'ready',
        connectionStatus: 'closed',
        lastEventId: null,
        processOpen: false,
        error: null,
        currentRequestId: null,
    };
}

function renderWorkspace(
    agentResource: AgentRunResourceState,
    goalResource: GoalResourceState,
    onOpenCleaning = vi.fn(),
) {
    const store = configureStore({
        reducer: {
            agentRun: agentRunReducer,
            goal: goalReducer,
        },
        preloadedState: {
            agentRun: {
                resources: {
                    dataset_sales: agentResource,
                },
            },
            goal: {
                resources: {
                    'dataset_sales::version_000': goalResource,
                },
            },
        },
    });
    render(
        <Provider store={store}>
            <AgentRunWorkspace
                datasetId="dataset_sales"
                versionId="version_000"
                profile={profile}
                onOpenCleaning={onOpenCleaning}
            />
        </Provider>,
    );
    return { store, onOpenCleaning };
}

describe('AgentRunWorkspace', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('shows the goal confirmation flow and hides direct run start when no confirmed goal exists', () => {
        renderWorkspace(emptyAgentResource(), readyGoalResource(null));

        expect(screen.getByText('insight.goal.panelTitle')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'insight.run.start' })).not.toBeInTheDocument();
        expect(screen.getByText('insight.goal.candidatesEmpty')).toBeInTheDocument();
    });

    it('shows the confirmed goal summary and starts a background run with goalId', async () => {
        vi.mocked(createAgentRun).mockResolvedValue({
            run: { ...baseRun, goal_id: 'goal_1', status: 'created', current_stage: 'created', completed_at: null, final_summary_ref: null },
            steps: [{ ...completedStep, title: 'Analysis run started' }],
            finalSummary: null,
            profile: null,
            proposals: [],
            executionMode: 'background',
        });

        renderWorkspace(emptyAgentResource(), readyGoalResource(confirmedGoal));
        fireEvent.click(screen.getByRole('button', { name: 'insight.goal.startWithGoal' }));

        await waitFor(() => {
            expect(createAgentRun).toHaveBeenCalledWith(
                {
                    datasetId: 'dataset_sales',
                    versionId: 'version_000',
                    goalId: 'goal_1',
                    executionMode: 'background',
                },
                expect.any(AbortSignal),
            );
        });
    });

    it('keeps a completed legacy run visible while prompting for a goal for the next run', () => {
        renderWorkspace(resourceFor(baseRun, [completedStep], summary), readyGoalResource(null));

        expect(screen.getByText('Data quality review complete')).toBeInTheDocument();
        expect(screen.getByText('No deterministic cleaning approval is required.')).toBeInTheDocument();
        expect(screen.getByText('insight.goal.panelTitle')).toBeInTheDocument();
        expect(screen.getByText('Confirm a business goal.')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'insight.run.viewFullProcess' })).toBeInTheDocument();
    });

    it('renders the complete persisted analysis process in ProcessDrawer', async () => {
        render(
            <ProcessDrawer
                open
                run={baseRun}
                steps={[completedStep]}
                t={translate as any}
                onClose={vi.fn()}
            />,
        );

        expect(await screen.findByText('insight.run.processDrawer.title')).toBeInTheDocument();
        expect(screen.getByText('Run run_1')).toBeInTheDocument();
        expect(screen.getByText('Analysis run completed')).toBeInTheDocument();
        expect(screen.getByText('No approval is required.')).toBeInTheDocument();
    });

    it('restores a waiting-approval run and sends the user to cleaning review', () => {
        const waitingRun: AgentRun = {
            ...baseRun,
            goal_id: 'goal_1',
            status: 'waiting_approval',
            current_stage: 'waiting_approval',
            completed_at: null,
            final_summary_ref: null,
        };
        const approvalStep: AgentStep = {
            ...completedStep,
            id: 'step_approval',
            type: 'approval',
            title: 'Cleaning approval required',
            status: 'pending',
            completed_at: null,
            output_refs: [],
            progress_text: 'Review the proposed cleaning operations.',
        };
        const onOpenCleaning = vi.fn();

        renderWorkspace(resourceFor(waitingRun, [approvalStep], null), readyGoalResource(confirmedGoal), onOpenCleaning);

        expect(screen.getByText('insight.run.waitingApproval')).toBeInTheDocument();
        expect(screen.getAllByText('Cleaning approval required').length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('button', { name: 'insight.run.openCleaning' }));
        expect(onOpenCleaning).toHaveBeenCalledTimes(1);
    });
});