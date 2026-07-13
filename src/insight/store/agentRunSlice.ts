import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { dfActions, type DataFormulatorState } from '../../app/dfSlice';
import {
    cancelAgentRun,
    createAgentRun,
    listAgentRuns,
    readAgentRun,
} from '../api/agentRunClient';
import { toInsightError } from '../api/insightClient';
import type {
    AgentRun,
    AgentRunEventPayload,
    AgentRunSnapshot,
    AgentStep,
    FinalSummary,
    InsightError,
} from '../types';

export type AgentRunResourceStatus = 'idle' | 'loading' | 'starting' | 'ready' | 'error';
export type AgentRunConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'closed' | 'error';

export interface AgentRunResourceState {
    datasetId: string;
    run: AgentRun | null;
    steps: AgentStep[];
    finalSummary: FinalSummary | null;
    status: AgentRunResourceStatus;
    connectionStatus: AgentRunConnectionStatus;
    lastEventId: string | null;
    processOpen: boolean;
    error: InsightError | null;
    currentRequestId: string | null;
}

export interface AgentRunState {
    resources: Record<string, AgentRunResourceState>;
}

export interface AgentRunRootState extends DataFormulatorState {
    agentRun: AgentRunState;
}

const createInitialAgentRunState = (): AgentRunState => ({ resources: {} });
const initialState: AgentRunState = createInitialAgentRunState();

function createResource(datasetId: string): AgentRunResourceState {
    return {
        datasetId,
        run: null,
        steps: [],
        finalSummary: null,
        status: 'idle',
        connectionStatus: 'disconnected',
        lastEventId: null,
        processOpen: false,
        error: null,
        currentRequestId: null,
    };
}

function ensureResource(state: AgentRunState, datasetId: string): AgentRunResourceState {
    if (!state.resources[datasetId]) {
        state.resources[datasetId] = createResource(datasetId);
    }
    return state.resources[datasetId];
}

export const restoreLatestAgentRun = createAsyncThunk<
    AgentRunSnapshot | null,
    { datasetId: string },
    { rejectValue: InsightError }
>('agentRun/restoreLatest', async ({ datasetId }, thunkApi) => {
    try {
        const runs = await listAgentRuns(datasetId, thunkApi.signal);
        if (!runs.length) return null;
        return await readAgentRun(runs[0].id, thunkApi.signal);
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

export const startObservableAgentRun = createAsyncThunk<
    AgentRunSnapshot,
    { datasetId: string; versionId?: string; goalId: string },
    { rejectValue: InsightError }
>('agentRun/start', async ({ datasetId, versionId, goalId }, thunkApi) => {
    try {
        const created = await createAgentRun(
            { datasetId, versionId, goalId, executionMode: 'background' },
            thunkApi.signal,
        );
        return {
            run: created.run,
            steps: created.steps,
            finalSummary: created.finalSummary,
        };
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

export const refreshAgentRun = createAsyncThunk<
    AgentRunSnapshot,
    { datasetId: string; runId: string },
    { rejectValue: InsightError }
>('agentRun/refresh', async ({ runId }, thunkApi) => {
    try {
        return await readAgentRun(runId, thunkApi.signal);
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

export const cancelObservableAgentRun = createAsyncThunk<
    AgentRunSnapshot,
    { datasetId: string; runId: string; reason?: string },
    { rejectValue: InsightError }
>('agentRun/cancel', async ({ runId, reason }, thunkApi) => {
    try {
        return await cancelAgentRun(runId, reason, thunkApi.signal);
    } catch (error) {
        return thunkApi.rejectWithValue(toInsightError(error));
    }
});

interface StreamPayload {
    datasetId: string;
}

interface EventPayload extends StreamPayload {
    lastEventId: string;
    event: AgentRunEventPayload;
}

const agentRunSlice = createSlice({
    name: 'agentRun',
    initialState,
    reducers: {
        streamConnecting: (state, action: PayloadAction<StreamPayload>) => {
            ensureResource(state, action.payload.datasetId).connectionStatus = 'connecting';
        },
        streamOpened: (state, action: PayloadAction<StreamPayload>) => {
            ensureResource(state, action.payload.datasetId).connectionStatus = 'connected';
        },
        streamClosed: (state, action: PayloadAction<StreamPayload>) => {
            ensureResource(state, action.payload.datasetId).connectionStatus = 'closed';
        },
        streamFailed: (state, action: PayloadAction<StreamPayload>) => {
            ensureResource(state, action.payload.datasetId).connectionStatus = 'error';
        },
        eventReceived: (state, action: PayloadAction<EventPayload>) => {
            const resource = ensureResource(state, action.payload.datasetId);
            if (action.payload.lastEventId) {
                resource.lastEventId = action.payload.lastEventId;
            }
            const runStatus = action.payload.event.runStatus;
            if (resource.run && runStatus) {
                resource.run.status = runStatus;
                resource.run.current_stage = action.payload.event.stage || resource.run.current_stage;
            }
        },
        setProcessOpen: (
            state,
            action: PayloadAction<{ datasetId: string; open: boolean }>,
        ) => {
            ensureResource(state, action.payload.datasetId).processOpen = action.payload.open;
        },
        clearAgentRunResource: (state, action: PayloadAction<{ datasetId: string }>) => {
            delete state.resources[action.payload.datasetId];
        },
        clearAgentRunState: () => createInitialAgentRunState(),
    },
    extraReducers: (builder) => {
        builder.addCase(restoreLatestAgentRun.pending, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.status = 'loading';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
        });
        builder.addCase(restoreLatestAgentRun.fulfilled, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            if (resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'ready';
            resource.error = null;
            resource.currentRequestId = null;
            resource.run = action.payload?.run ?? null;
            resource.steps = action.payload?.steps ?? [];
            resource.finalSummary = action.payload?.finalSummary ?? null;
            resource.lastEventId = null;
            resource.connectionStatus = 'disconnected';
            resource.processOpen = false;
        });
        builder.addCase(restoreLatestAgentRun.rejected, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            if (resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'error';
            resource.error = action.payload ?? null;
            resource.currentRequestId = null;
        });

        builder.addCase(startObservableAgentRun.pending, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.status = 'starting';
            resource.error = null;
            resource.currentRequestId = action.meta.requestId;
            resource.lastEventId = null;
            resource.processOpen = false;
        });
        builder.addCase(startObservableAgentRun.fulfilled, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            if (resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'ready';
            resource.run = action.payload.run;
            resource.steps = action.payload.steps;
            resource.finalSummary = action.payload.finalSummary;
            resource.error = null;
            resource.currentRequestId = null;
            resource.connectionStatus = 'connecting';
        });
        builder.addCase(startObservableAgentRun.rejected, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            if (resource.currentRequestId !== action.meta.requestId) return;
            resource.status = 'error';
            resource.error = action.payload ?? null;
            resource.currentRequestId = null;
        });

        builder.addCase(refreshAgentRun.fulfilled, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.status = 'ready';
            resource.run = action.payload.run;
            resource.steps = action.payload.steps;
            resource.finalSummary = action.payload.finalSummary;
            resource.error = null;
        });
        builder.addCase(refreshAgentRun.rejected, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.error = action.payload ?? null;
        });

        builder.addCase(cancelObservableAgentRun.fulfilled, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.run = action.payload.run;
            resource.steps = action.payload.steps;
            resource.finalSummary = action.payload.finalSummary;
            resource.status = 'ready';
            resource.connectionStatus = 'closed';
        });
        builder.addCase(cancelObservableAgentRun.rejected, (state, action) => {
            const resource = ensureResource(state, action.meta.arg.datasetId);
            resource.error = action.payload ?? null;
        });

        builder.addCase(dfActions.setActiveWorkspace, () => createInitialAgentRunState());
        builder.addCase(dfActions.resetForNewWorkspace, () => createInitialAgentRunState());
        builder.addCase(dfActions.loadState, () => createInitialAgentRunState());
    },
});

export const agentRunReducer = agentRunSlice.reducer;
export const agentRunActions = agentRunSlice.actions;
export const agentRunInitialState = initialState;

export const selectAgentRunResource = (
    state: AgentRunRootState,
    datasetId: string | undefined,
): AgentRunResourceState | undefined => (datasetId ? state.agentRun.resources[datasetId] : undefined);