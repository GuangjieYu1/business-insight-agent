import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/app/apiClient', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../../src/app/apiClient')>();
    return {
        ...actual,
        apiRequest: vi.fn(),
    };
});

import { ApiRequestError, apiRequest } from '../../../../src/app/apiClient';
import {
    readVersionZeroProfile,
    registerDataset,
    toInsightError,
} from '../../../../src/insight/api/insightClient';

describe('insightClient', () => {
    it('registerDataset posts the canonical payload', async () => {
        vi.mocked(apiRequest).mockResolvedValueOnce({
            data: {
                project: {} as any,
                dataset: { id: 'dataset_sales' } as any,
                version: {} as any,
                created: true,
            },
        });

        await registerDataset({
            tableName: 'sales_raw',
            datasetName: 'Sales Raw',
        });

        expect(apiRequest).toHaveBeenCalledWith('/api/insight/datasets', expect.objectContaining({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tableName: 'sales_raw',
                datasetName: 'Sales Raw',
            }),
        }));
    });

    it('reads the immutable version_000 profile path', async () => {
        vi.mocked(apiRequest).mockResolvedValueOnce({
            data: {
                profile: { id: 'profile_1', version_id: 'version_000' },
            } as any,
        });

        const profile = await readVersionZeroProfile('dataset_sales');

        expect(profile.id).toBe('profile_1');
        expect(apiRequest).toHaveBeenCalledWith(
            '/api/insight/datasets/dataset_sales/profiles/version_000',
            expect.objectContaining({ method: 'GET' }),
        );
    });

    it('normalizes ApiRequestError into InsightError', () => {
        const error = new ApiRequestError(
            {
                code: 'TABLE_NOT_FOUND',
                message: 'Dataset profile not found',
                detail: 'dataset_sales/version_000',
                retry: false,
                request_id: 'req-123',
            },
            404,
        );

        expect(toInsightError(error)).toEqual({
            code: 'TABLE_NOT_FOUND',
            message: 'Dataset profile not found',
            detail: 'dataset_sales/version_000',
            retryable: false,
            httpStatus: 404,
            requestId: 'req-123',
        });
    });
});
