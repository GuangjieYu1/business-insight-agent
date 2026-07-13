import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/insight/api/agentRunClient', () => ({
    listDataAgentLedgerRuns: vi.fn(),
    readAgentRun: vi.fn(),
    subscribeToAgentRunEvents: vi.fn(() => ({ close: vi.fn() })),
}));

vi.mock('react-i18next', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react-i18next')>();
    return {
        ...actual,
        useTranslation: () => ({
            t: (key: string, params?: Record<string, unknown>) => {
                if (key === 'insight.ledger.title') return 'Task ledger';
                if (key === 'insight.ledger.duration') return `Duration ${params?.seconds}s`;
                if (key === 'insight.ledger.steps') return `${params?.count} steps`;
                if (key === 'insight.ledger.table') return `Table ${params?.tableName}`;
                if (key === 'insight.run.status.completed') return 'Completed';
                if (key === 'insight.run.stepStatus.completed') return 'Completed';
                return key;
            },
        }),
    };
});

import {
    listDataAgentLedgerRuns,
    readAgentRun,
    subscribeToAgentRunEvents,
} from '../../../../src/insight/api/agentRunClient';
import { TaskLedgerPanel } from '../../../../src/insight/components/TaskLedgerPanel';

function snapshot(tableName = 'sales') {
    return {
        run: {
            id: `run_${tableName}`,
            schema_version: '1.0',
            workspace_id: 'workspace_1',
            created_at: '2026-07-14T00:00:00Z',
            updated_at: '2026-07-14T00:00:05Z',
            goal_id: null,
            dataset_version_id: null,
            execution_kind: 'data_agent_ledger',
            source_table_refs: [tableName],
            interrupted_at: null,
            resume_cursor_hash: null,
            status: 'completed',
            current_stage: 'completed',
            started_at: '2026-07-14T00:00:00Z',
            completed_at: '2026-07-14T00:00:05Z',
            final_summary_ref: null,
        },
        steps: [
            {
                id: `step_${tableName}`,
                schema_version: '1.0',
                workspace_id: 'workspace_1',
                created_at: '2026-07-14T00:00:00Z',
                updated_at: '2026-07-14T00:00:00Z',
                run_id: `run_${tableName}`,
                type: 'progress',
                title: `Question for ${tableName}`,
                status: 'completed',
                started_at: '2026-07-14T00:00:00Z',
                completed_at: '2026-07-14T00:00:00Z',
                input_refs: [tableName],
                output_refs: [],
                progress_text: 'Existing Data Agent started.',
                detail: { event_type: 'run_started' },
                collapsed_by_default: true,
            },
        ],
        finalSummary: null,
    } as any;
}

describe('TaskLedgerPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(listDataAgentLedgerRuns).mockImplementation(async (tableName) => [
            snapshot(tableName).run,
        ]);
        vi.mocked(readAgentRun).mockImplementation(async (runId) => (
            snapshot(runId.replace('run_', ''))
        ));
    });

    it('shows a read-only task ledger without goal or start-analysis controls', async () => {
        render(<TaskLedgerPanel workspaceId='workspace_1' tableName='sales' />);

        expect(await screen.findByText('Task ledger')).toBeInTheDocument();
        expect(screen.getAllByText('Question for sales')).toHaveLength(2);
        expect(screen.getByText('Duration 5s')).toBeInTheDocument();
        expect(screen.getByText('1 steps')).toBeInTheDocument();
        expect(screen.queryByText(/Start analysis/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Goal/i)).not.toBeInTheDocument();
        expect(subscribeToAgentRunEvents).not.toHaveBeenCalled();
    });

    it('reloads from the server when the workspace or table changes', async () => {
        const view = render(
            <TaskLedgerPanel workspaceId='workspace_1' tableName='sales' />,
        );
        expect(await screen.findAllByText('Question for sales')).toHaveLength(2);

        view.rerender(
            <TaskLedgerPanel workspaceId='workspace_2' tableName='inventory' />,
        );

        await waitFor(() => {
            expect(screen.getAllByText('Question for inventory')).toHaveLength(2);
        });
        expect(listDataAgentLedgerRuns).toHaveBeenCalledWith(
            'inventory',
            expect.any(AbortSignal),
        );
        expect(screen.queryAllByText('Question for sales')).toHaveLength(0);
    });
});
