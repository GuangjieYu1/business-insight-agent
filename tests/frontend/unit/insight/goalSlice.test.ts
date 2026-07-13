import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/insight/api/goalClient', () => ({
    createAnalysisGoal: vi.fn(),
    createIntentSnapshot: vi.fn(),
    readAnalysisGoal: vi.fn(),
    readInsightProject: vi.fn(),
    readIntentSnapshot: vi.fn(),
}));

import {
    createAnalysisGoal,
    createIntentSnapshot,
    readAnalysisGoal,
    readInsightProject,
    readIntentSnapshot,
} from '../../../../src/insight/api/goalClient';
import {
    createGoalIntent,
    goalReducer,
    restoreGoalForDatasetVersion,
    saveAnalysisGoal,
} from '../../../../src/insight/store/goalSlice';
import type { AnalysisGoal, GoalCandidate, InsightProject, IntentRequest } from '../../../../src/insight/types';

const project: InsightProject = {
    id: 'project_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    name: 'Business Insight Project',
    description: '',
    status: 'active',
    default_language: 'zh-CN',
    active_dataset_id: 'dataset_sales',
    active_goal_id: 'goal_1',
};

const intent: IntentRequest = {
    id: 'intent_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    dataset_id: 'dataset_sales',
    dataset_version_id: 'version_000',
    user_input: 'why did revenue decline?',
    clarification_questions: [],
    status: 'candidates_ready',
};

const candidate: GoalCandidate = {
    id: 'goal_candidate_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    intent_id: 'intent_1',
    dataset_id: 'dataset_sales',
    dataset_version_id: 'version_000',
    title: 'Analyze revenue decline drivers',
    description: 'Compare revenue by region.',
    goal_type: 'driver_analysis',
    target_metric: 'revenue',
    dimensions: ['region'],
    time_column: 'date',
    filters: [],
    confidence: 0.82,
    assumptions: ['revenue is the key business metric'],
    missing_information: [],
    requires_confirmation: true,
};

const goal: AnalysisGoal = {
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

function createStore() {
    return configureStore({ reducer: { goal: goalReducer } });
}

describe('goalSlice', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('restores the active goal only when it matches the selected dataset version', async () => {
        vi.mocked(readInsightProject).mockResolvedValue(project);
        vi.mocked(readAnalysisGoal).mockResolvedValue(goal);
        vi.mocked(readIntentSnapshot).mockResolvedValue({
            intent,
            goalCandidates: [candidate],
            questions: [],
        });
        const store = createStore();

        await store.dispatch(restoreGoalForDatasetVersion({ datasetId: 'dataset_sales', versionId: 'version_000' }));
        const resource = store.getState().goal.resources['dataset_sales::version_000'];

        expect(resource.activeGoal?.id).toBe('goal_1');
        expect(resource.intent?.id).toBe('intent_1');
        expect(resource.goalCandidates).toHaveLength(1);
    });

    it('drops a mismatched active goal instead of leaking it across versions', async () => {
        vi.mocked(readInsightProject).mockResolvedValue(project);
        vi.mocked(readAnalysisGoal).mockResolvedValue({ ...goal, dataset_version_id: 'version_001' });
        const store = createStore();

        await store.dispatch(restoreGoalForDatasetVersion({ datasetId: 'dataset_sales', versionId: 'version_000' }));
        const resource = store.getState().goal.resources['dataset_sales::version_000'];

        expect(resource.activeGoal).toBeNull();
        expect(resource.intent).toBeNull();
    });

    it('stores deterministic candidates and confirmed goals from the backend responses', async () => {
        vi.mocked(readInsightProject).mockResolvedValue(project);
        vi.mocked(createIntentSnapshot).mockResolvedValue({
            intent,
            goalCandidates: [candidate],
            questions: [],
        });
        vi.mocked(createAnalysisGoal).mockResolvedValue({
            goal,
            project,
            created: true,
        });
        vi.mocked(readIntentSnapshot).mockResolvedValue({
            intent: { ...intent, status: 'confirmed' },
            goalCandidates: [candidate],
            questions: [],
        });
        const store = createStore();

        await store.dispatch(createGoalIntent({
            datasetId: 'dataset_sales',
            datasetVersionId: 'version_000',
            userInput: 'why did revenue decline?',
        }));
        await store.dispatch(saveAnalysisGoal({
            datasetId: 'dataset_sales',
            datasetVersionId: 'version_000',
            sourceCandidateId: 'goal_candidate_1',
        }));
        const resource = store.getState().goal.resources['dataset_sales::version_000'];

        expect(resource.intent?.status).toBe('confirmed');
        expect(resource.activeGoal?.id).toBe('goal_1');
        expect(resource.project?.active_goal_id).toBe('goal_1');
    });
});