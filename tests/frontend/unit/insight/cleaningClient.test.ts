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
    listCleaningProposals,
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

        await listCleaningProposals('dataset_sales', 'version_000');

        expect(apiRequest).toHaveBeenCalledWith(
            '/api/insight/cleaning/proposals?datasetId=dataset_sales&versionId=version_000',
            expect.objectContaining({ method: 'GET' }),
        );
    });

    it('previews and applies a selected operation with output analysis', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { operation: {}, proposal: {}, warnings: [], sampleDiff: [] } as any })
            .mockResolvedValueOnce({ data: { operation: {}, proposal: {}, dataset: {}, version: {}, idempotent: false } as any });

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

    it('loads version history and sends undo reason', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { dataset: {}, versions: [], activeVersionId: 'version_001' } as any })
            .mockResolvedValueOnce({ data: { dataset: {}, activeVersion: {}, previousVersion: {}, operation: {}, undoneOperation: {} } as any });

        await listDatasetVersions('dataset_sales');
        await undoCleaningOperation('operation_1', 'Undo from UI');

        expect(apiRequest).toHaveBeenNthCalledWith(
            1,
            '/api/insight/datasets/dataset_sales/versions',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/insight/operations/operation_1/undo',
            expect.objectContaining({ body: JSON.stringify({ reason: 'Undo from UI' }) }),
        );
    });
});
