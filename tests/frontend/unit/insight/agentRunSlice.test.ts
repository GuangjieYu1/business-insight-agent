import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/insight/api/agentRunClient', () => ({
    cancelAgentRun: vi.fn(),
    createAgentRun: vi.fn(),
    listAgentRuns: vi.fn(),
    readAgentRun: vi.fn(),
}));

import { dfActions } from '../../../../src/app/dfSlice';
import {
    agentRunActions,
    agentRunReducer,
    restoreLatestAgentRun,
    startObservableAgentRun,
} from '../../../../src/insight/store/agentRunSlice';
import {
    createAgentRun,
    listAgentRuns,
    readAgentRun,
} from '../../../../src/insight/api/agentRunClient';
import type { AgentRun, AgentStep, FinalSummary } from '../../../../src/insight/types';

const run: AgentRun = {
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

const step: AgentStep = {
    id: 'step_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:00Z',
    run_id: 'run_1',
    type: 'progress',
    title: 'Analysis run completed',
    status: 'completed',
    started_at: '2026-07-13T00:00:00Z',
    completed_at: '2026-07-13T00:00:01Z',
    input_refs: [],
    output_refs: ['summary_1'],
    progress_text: 'Completed.',
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
    title: 'Review complete',
    executive_summary: 'No cleaning approval is required.',
    claim_refs: [],
    operation_refs: [],
    metric_changes: [],
    artifact_refs: [],
    limitations: [],
    next_steps: [],
};

function createStore() {
    return configureStore({ reducer: { agentRun: agentRunReducer } });
}

describe('agentRunSlice', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('restores the latest persisted run after a page refresh', async () => {
        vi.mocked(listAgentRuns).mockResolvedValue([run]);
        vi.mocked(readAgentRun).mockResolvedValue({
            run,
            steps: [step],
            finalSummary: summary,
        });
        const store = createStore();

        await store.dispatch(restoreLatestAgentRun({ datasetId: 'dataset_sales' }));
        const resource = store.getState().agentRun.resources.dataset_sales;

        expect(listAgentRuns).toHaveBeenCalledWith('dataset_sales', expect.any(AbortSignal));
        expect(readAgentRun).toHaveBeenCalledWith('run_1', expect.any(AbortSignal));
        expect(resource.run).toEqual(run);
        expect(resource.steps).toEqual([step]);
        expect(resource.finalSummary).toEqual(summary);
        expect(resource.processOpen).toBe(false);
    });

    it('starts a background run and tracks the stable event cursor', async () => {
        vi.mocked(createAgentRun).mockResolvedValue({
            run: { ...run, status: 'created', current_stage: 'created', completed_at: null, final_summary_ref: null },
            steps: [{ ...step, title: 'Analysis run started' }],
            finalSummary: null,
            profile: null,
            proposals: [],
            executionMode: 'background',
        });
        const store = createStore();

        await store.dispatch(startObservableAgentRun({
            datasetId: 'dataset_sales',
            versionId: 'version_000',
        }));
        store.dispatch(agentRunActions.eventReceived({
            datasetId: 'dataset_sales',
            lastEventId: 'step_2:stage',
            event: {
                eventType: 'stage_changed',
                runId: 'run_1',
                stepId: 'step_2',
                stage: 'profiling',
                status: 'completed',
                runStatus: 'profiling',
                timestamp: '2026-07-13T00:00:02Z',
            },
        }));

        const resource = store.getState().agentRun.resources.dataset_sales;
        expect(createAgentRun).toHaveBeenCalledWith(
            {
                datasetId: 'dataset_sales',
                versionId: 'version_000',
                executionMode: 'background',
            },
            expect.any(AbortSignal),
        );
        expect(resource.run?.status).toBe('profiling');
        expect(resource.run?.current_stage).toBe('profiling');
        expect(resource.lastEventId).toBe('step_2:stage');
        expect(resource.connectionStatus).toBe('connecting');
        expect(resource.processOpen).toBe(false);
    });

    it('clears all run state when the active workspace changes', async () => {
        vi.mocked(listAgentRuns).mockResolvedValue([run]);
        vi.mocked(readAgentRun).mockResolvedValue({ run, steps: [step], finalSummary: summary });
        const store = createStore();
        await store.dispatch(restoreLatestAgentRun({ datasetId: 'dataset_sales' }));

        store.dispatch(dfActions.setActiveWorkspace({
            id: 'workspace_2',
            displayName: 'Workspace 2',
        }));

        expect(store.getState().agentRun.resources).toEqual({});
    });
});
