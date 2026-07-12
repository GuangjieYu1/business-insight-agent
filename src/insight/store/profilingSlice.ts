import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';

import type { DataFormulatorState } from '../../app/dfSlice';
import { dfActions } from '../../app/dfSlice';
import {
    generateVersionZeroProfile,
    isInsightApiError,
    readVersionZeroProfile,
    registerDataset,
    toInsightError,
} from '../api/insightClient';
import type { DatasetProfile, InsightError } from '../types';

export type ProfilingStatus = 'idle' | 'registering' | 'loading' | 'profiling' | 'ready' | 'error';

export interface ProfilingResourceState {
    requestKey: string;
    workspaceId: string;
    tableId: string;
    datasetId: string | null;
    profileVersionId: string | null;
    profile: DatasetProfile | null;
    status: ProfilingStatus;
    error: InsightError | null;
    currentRequestId: string | null;
    lastProfileSource: 'existing' | 'generated' | null;
}

export interface InsightState {
    resources: Record<string, ProfilingResourceState>;
}

export interface InsightRootState extends DataFormulatorState {
    insight: InsightState;
}

export interface LoadProfileForTableArgs {
    workspaceId: string;
    tableId: string;
    tableName: string;
    datasetName: string;
}

interface LoadProfileForTableResult {
    requestKey: string;
    datasetId: string;
    profile: DatasetProfile;
    source: 'existing' | 'generated';
}

interface ResourceRequestPayload {
    requestKey: string;
    requestId: string;
}

interface RegistrationResolvedPayload extends ResourceRequestPayload {
    datasetId: string;
}

const createInitialInsightState = (): InsightState => ({
    resources: {},
});

const initialState: InsightState = createInitialInsightState();

export const makeProfilingRequestKey = (workspaceId: string, tableId: string): string =>
    `${workspaceId}::${tableId}`;

const createResourceState = (
    requestKey: string,
    workspaceId: string,
    tableId: string,
): ProfilingResourceState => ({
    requestKey,
    workspaceId,
    tableId,
    datasetId: null,
    profileVersionId: null,
    profile: null,
    status: 'idle',
    error: null,
    currentRequestId: null,
    lastProfileSource: null,
});

const ensureResourceState = (
    state: InsightState,
    requestKey: string,
    workspaceId: string,
    tableId: string,
): ProfilingResourceState => {
    const existing = state.resources[requestKey];
    if (existing) {
        return existing;
    }
    const created = createResourceState(requestKey, workspaceId, tableId);
    state.resources[requestKey] = created;
    return created;
};

export const loadProfileForTable = createAsyncThunk<
    LoadProfileForTableResult,
    LoadProfileForTableArgs,
    { rejectValue: InsightError; state: InsightRootState }
>(
    'insight/loadProfileForTable',
    async (args, thunkApi) => {
        const requestKey = makeProfilingRequestKey(args.workspaceId, args.tableId);

        try {
            const registration = await registerDataset(
                {
                    tableName: args.tableName,
                    datasetName: args.datasetName,
                },
                thunkApi.signal,
            );

            thunkApi.dispatch(
                insightActions.registrationResolved({
                    requestKey,
                    requestId: thunkApi.requestId,
                    datasetId: registration.dataset.id,
                }),
            );

            try {
                const profile = await readVersionZeroProfile(registration.dataset.id, thunkApi.signal);
                return {
                    requestKey,
                    datasetId: registration.dataset.id,
                    profile,
                    source: 'existing',
                };
            } catch (error) {
                if (!isInsightApiError(error, 'TABLE_NOT_FOUND')) {
                    throw error;
                }
            }

            thunkApi.dispatch(
                insightActions.profilingStarted({
                    requestKey,
                    requestId: thunkApi.requestId,
                }),
            );

            const generatedProfile = await generateVersionZeroProfile(registration.dataset.id, thunkApi.signal);
            return {
                requestKey,
                datasetId: registration.dataset.id,
                profile: generatedProfile,
                source: 'generated',
            };
        } catch (error) {
            return thunkApi.rejectWithValue(toInsightError(error));
        }
    },
);

const insightSlice = createSlice({
    name: 'insight',
    initialState,
    reducers: {
        registrationResolved: (state, action: PayloadAction<RegistrationResolvedPayload>) => {
            const resource = state.resources[action.payload.requestKey];
            if (!resource || resource.currentRequestId !== action.payload.requestId) {
                return;
            }
            resource.datasetId = action.payload.datasetId;
            resource.status = 'loading';
        },
        profilingStarted: (state, action: PayloadAction<ResourceRequestPayload>) => {
            const resource = state.resources[action.payload.requestKey];
            if (!resource || resource.currentRequestId !== action.payload.requestId) {
                return;
            }
            resource.status = 'profiling';
        },
        clearInsightState: () => createInitialInsightState(),
    },
    extraReducers: (builder) => {
        builder.addCase(loadProfileForTable.pending, (state, action) => {
            const { workspaceId, tableId } = action.meta.arg;
            const requestKey = makeProfilingRequestKey(workspaceId, tableId);
            const resource = ensureResourceState(state, requestKey, workspaceId, tableId);
            resource.status = 'registering';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
        });

        builder.addCase(loadProfileForTable.fulfilled, (state, action) => {
            const { requestKey, datasetId, profile, source } = action.payload;
            const resource = state.resources[requestKey];
            if (!resource || resource.currentRequestId !== action.meta.requestId) {
                return;
            }
            resource.datasetId = datasetId;
            resource.profileVersionId = profile.version_id;
            resource.profile = profile;
            resource.status = 'ready';
            resource.error = null;
            resource.currentRequestId = null;
            resource.lastProfileSource = source;
        });

        builder.addCase(loadProfileForTable.rejected, (state, action) => {
            const { workspaceId, tableId } = action.meta.arg;
            const requestKey = makeProfilingRequestKey(workspaceId, tableId);
            const resource = ensureResourceState(state, requestKey, workspaceId, tableId);
            if (resource.currentRequestId !== action.meta.requestId) {
                return;
            }

            if (action.meta.aborted) {
                resource.status = resource.profile ? 'ready' : 'idle';
                resource.error = null;
                resource.currentRequestId = null;
                return;
            }

            resource.status = 'error';
            resource.error = action.payload ?? {
                code: action.error.name || 'UNKNOWN_ERROR',
                message: action.error.message || 'Insight request failed',
                retryable: false,
            };
            resource.currentRequestId = null;
        });

        builder.addCase(dfActions.setActiveWorkspace, () => createInitialInsightState());
        builder.addCase(dfActions.resetForNewWorkspace, () => createInitialInsightState());
        builder.addCase(dfActions.loadState, () => createInitialInsightState());
    },
});

export const insightReducer = insightSlice.reducer;
export const insightActions = insightSlice.actions;
export const insightInitialState = initialState;

export const selectProfilingResource = (
    state: InsightRootState,
    requestKey: string | undefined,
): ProfilingResourceState | undefined => (requestKey ? state.insight.resources[requestKey] : undefined);
