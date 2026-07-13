import { apiRequest } from '../../app/apiClient';
import type {
    GoalFilter,
    GoalMutationResponse,
    GoalReadResponse,
    GoalType,
    IntentSnapshotResponse,
    ProjectReadResponse,
} from '../types';

const insightUrl = (path: string): string => `/api/insight${path}`;

export interface CreateIntentParams {
    datasetId: string;
    datasetVersionId: string;
    userInput: string;
}

export interface SaveGoalParams {
    datasetId: string;
    datasetVersionId: string;
    sourceCandidateId?: string;
    intentId?: string;
    title?: string;
    goalType?: GoalType;
    targetMetric?: string | null;
    dimensions?: string[] | null;
    timeColumn?: string | null;
    filters?: GoalFilter[] | null;
    description?: string | null;
    reasoning?: string[] | null;
    confidence?: number;
    taskType?: 'descriptive' | 'regression' | 'classification' | 'forecasting' | 'anomaly';
}

export interface UpdateGoalParams {
    title?: string;
    goalType?: GoalType;
    targetMetric?: string | null;
    dimensions?: string[] | null;
    timeColumn?: string | null;
    filters?: GoalFilter[] | null;
    description?: string | null;
    reasoning?: string[] | null;
    confidence?: number;
    status?: 'candidate' | 'confirmed' | 'rejected';
    taskType?: 'descriptive' | 'regression' | 'classification' | 'forecasting' | 'anomaly';
}

export async function readInsightProject(signal?: AbortSignal): Promise<ProjectReadResponse['project']> {
    const { data } = await apiRequest<ProjectReadResponse>(insightUrl('/project'), {
        method: 'GET',
        signal,
    });
    return data.project;
}

export async function createIntentSnapshot(
    params: CreateIntentParams,
    signal?: AbortSignal,
): Promise<IntentSnapshotResponse> {
    const { data } = await apiRequest<IntentSnapshotResponse>(insightUrl('/intents'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
        signal,
    });
    return data;
}

export async function readIntentSnapshot(
    intentId: string,
    signal?: AbortSignal,
): Promise<IntentSnapshotResponse> {
    const { data } = await apiRequest<IntentSnapshotResponse>(
        insightUrl(`/intents/${encodeURIComponent(intentId)}`),
        { method: 'GET', signal },
    );
    return data;
}

export async function createAnalysisGoal(
    params: SaveGoalParams,
    signal?: AbortSignal,
): Promise<GoalMutationResponse> {
    const { data } = await apiRequest<GoalMutationResponse>(insightUrl('/goals'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            datasetId: params.datasetId,
            datasetVersionId: params.datasetVersionId,
            sourceCandidateId: params.sourceCandidateId,
            intentId: params.intentId,
            title: params.title,
            goalType: params.goalType,
            targetMetric: params.targetMetric,
            dimensions: params.dimensions,
            timeColumn: params.timeColumn,
            filters: params.filters,
            description: params.description,
            reasoning: params.reasoning,
            confidence: params.confidence,
            taskType: params.taskType,
        }),
        signal,
    });
    return data;
}

export async function readAnalysisGoal(
    goalId: string,
    signal?: AbortSignal,
): Promise<GoalReadResponse['goal']> {
    const { data } = await apiRequest<GoalReadResponse>(
        insightUrl(`/goals/${encodeURIComponent(goalId)}`),
        { method: 'GET', signal },
    );
    return data.goal;
}

export async function updateAnalysisGoal(
    goalId: string,
    params: UpdateGoalParams,
    signal?: AbortSignal,
): Promise<GoalMutationResponse> {
    const { data } = await apiRequest<GoalMutationResponse>(
        insightUrl(`/goals/${encodeURIComponent(goalId)}`),
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
            signal,
        },
    );
    return data;
}