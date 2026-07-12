import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../../../../src/insight/api/insightClient', () => ({
    registerDataset: vi.fn(),
    readVersionZeroProfile: vi.fn(),
    generateVersionZeroProfile: vi.fn(),
    isInsightApiError: vi.fn((error: any, code?: string) => {
        return error?.apiError?.code === code;
    }),
    toInsightError: vi.fn((error: any) => ({
        code: error?.apiError?.code || 'UNKNOWN_ERROR',
        message: error?.apiError?.message || error?.message || 'failed',
        retryable: false,
    })),
}));

import { dfActions } from '../../../../src/app/dfSlice';
import {
    generateVersionZeroProfile,
    readVersionZeroProfile,
    registerDataset,
} from '../../../../src/insight/api/insightClient';
import {
    insightReducer,
    loadProfileForTable,
    makeProfilingRequestKey,
} from '../../../../src/insight/store/profilingSlice';
import type { DatasetProfile } from '../../../../src/insight/types';

function createProfile(overrides: Partial<DatasetProfile> = {}): DatasetProfile {
    return {
        id: 'profile_sales',
        schema_version: '1.0',
        workspace_id: 'ws-1',
        created_at: '2026-07-12T00:00:00Z',
        updated_at: '2026-07-12T00:00:00Z',
        dataset_id: 'dataset_sales',
        version_id: 'version_000',
        source_content_hash: 'hash-1',
        profiler_version: 'dataset-profiler-v1',
        configuration_hash: 'cfg-1',
        file_ref: 'datasets/dataset_sales/versions/version_000.parquet',
        profile_ref: 'datasets/dataset_sales/profiles/version_000.json',
        row_count: 10,
        column_count: 4,
        duplicate_row_count: 1,
        duplicate_row_ratio: 0.1,
        duplicate_group_member_count: 2,
        duplicate_group_member_ratio: 0.2,
        duplicate_excess_row_count: 1,
        duplicate_excess_row_ratio: 0.1,
        sample_policy: 'disabled',
        redaction_applied: false,
        sensitive_data_detected: false,
        columns: [],
        quality_issues: [],
        ...overrides,
    };
}

function createStore() {
    return configureStore({
        reducer: {
            insight: insightReducer,
        },
    });
}

describe('profilingSlice', () => {
    beforeEach(() => {
        vi.mocked(registerDataset).mockReset();
        vi.mocked(readVersionZeroProfile).mockReset();
        vi.mocked(generateVersionZeroProfile).mockReset();
    });

    it('stores an existing version_000 profile without generating a new one', async () => {
        vi.mocked(registerDataset).mockResolvedValue({
            project: {} as any,
            dataset: { id: 'dataset_sales' } as any,
            version: {} as any,
            created: false,
        });
        vi.mocked(readVersionZeroProfile).mockResolvedValue(createProfile());

        const store = createStore();
        await store.dispatch(loadProfileForTable({
            workspaceId: 'ws-1',
            tableId: 'table-1',
            tableName: 'sales_raw',
            datasetName: 'Sales Raw',
        }) as any);

        const resource = store.getState().insight.resources[makeProfilingRequestKey('ws-1', 'table-1')];
        expect(resource.status).toBe('ready');
        expect(resource.datasetId).toBe('dataset_sales');
        expect(resource.lastProfileSource).toBe('existing');
        expect(generateVersionZeroProfile).not.toHaveBeenCalled();
    });

    it('falls back to profiling POST when the saved profile is missing', async () => {
        vi.mocked(registerDataset).mockResolvedValue({
            project: {} as any,
            dataset: { id: 'dataset_sales' } as any,
            version: {} as any,
            created: true,
        });
        vi.mocked(readVersionZeroProfile).mockRejectedValue({
            apiError: {
                code: 'TABLE_NOT_FOUND',
                message: 'missing',
            },
        });
        vi.mocked(generateVersionZeroProfile).mockResolvedValue(createProfile({ id: 'profile_generated' }));

        const store = createStore();
        await store.dispatch(loadProfileForTable({
            workspaceId: 'ws-1',
            tableId: 'table-1',
            tableName: 'sales_raw',
            datasetName: 'Sales Raw',
        }) as any);

        const resource = store.getState().insight.resources[makeProfilingRequestKey('ws-1', 'table-1')];
        expect(resource.status).toBe('ready');
        expect(resource.profile?.id).toBe('profile_generated');
        expect(resource.lastProfileSource).toBe('generated');
        expect(generateVersionZeroProfile).toHaveBeenCalledWith('dataset_sales', expect.any(AbortSignal));
    });

    it('ignores stale fulfilled payloads after a newer request starts', () => {
        const requestKey = makeProfilingRequestKey('ws-1', 'table-1');
        const firstPending = loadProfileForTable.pending('request-1', {
            workspaceId: 'ws-1',
            tableId: 'table-1',
            tableName: 'sales_raw',
            datasetName: 'Sales Raw',
        });
        const secondPending = loadProfileForTable.pending('request-2', {
            workspaceId: 'ws-1',
            tableId: 'table-1',
            tableName: 'sales_raw',
            datasetName: 'Sales Raw',
        });
        const staleFulfilled = loadProfileForTable.fulfilled(
            {
                requestKey,
                datasetId: 'dataset_sales',
                profile: createProfile({ id: 'profile_stale' }),
                source: 'existing',
            },
            'request-1',
            {
                workspaceId: 'ws-1',
                tableId: 'table-1',
                tableName: 'sales_raw',
                datasetName: 'Sales Raw',
            },
        );

        let state = insightReducer(undefined, firstPending);
        state = insightReducer(state, secondPending);
        state = insightReducer(state, staleFulfilled);

        expect(state.resources[requestKey].status).toBe('registering');
        expect(state.resources[requestKey].profile).toBeNull();
        expect(state.resources[requestKey].currentRequestId).toBe('request-2');
    });

    it('clears profiling resources when a workspace state is loaded', () => {
        const requestKey = makeProfilingRequestKey('ws-1', 'table-1');
        const seededState = {
            resources: {
                [requestKey]: {
                    requestKey,
                    workspaceId: 'ws-1',
                    tableId: 'table-1',
                    datasetId: 'dataset_sales',
                    profileVersionId: 'version_000',
                    profile: createProfile(),
                    status: 'ready',
                    error: null,
                    currentRequestId: null,
                    lastProfileSource: 'existing',
                },
            },
        };

        const nextState = insightReducer(seededState, dfActions.loadState({ tables: [] }));
        expect(nextState.resources).toEqual({});
    });
});
