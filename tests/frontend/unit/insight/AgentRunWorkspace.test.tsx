import React from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, params?: Record<string, unknown>) => {
            if (key === 'insight.run.processDrawer.subtitle') return `Run ${params?.runId}`;
            if (key === 'insight.run.final.runReference') return `Run reference: ${params?.runId}`;
            return key;
        },
    }),
}));

vi.mock('../../../../src/insight/api/agentRunClient', () => ({
    cancelAgentRun: vi.fn(),
    createAgentRun: vi.fn(),
    listAgentRuns: vi.fn(),
    readAgentRun: vi.fn(),
    subscribeToAgentRunEvents: vi.fn(() => ({ close: vi.fn() })),
}));

import {
    listAgentRuns,
    readAgentRun,
} from '../../../../src/insight/api/agentRunClient';
import { AgentRunWorkspace } from '../../../../src/insight/components/AgentRunWorkspace';
import { agentRunReducer } from '../../../../src/insight/store/agentRunSlice';
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

function mockCompletedRun() {
    vi.mocked(listAgentRuns).mockResolvedValue([baseRun]);
    vi.mocked(readAgentRun).mockResolvedValue({
        run: baseRun,
        steps: [completedStep],
        finalSummary: summary,
    });
}

function renderWorkspace(onOpenCleaning = vi.fn()) {
    const store = configureStore({ reducer: { agentRun: agentRunReducer } });
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

    it('restores a completed run and presents the final conclusion', async () => {
        mockCompletedRun();
        renderWorkspace();

        expect(await screen.findByText('Data quality review complete')).toBeInTheDocument();
        expect(screen.getByText('No deterministic cleaning approval is required.')).toBeInTheDocument();
        expect(screen.getByText('insight.run.final.limitations')).toBeInTheDocument();
        expect(screen.getByText('This is not a causal result.')).toBeInTheDocument();
        expect(screen.getByText('insight.run.final.nextSteps')).toBeInTheDocument();
        expect(screen.getByText('Confirm a business goal.')).toBeInTheDocument();
    });

    it('opens the persisted process drawer from a completed conclusion', async () => {
        mockCompletedRun();
        renderWorkspace();

        expect(await screen.findByText('Data quality review complete')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'insight.run.viewFullProcess' }));

        expect(await screen.findByText('insight.run.processDrawer.title')).toBeInTheDocument();
        expect((await screen.findAllByText('Analysis run completed')).length).toBeGreaterThan(0);
        expect(screen.getByText('Run run_1')).toBeInTheDocument();
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
        vi.mocked(listAgentRuns).mockResolvedValue([waitingRun]);
        vi.mocked(readAgentRun).mockResolvedValue({
            run: waitingRun,
            steps: [approvalStep],
            finalSummary: null,
        });
        const onOpenCleaning = vi.fn();

        renderWorkspace(onOpenCleaning);

        expect(await screen.findByText('insight.run.waitingApproval')).toBeInTheDocument();
        expect((await screen.findAllByText('Cleaning approval required')).length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('button', { name: 'insight.run.openCleaning' }));
        expect(onOpenCleaning).toHaveBeenCalledTimes(1);
    });
});
