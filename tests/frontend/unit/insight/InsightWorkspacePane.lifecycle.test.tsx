import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const abortRequest = vi.fn();
const dispatch = vi.fn(() => ({ abort: abortRequest }));

let profilingStatus: 'registering' | 'ready' | undefined;

const activeTable = {
    id: 'table-1',
    displayId: 'Sales Raw',
    virtual: { tableId: 'sales_raw' },
    source: {},
};

vi.mock('react-redux', () => ({
    useDispatch: () => dispatch,
    useSelector: (selector: (state: any) => unknown) => selector({
        activeWorkspace: { id: 'workspace-1', displayName: 'Workspace 1' },
        tables: [activeTable],
        insight: {
            resources: profilingStatus
                ? {
                    'workspace-1::table-1': {
                        requestKey: 'workspace-1::table-1',
                        workspaceId: 'workspace-1',
                        tableId: 'table-1',
                        datasetId: profilingStatus === 'ready' ? 'dataset_sales' : null,
                        profileVersionId: profilingStatus === 'ready' ? 'version_000' : null,
                        profile: profilingStatus === 'ready'
                            ? { id: 'profile_sales', version_id: 'version_000', dataset_id: 'dataset_sales' }
                            : null,
                        status: profilingStatus,
                        error: null,
                        currentRequestId: 'request-1',
                        lastProfileSource: null,
                    },
                }
                : {},
        },
    }),
}));

vi.mock('../../../../src/app/dfSlice', () => ({
    dfSelectors: {
        getEffectiveTableId: () => 'table-1',
    },
}));

vi.mock('../../../../src/insight/store/profilingSlice', () => ({
    loadProfileForTable: (payload: unknown) => ({ type: 'insight/loadProfileForTable', payload }),
    makeProfilingRequestKey: (workspaceId: string, tableId: string) => `${workspaceId}::${tableId}`,
    selectProfilingResource: (state: any, requestKey?: string) => (
        requestKey ? state.insight.resources[requestKey] : undefined
    ),
}));

vi.mock('../../../../src/insight/components/ProfileColumnsTable', () => ({
    ProfileColumnsTable: () => <div>columns</div>,
}));

vi.mock('../../../../src/insight/components/ProfileIssueList', () => ({
    ProfileIssueList: () => <div>issues</div>,
}));

vi.mock('../../../../src/insight/components/ProfileOverviewCards', () => ({
    ProfileOverviewCards: () => <div>overview</div>,
}));

vi.mock('../../../../src/insight/components/VersionedCleaningWorkspacePanel', () => ({
    VersionedCleaningWorkspacePanel: ({ datasetId }: { datasetId: string }) => (
        <div>{`versioned cleaning workspace ${datasetId}`}</div>
    ),
}));

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => ({
            'insight.tabs.ariaLabel': 'Business insight workspace tabs',
            'insight.tabs.analysis': 'Analysis View',
            'insight.tabs.profiling': 'Data Profile',
            'insight.tabs.cleaning': 'Cleaning Suggestions',
            'insight.profile.emptyTitle': 'Profile will appear here',
            'insight.profile.emptyBody': 'Open this tab to load a profile.',
            'insight.profile.loading.registering': 'Registering',
        }[key] ?? key),
    }),
}));

import { InsightWorkspacePane } from '../../../../src/insight/views/InsightWorkspacePane';

describe('InsightWorkspacePane request lifecycle', () => {
    beforeEach(() => {
        profilingStatus = undefined;
        dispatch.mockClear();
        abortRequest.mockClear();
    });

    it('does not abort the active request when status changes to registering', () => {
        const { rerender } = render(<InsightWorkspacePane analysisView={<div>analysis</div>} />);

        fireEvent.click(screen.getByRole('tab', { name: 'Data Profile' }));
        expect(dispatch).toHaveBeenCalledOnce();
        expect(abortRequest).not.toHaveBeenCalled();

        profilingStatus = 'registering';
        rerender(<InsightWorkspacePane analysisView={<div>analysis</div>} />);

        expect(abortRequest).not.toHaveBeenCalled();
        expect(screen.getByText('Registering')).toBeInTheDocument();
    });

    it('renders the versioned cleaning workspace when the cleaning tab opens with a ready dataset resource', () => {
        profilingStatus = 'ready';
        render(<InsightWorkspacePane analysisView={<div>analysis</div>} />);

        fireEvent.click(screen.getByRole('tab', { name: 'Cleaning Suggestions' }));

        expect(screen.getByText('versioned cleaning workspace dataset_sales')).toBeInTheDocument();
    });
});
