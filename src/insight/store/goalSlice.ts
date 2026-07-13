import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { dfActions, type DataFormulatorState } from '../../app/dfSlice';
import {
    createAnalysisGoal,
    createIntentSnapshot,
    readAnalysisGoal,
    readInsightProject,
    readIntentSnapshot,
    type CreateIntentParams,
    type SaveGoalParams,
} from '../api/goalClient';
import { isInsightApiError, toInsightError } from '../api/insightClient';
import type {
    AnalysisGoal,
    GoalCandidate,
    InsightError,
    InsightProject,
    IntentRequest,
    ClarificationQuestion,
} from '../types';

export type GoalResourceStatus = 'idle' | 'loading' | 'generating' | 'confirming' | 'ready' | 'error';

export interface GoalResourceState {
    resourceKey: string;
    datasetId: string;
    versionId: string;
    project: InsightProject | null;
    activeGoal: AnalysisGoal | null;
    intent: IntentRequest | null;
    goalCandidates: GoalCandidate[];
    questions: ClarificationQuestion[];
    status: GoalResourceStatus;
    error: InsightError | null;
    currentRequestId: string | null;
}

export interface GoalState {
    resources: Record<string, GoalResourceState>;
}

export interface GoalRootState extends DataFormulatorState {
    goal: GoalState;
}

interface GoalSnapshotResult {
    resourceKey: string;
    datasetId: string;
    versionId: string;
    project: InsightProject;
    activeGoal: AnalysisGoal | null;
    intent: IntentRequest | null;
    goalCandidates: GoalCandidate[];
    questions: ClarificationQuestion[];
}

interface GoalMutationResult extends GoalSnapshotResult {
    created: boolean;
}

const createInitialGoalState = (): GoalState => ({ resources: {} });
const initialState: GoalState = createInitialGoalState();

export const makeGoalResourceKey = (datasetId: string, versionId: string): string => `${datasetId}::${versionId}`;

function createResource(datasetId: string, versionId: string): GoalResourceState {
    return {
        resourceKey: makeGoalResourceKey(datasetId, versionId),
        datasetId,
        versionId,
        project: null,
        activeGoal: null,
        intent: null,
        goalCandidates: [],
        questions: [],
        status: 'idle',
        error: null,
        currentRequestId: null,
    };
}

function ensureResource(state: GoalState, datasetId: string, versionId: string): GoalResourceState {
    const resourceKey = makeGoalResourceKey(datasetId, versionId);
    if (!state.resources[resourceKey]) {
        state.resources[resourceKey] = createResource(datasetId, versionId);
    }
    return state.resources[resourceKey];
}

function matchesDatasetVersion(goal: AnalysisGoal, datasetId: string, versionId: string): boolean {
    return goal.status === 'confirmed'
        && goal.dataset_id === datasetId
        && goal.dataset_version_id === versionId;
}

function preserveActiveGoal(
    activeGoal: AnalysisGoal | null,
    project: InsightProject,
    datasetId: string,
    versionId: string,
): AnalysisGoal | null {
    if (!activeGoal) {
        return null;
    }
    if (project.active_goal_id !== activeGoal.id) {
        return null;
    }
    return matchesDatasetVersion(activeGoal, datasetId, versionId) ? activeGoal : null;
}

async function loadIntentSnapshotForGoal(goal: AnalysisGoal, signal: AbortSignal): Promise<{
    intent: IntentRequest | null;
    goalCandidates: GoalCandidate[];
    questions: ClarificationQuestion[];
}> {
    if (!goal.intent_id) {
        return {
            intent: null,
            goalCandidates: [],
            questions: [],
        };
    }

    try {
        const snapshot = await readIntentSnapshot(goal.intent_id, signal);
        return {
            intent: snapshot.intent,
            goalCandidates: snapshot.goalCandidates,
            questions: snapshot.questions,
        };
    } catch (error) {
        if (isInsightApiError(error, 'TABLE_NOT_FOUND')) {
            return {
                intent: null,
                goalCandidates: [],
                questions: [],
            };
        }
        throw error;
    }
}

export const restoreGoalForDatasetVersion = createAsyncThunk<
    GoalSnapshotResult,
    { datasetId: string; versionId: string },
    { rejectValue: InsightError }
>('goal/restore', async ({ datasetId, versionId }, thunkApi) => {
    try {
        const project = await readInsightProject(thunkApi.signal);
        if (!project.active_goal_id) {
            return {
                resourceKey: makeGoalResourceKey(datasetId, versionId),
                datasetId,
                versionId,
                project,
                activeGoal: null,
                intent: null,
                goalCandidates: [],
                questions: [],
            };
        }

        let activeGoal: AnalysisGoal | null = null;
        try {
            const loadedGoal = await readAnalysisGoal(project.active_goal_id, thunkApi.signal);
            if (matchesDatasetVersion(loadedGoal, datasetId, versionId)) {
                activeGoal = loadedGoal;
            }
        } catch (error) {
            if (!isInsightApiError(error, 'TABLE_NOT_FOUND')) {
                throw error;
            }
        }

        if (!activeGoal) {
            return {
                resourceKey: makeGoalResourceKey(datasetId, versionId),
                datasetId,
                versionId,
                project,
                activeGoal: null,
                intent: null,
                goalCandidates: [],
                questions: [],
            };
        }

        const intentSnapshot = await loadIntentSnapshotForGoal(activeGoal, thunkApi.signal);
        return {
            resourceKey: makeGoalResourceKey(datasetId, versionId),
            datasetId,
            versionId,
            project,
            activeGoal,
            intent: intentSnapshot.intent,
            goalCandidates: intentSnapshot.goalCandidates,
            questions: intentSnapshot.questions,
        };
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

export const createGoalIntent = createAsyncThunk<
    GoalSnapshotResult,
    CreateIntentParams,
    { rejectValue: InsightError }
>('goal/createIntent', async ({ datasetId, datasetVersionId, userInput }, thunkApi) => {
    try {
        const snapshot = await createIntentSnapshot(
            {
                datasetId,
                datasetVersionId,
                userInput,
            },
            thunkApi.signal,
        );
        const resourceKey = makeGoalResourceKey(datasetId, datasetVersionId);
        return {
            resourceKey,
            datasetId,
            versionId: datasetVersionId,
            project: await readInsightProject(thunkApi.signal),
            activeGoal: null,
            intent: snapshot.intent,
            goalCandidates: snapshot.goalCandidates,
            questions: snapshot.questions,
        };
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

export const saveAnalysisGoal = createAsyncThunk<
    GoalMutationResult,
    SaveGoalParams,
    { rejectValue: InsightError }
>('goal/saveGoal', async (params, thunkApi) => {
    try {
        const result = await createAnalysisGoal(params, thunkApi.signal);
        const snapshot = result.goal.intent_id
            ? await loadIntentSnapshotForGoal(result.goal, thunkApi.signal)
            : { intent: null, goalCandidates: [], questions: [] };
        return {
            resourceKey: makeGoalResourceKey(params.datasetId, params.datasetVersionId),
            datasetId: params.datasetId,
            versionId: params.datasetVersionId,
            project: result.project,
            activeGoal: result.goal,
            intent: snapshot.intent,
            goalCandidates: snapshot.goalCandidates,
            questions: snapshot.questions,
            created: result.created,
        };
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

const goalSlice = createSlice({
    name: 'goal',
    initialState,
    reducers: {
        clearGoalResource: (state, action: PayloadAction<{ datasetId: string; versionId: string }>) => {
            delete state.resources[makeGoalResourceKey(action.payload.datasetId, action.payload.versionId)];
        },
        clearGoalState: () => createInitialGoalState(),
    },
    extraReducers: (builder) => {
        builder.addCase(restoreGoalForDatasetVersion.pending, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId, action.meta.arg.versionId);
            resource.status = 'loading';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
        });
        builder.addCase(restoreGoalForDatasetVersion.fulfilled, (state, action) => {
            const resource = state.resources[action.payload.resourceKey];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.project = action.payload.project;
            resource.activeGoal = action.payload.activeGoal;
            resource.intent = action.payload.intent;
            resource.goalCandidates = action.payload.goalCandidates;
            resource.questions = action.payload.questions;
            resource.status = 'ready';
            resource.error = null;
            resource.currentRequestId = null;
        });
        builder.addCase(restoreGoalForDatasetVersion.rejected, (state, action) => {
            const resource = state.resources[makeGoalResourceKey(action.meta.arg.datasetId, action.meta.arg.versionId)];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'error';
            resource.error = action.payload ?? null;
            resource.currentRequestId = null;
        });

        builder.addCase(createGoalIntent.pending, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId, action.meta.arg.datasetVersionId);
            resource.status = 'generating';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
        });
        builder.addCase(createGoalIntent.fulfilled, (state, action) => {
            const resource = state.resources[action.payload.resourceKey];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.project = action.payload.project;
            resource.activeGoal = preserveActiveGoal(
                resource.activeGoal,
                action.payload.project,
                action.payload.datasetId,
                action.payload.versionId,
            );
            resource.intent = action.payload.intent;
            resource.goalCandidates = action.payload.goalCandidates;
            resource.questions = action.payload.questions;
            resource.status = 'ready';
            resource.error = null;
            resource.currentRequestId = null;
        });
        builder.addCase(createGoalIntent.rejected, (state, action) => {
            const resource = state.resources[makeGoalResourceKey(action.meta.arg.datasetId, action.meta.arg.datasetVersionId)];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'error';
            resource.error = action.payload ?? null;
            resource.currentRequestId = null;
        });

        builder.addCase(saveAnalysisGoal.pending, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId, action.meta.arg.datasetVersionId);
            resource.status = 'confirming';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
        });
        builder.addCase(saveAnalysisGoal.fulfilled, (state, action) => {
            const resource = state.resources[action.payload.resourceKey];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.project = action.payload.project;
            resource.activeGoal = action.payload.activeGoal;
            resource.intent = action.payload.intent;
            resource.goalCandidates = action.payload.goalCandidates;
            resource.questions = action.payload.questions;
            resource.status = 'ready';
            resource.error = null;
            resource.currentRequestId = null;
        });
        builder.addCase(saveAnalysisGoal.rejected, (state, action) => {
            const resource = state.resources[makeGoalResourceKey(action.meta.arg.datasetId, action.meta.arg.datasetVersionId)];
            if (!resource || resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'error';
            resource.error = action.payload ?? null;
            resource.currentRequestId = null;
        });

        builder.addCase(dfActions.setActiveWorkspace, () => createInitialGoalState());
        builder.addCase(dfActions.resetForNewWorkspace, () => createInitialGoalState());
        builder.addCase(dfActions.loadState, () => createInitialGoalState());
    },
});

export const goalReducer = goalSlice.reducer;
export const goalActions = goalSlice.actions;
export const goalInitialState = initialState;

export const selectGoalResource = (
    state: GoalRootState,
    resourceKey: string | undefined,
): GoalResourceState | undefined => (resourceKey ? state.goal.resources[resourceKey] : undefined);