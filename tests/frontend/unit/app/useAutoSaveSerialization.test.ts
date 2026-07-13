import { describe, expect, it } from 'vitest';

import { getSerializableState } from '../../../../src/app/useAutoSave';

describe('getSerializableState', () => {
    it('excludes the insight, agentRun, and goal slices from workspace session saves', () => {
        const serializable = getSerializableState({
            activeWorkspace: { id: 'ws-1', displayName: 'Workspace 1' },
            tables: [{ id: 'table-1' }],
            insight: {
                resources: {
                    'ws-1::table-1': {
                        status: 'ready',
                    },
                },
            },
            agentRun: {
                resources: {
                    dataset_sales: {
                        status: 'ready',
                    },
                },
            },
            goal: {
                resources: {
                    'dataset_sales::version_000': {
                        status: 'ready',
                    },
                },
            },
            chartThumbnails: { chart1: 'data:image/png;base64,abc' },
        } as any);

        expect(serializable.activeWorkspace).toEqual({ id: 'ws-1', displayName: 'Workspace 1' });
        expect(serializable.tables).toEqual([{ id: 'table-1' }]);
        expect(serializable).not.toHaveProperty('insight');
        expect(serializable).not.toHaveProperty('agentRun');
        expect(serializable).not.toHaveProperty('goal');
        expect(serializable).not.toHaveProperty('chartThumbnails');
    });
});