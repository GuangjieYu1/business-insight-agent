import React from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { fireEvent, render, screen } from '@testing-library/react';
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

import { AgentRunWorkspace } from '../../../../src/insight/components/AgentRunWorkspace';
import { ProcessDrawer } from '../../../../src/insight/components/ProcessDrawer';
import {
    agentRunReducer,
    type AgentRunResourceState,
} from '../../../../src/insight/store/agentRunSlice';
import type { AgentRun, AgentStep, FinalSummary } from '../../../../src/insight/types';

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

function renderWorkspace(resource: AgentRunResourceState, onOpenCleaning = vi.fn()) {
    const store = configureStore({
        reducer: { agentRun: agentRunReducer },
        preloadedState: {
            agentRun: {
                resources: {
                    dataset_sales: resource,
                },
            },
        },
    });
    render(
        <Provider store={store}>
            <AgentRunWorkspace
                datasetId="dataset_sales"
                versionId="version_000"
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

    it('restores a completed run and collapses the main workspace into the final conclusion', () => {
        renderWorkspace(resourceFor(baseRun, [completedStep], summary));

        expect(screen.getByText('Data quality review complete')).toBeInTheDocument();
        expect(screen.getByText('No deterministic cleaning approval is required.')).toBeInTheDocument();
        expect(screen.getByText('insight.run.final.limitations')).toBeInTheDocument();
        expect(screen.getByText('This is not a causal result.')).toBeInTheDocument();
        expect(screen.getByText('insight.run.final.nextSteps')).toBeInTheDocument();
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

    it('restores a waiting-approval run and sends the user to cleaning review', async () => {
        const waitingRun: AgentRun = {
            ...baseRun,
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

        renderWorkspace(resourceFor(waitingRun, [approvalStep], null), onOpenCleaning);

        expect(screen.getByText('insight.run.waitingApproval')).toBeInTheDocument();
        expect(screen.getAllByText('Cleaning approval required').length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('button', { name: 'insight.run.openCleaning' }));
        expect(onOpenCleaning).toHaveBeenCalledTimes(1);
    });
});
