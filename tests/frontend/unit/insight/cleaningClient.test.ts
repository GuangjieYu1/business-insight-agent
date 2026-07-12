import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../src/app/apiClient', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../../src/app/apiClient')>();
    return {
        ...actual,
        apiRequest: vi.fn(),
    };
});

import { apiRequest } from '../../../../src/app/apiClient';
import {
    applyCleaningProposal,
    compareDatasetProfiles,
    listCleaningProposals,
    listDatasetOperations,
    listDatasetVersions,
    previewCleaningProposal,
    undoCleaningOperation,
} from '../../../../src/insight/api/insightClient';

describe('cleaning insight client', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('lists proposals for a specific dataset version', async () => {
        vi.mocked(apiRequest).mockResolvedValueOnce({ data: { proposals: [] } });

        await listCleaningProposals('dataset_sales', 'version_001');

        expect(apiRequest).toHaveBeenCalledWith(
            '/api/insight/datasets/dataset_sales/versions/version_001/cleaning/proposals',
            expect.objectContaining({ method: 'GET' }),
        );
    });

    it('previews and applies a selected operation with output analysis', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { operation: {}, proposal: {}, warnings: [], sampleDiff: [] } as any })
            .mockResolvedValueOnce({ data: { operation: {}, proposal: {}, dataset: { id: 'dataset_sales' }, version: {}, idempotent: false } as any });

        const request = { operationType: 'rename_column', parameters: { new_name: 'customer_name' } };
        await previewCleaningProposal('proposal_1', request);
        await applyCleaningProposal('proposal_1', request);

        expect(apiRequest).toHaveBeenNthCalledWith(
            1,
            '/api/insight/cleaning/proposals/proposal_1/preview',
            expect.objectContaining({ body: JSON.stringify(request) }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/insight/cleaning/proposals/proposal_1/apply-with-analysis',
            expect.objectContaining({ body: JSON.stringify(request) }),
        );
    });

    it('loads versions, operations, and profile comparison', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { dataset: {}, versions: [], activeVersionId: 'version_001' } as any })
            .mockResolvedValueOnce({ data: { operations: [] } as any })
            .mockResolvedValueOnce({ data: { metricDelta: {} } as any });

        await listDatasetVersions('dataset_sales');
        await listDatasetOperations('dataset_sales');
        await compareDatasetProfiles('dataset_sales', 'version_000', 'version_001');

        expect(apiRequest).toHaveBeenNthCalledWith(
            1,
            '/api/insight/datasets/dataset_sales/versions',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/insight/datasets/dataset_sales/operations',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            3,
            '/api/insight/datasets/dataset_sales/profiles/compare?beforeVersionId=version_000&afterVersionId=version_001',
            expect.objectContaining({ method: 'GET' }),
        );
    });

    it('sends undo reason', async () => {
        vi.mocked(apiRequest).mockResolvedValueOnce({
            data: {
                dataset: { id: 'dataset_sales' },
                activeVersion: {},
                previousVersion: {},
                operation: {},
                undoneOperation: {},
            } as any,
        });

        await undoCleaningOperation('operation_1', 'Undo from UI');

        expect(apiRequest).toHaveBeenCalledWith(
            '/api/insight/operations/operation_1/undo',
            expect.objectContaining({ body: JSON.stringify({ reason: 'Undo from UI' }) }),
        );
    });
});
