import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/app/apiClient', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../../src/app/apiClient')>();
    return {
        ...actual,
        apiRequest: vi.fn(),
    };
});

import { apiRequest } from '../../../../src/app/apiClient';
import {
    createAnalysisGoal,
    createIntentSnapshot,
    readAnalysisGoal,
    readInsightProject,
    readIntentSnapshot,
    updateAnalysisGoal,
} from '../../../../src/insight/api/goalClient';

describe('goalClient', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('calls the project, intent, and goal endpoints with canonical payloads', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { project: { id: 'project_1' } } as any })
            .mockResolvedValueOnce({ data: { intent: { id: 'intent_1' }, goalCandidates: [], questions: [] } as any })
            .mockResolvedValueOnce({ data: { intent: { id: 'intent_1' }, goalCandidates: [], questions: [] } as any })
            .mockResolvedValueOnce({ data: { goal: { id: 'goal_1' }, project: { id: 'project_1' }, created: true } as any })
            .mockResolvedValueOnce({ data: { goal: { id: 'goal_1' } } as any })
            .mockResolvedValueOnce({ data: { goal: { id: 'goal_1' }, project: { id: 'project_1' }, created: false } as any });

        await readInsightProject();
        await createIntentSnapshot({
            datasetId: 'dataset_sales',
            datasetVersionId: 'version_000',
            userInput: 'why did revenue decline?',
        });
        await readIntentSnapshot('intent/1');
        await createAnalysisGoal({
            datasetId: 'dataset_sales',
            datasetVersionId: 'version_000',
            sourceCandidateId: 'goal_candidate_1',
            goalType: 'driver_analysis',
            title: 'Analyze revenue decline drivers',
            targetMetric: 'revenue',
            dimensions: ['region'],
            timeColumn: 'date',
        });
        await readAnalysisGoal('goal/1');
        await updateAnalysisGoal('goal/1', {
            dimensions: ['region', 'product'],
        });

        expect(apiRequest).toHaveBeenNthCalledWith(
            1,
            '/api/insight/project',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/insight/intents',
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({
                    datasetId: 'dataset_sales',
                    datasetVersionId: 'version_000',
                    userInput: 'why did revenue decline?',
                }),
            }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            3,
            '/api/insight/intents/intent%2F1',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            4,
            '/api/insight/goals',
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({
                    datasetId: 'dataset_sales',
                    datasetVersionId: 'version_000',
                    sourceCandidateId: 'goal_candidate_1',
                    intentId: undefined,
                    title: 'Analyze revenue decline drivers',
                    goalType: 'driver_analysis',
                    targetMetric: 'revenue',
                    dimensions: ['region'],
                    timeColumn: 'date',
                    filters: undefined,
                    description: undefined,
                    reasoning: undefined,
                    confidence: undefined,
                    taskType: undefined,
                }),
            }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            5,
            '/api/insight/goals/goal%2F1',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            6,
            '/api/insight/goals/goal%2F1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ dimensions: ['region', 'product'] }),
            }),
        );
    });
});