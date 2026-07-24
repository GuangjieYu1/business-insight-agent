import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const dispatch = vi.fn();
const state = {
    focusedId: { type: 'table', tableId: 'table_1' },
    activeWorkspace: { id: 'workspace_1' },
    tables: [
        {
            id: 'table_1',
            displayId: 'Sales',
            virtual: { tableId: 'sales', rowCount: 3 },
        },
    ],
    insight: { resources: {} },
};

vi.mock('react-redux', () => ({
    useDispatch: () => dispatch,
    useSelector: (selector: (value: typeof state) => unknown) => selector(state),
}));

vi.mock('react-i18next', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react-i18next')>();
    return {
        ...actual,
        useTranslation: () => ({
            t: (key: string) => ({
                'insight.tabs.ariaLabel': 'Business insight tabs',
                'insight.tabs.analysis': 'Analysis View',
                'insight.tabs.profiling': 'Data Profile',
                'insight.tabs.cleaning': 'Cleaning Suggestions',
                'insight.tabs.process': 'Task Process',
            }[key] || key),
        }),
    };
});

vi.mock('../../../../src/insight/components/TaskLedgerPanel', () => ({
    TaskLedgerPanel: ({ workspaceId, tableName }: {
        workspaceId: string;
        tableName: string;
    }) => <div>{`ledger:${workspaceId}:${tableName}`}</div>,
}));

vi.mock('../../../../src/insight/components/VersionedCleaningWorkspacePanel', () => ({
    VersionedCleaningWorkspacePanel: () => <div>cleaning</div>,
}));

import { InsightWorkspacePane } from '../../../../src/insight/views/InsightWorkspacePane';

describe('InsightWorkspacePane tabs', () => {
    it('keeps analysis first and exposes a read-only task-process tab', () => {
        render(<InsightWorkspacePane analysisView={<div>analysis content</div>} />);

        const tabs = screen.getAllByRole('tab');
        expect(tabs.map((tab) => tab.textContent)).toEqual([
            'Analysis View',
            'Data Profile',
            'Cleaning Suggestions',
            'Task Process',
        ]);
        expect(screen.queryByText('Agent Run')).not.toBeInTheDocument();
        expect(screen.getByText('analysis content')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('tab', { name: 'Task Process' }));
        expect(screen.getByText('ledger:workspace_1:sales')).toBeInTheDocument();
        expect(dispatch).not.toHaveBeenCalled();
    });
});
