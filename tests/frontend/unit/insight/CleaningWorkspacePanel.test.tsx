import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, params?: Record<string, unknown>) => {
            if (key === 'insight.cleaning.metricDelta') {
                return `${params?.metric}: ${params?.before} -> ${params?.after} (${params?.delta})`;
            }
            if (key === 'insight.cleaning.affected') {
                return `affected ${params?.rows} ${params?.columns}`;
            }
            return key;
        },
    }),
}));

vi.mock('../../../../src/insight/api/insightClient', () => ({
    listCleaningProposals: vi.fn(),
    generateCleaningProposals: vi.fn(),
    listDatasetVersions: vi.fn(),
    previewCleaningProposal: vi.fn(),
    approveCleaningProposal: vi.fn(),
    rejectCleaningProposal: vi.fn(),
    applyCleaningProposal: vi.fn(),
    undoCleaningOperation: vi.fn(),
    toInsightError: (error: unknown) => ({
        code: 'TEST_ERROR',
        message: error instanceof Error ? error.message : String(error),
        retryable: false,
    }),
}));

import {
    approveCleaningProposal,
    listCleaningProposals,
    listDatasetVersions,
    previewCleaningProposal,
} from '../../../../src/insight/api/insightClient';
import { CleaningWorkspacePanel } from '../../../../src/insight/components/CleaningWorkspacePanel';
import type { CleaningProposal, DatasetVersion } from '../../../../src/insight/types';

const proposal: CleaningProposal = {
    id: 'proposal_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
    dataset_version_id: 'version_000',
    problem_type: 'whitespace_pollution',
    severity: 'low',
    confidence: 0.9,
    scope: { dataset_id: 'dataset_sales', column: 'customer_name' },
    evidence: { whitespace_pollution_count: 2 },
    recommended_operation: 'trim_string',
    alternatives: ['keep_column'],
    requires_approval: true,
    status: 'pending',
};

const version: DatasetVersion = {
    id: 'version_000',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
    dataset_id: 'dataset_sales',
    parent_version_id: null,
    created_by_operation_id: null,
    content_hash: 'hash-1',
    row_count: 3,
    column_count: 2,
    file_ref: 'datasets/dataset_sales/versions/version_000.parquet',
    status: 'active',
};

describe('CleaningWorkspacePanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(listCleaningProposals).mockResolvedValue([proposal]);
        vi.mocked(listDatasetVersions).mockResolvedValue({
            dataset: { id: 'dataset_sales' } as any,
            versions: [version],
            activeVersionId: 'version_000',
        });
    });

    it('loads persisted proposals and keeps the standalone header and version history by default', async () => {
        render(<CleaningWorkspacePanel datasetId="dataset_sales" />);

        expect(await screen.findByText('insight.issueTypes.whitespace_pollution')).toBeInTheDocument();
        expect(screen.getByText('insight.cleaning.title')).toBeInTheDocument();
        expect(screen.getByText('insight.cleaning.versions.title')).toBeInTheDocument();
        expect(screen.getByText('version_000 · 3 × 2')).toBeInTheDocument();
        expect(screen.getByText('insight.cleaning.status.pending')).toBeInTheDocument();
    });

    it('shows a privacy-safe preview and allows approval', async () => {
        vi.mocked(previewCleaningProposal).mockResolvedValue({
            proposal,
            operation: {
                id: 'operation_preview_1',
                schema_version: '1.0',
                workspace_id: 'workspace_1',
                created_at: '2026-07-12T00:00:00Z',
                updated_at: '2026-07-12T00:00:00Z',
                proposal_id: proposal.id,
                operation_type: 'trim_string',
                input_version_id: 'version_000',
                output_version_id: null,
                parameters: {},
                reason: 'preview',
                status: 'previewed',
                reversible: true,
                before_metrics: { row_count: 3, column_count: 2, null_cell_count: 0, duplicate_excess_row_count: 0 },
                after_metrics: { row_count: 3, column_count: 2, null_cell_count: 0, duplicate_excess_row_count: 0 },
                metric_delta: { row_count: 0, column_count: 0, null_cell_count: 0, duplicate_excess_row_count: 0 },
                animation_payload: {
                    affected_rows: 2,
                    affected_columns: ['customer_name'],
                    raw_values_included: false,
                },
            },
            warnings: [],
            sampleDiff: [{ change_type: 'cell_updated', row_index: '0' }],
        });
        vi.mocked(approveCleaningProposal).mockResolvedValue({ ...proposal, status: 'approved' });

        render(<CleaningWorkspacePanel datasetId="dataset_sales" />);
        await screen.findByText('insight.issueTypes.whitespace_pollution');

        fireEvent.click(screen.getByText('insight.cleaning.preview'));
        expect(await screen.findByText('insight.cleaning.previewTitle')).toBeInTheDocument();
        expect(screen.queryByText(' Alice ')).not.toBeInTheDocument();
        expect(screen.getByText('affected 2 customer_name')).toBeInTheDocument();

        fireEvent.click(screen.getByText('insight.cleaning.approve'));
        await waitFor(() => expect(approveCleaningProposal).toHaveBeenCalledWith('proposal_1'));
        expect(await screen.findByText('insight.cleaning.status.approved')).toBeInTheDocument();
    });

    it('can hide duplicated header and version controls for the embedded workspace mode', async () => {
        render(
            <CleaningWorkspacePanel
                datasetId="dataset_sales"
                showHeader={false}
                showVersionHistory={false}
                showUndo={false}
            />,
        );

        expect(await screen.findByText('insight.issueTypes.whitespace_pollution')).toBeInTheDocument();
        expect(screen.queryByText('insight.cleaning.title')).not.toBeInTheDocument();
        expect(screen.queryByText('insight.cleaning.versions.title')).not.toBeInTheDocument();
        expect(screen.queryByText('insight.cleaning.refresh')).not.toBeInTheDocument();
        expect(screen.queryByText('version_000 · 3 × 2')).not.toBeInTheDocument();
    });
});
