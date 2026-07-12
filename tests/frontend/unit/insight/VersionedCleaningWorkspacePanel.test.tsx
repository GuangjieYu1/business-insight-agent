import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, params?: Record<string, unknown>) => {
            if (key === 'insight.versionComparison.title') {
                return `${params?.before} -> ${params?.after}`;
            }
            if (key === 'insight.versionComparison.metric') {
                return `${params?.metric}: ${params?.before} -> ${params?.after} (${params?.delta})`;
            }
            if (key === 'insight.versionComparison.resolved') return `resolved ${params?.count}`;
            if (key === 'insight.versionComparison.introduced') return `introduced ${params?.count}`;
            if (key === 'insight.versionComparison.unchanged') return `unchanged ${params?.count}`;
            if (key === 'insight.cleaning.notice.undone') return `undone ${params?.versionId}`;
            return key;
        },
    }),
}));

vi.mock('../../../../src/insight/components/CleaningWorkspacePanel', () => ({
    CleaningWorkspacePanel: ({ datasetId, versionId }: { datasetId: string; versionId: string }) => (
        <div>{`cleaning ${datasetId} ${versionId}`}</div>
    ),
}));

vi.mock('../../../../src/insight/api/insightClient', () => ({
    INSIGHT_DATASET_HISTORY_CHANGED: 'insight:dataset-history-changed',
    listDatasetVersions: vi.fn(),
    listDatasetOperations: vi.fn(),
    compareDatasetProfiles: vi.fn(),
    undoCleaningOperation: vi.fn(),
    toInsightError: (error: unknown) => ({
        code: 'TEST_ERROR',
        message: error instanceof Error ? error.message : String(error),
        retryable: false,
    }),
}));

import {
    compareDatasetProfiles,
    listDatasetOperations,
    listDatasetVersions,
    undoCleaningOperation,
} from '../../../../src/insight/api/insightClient';
import { VersionedCleaningWorkspacePanel } from '../../../../src/insight/components/VersionedCleaningWorkspacePanel';
import type { CleaningOperation, DatasetVersion, ProfileQualityIssue } from '../../../../src/insight/types';

const version000: DatasetVersion = {
    id: 'version_000',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
    dataset_id: 'dataset_sales',
    parent_version_id: null,
    created_by_operation_id: null,
    content_hash: 'hash-0',
    row_count: 3,
    column_count: 2,
    file_ref: 'datasets/dataset_sales/versions/version_000.parquet',
    status: 'historical',
};

const version001: DatasetVersion = {
    ...version000,
    id: 'version_001',
    parent_version_id: 'version_000',
    created_by_operation_id: 'operation_1',
    content_hash: 'hash-1',
    row_count: 2,
    status: 'active',
};

const operation: CleaningOperation = {
    id: 'operation_1',
    schema_version: '1.0',
    workspace_id: 'workspace_1',
    created_at: '2026-07-12T00:01:00Z',
    updated_at: '2026-07-12T00:01:00Z',
    proposal_id: 'proposal_1',
    operation_type: 'drop_duplicate_rows',
    input_version_id: 'version_000',
    output_version_id: 'version_001',
    parameters: { dataset_id: 'dataset_sales' },
    reason: 'Drop duplicates',
    status: 'completed',
    reversible: true,
    before_metrics: {},
    after_metrics: {},
    metric_delta: {},
    animation_payload: {},
};

const duplicateIssue: ProfileQualityIssue = {
    issue_type: 'duplicate_rows',
    severity: 'medium',
    scope: { dataset_id: 'dataset_sales', version_id: 'version_000' },
    metrics: { duplicate_excess_row_count: 1 },
    message: 'Duplicate rows detected',
};

describe('VersionedCleaningWorkspacePanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(listDatasetVersions).mockResolvedValue({
            dataset: { id: 'dataset_sales' } as any,
            versions: [version000, version001],
            activeVersionId: 'version_001',
        });
        vi.mocked(listDatasetOperations).mockResolvedValue([operation]);
        vi.mocked(compareDatasetProfiles).mockResolvedValue({
            datasetId: 'dataset_sales',
            beforeVersionId: 'version_000',
            afterVersionId: 'version_001',
            beforeProfile: {} as any,
            afterProfile: {} as any,
            beforeMetrics: {
                row_count: 3,
                column_count: 2,
                duplicate_excess_row_count: 1,
                quality_issue_count: 1,
                high_issue_count: 0,
                medium_issue_count: 1,
            },
            afterMetrics: {
                row_count: 2,
                column_count: 2,
                duplicate_excess_row_count: 0,
                quality_issue_count: 0,
                high_issue_count: 0,
                medium_issue_count: 0,
            },
            metricDelta: {
                row_count: -1,
                column_count: 0,
                duplicate_excess_row_count: -1,
                quality_issue_count: -1,
                high_issue_count: 0,
                medium_issue_count: -1,
            },
            resolvedIssues: [duplicateIssue],
            introducedIssues: [],
            unchangedIssues: [],
        });
    });

    it('selects the active version, compares with its parent, and restores persistent Undo', async () => {
        render(<VersionedCleaningWorkspacePanel datasetId="dataset_sales" />);

        expect(await screen.findByText('cleaning dataset_sales version_001')).toBeInTheDocument();
        expect(await screen.findByText('version_000 -> version_001')).toBeInTheDocument();
        expect(screen.getByText('resolved 1')).toBeInTheDocument();
        expect(screen.getByText('insight.issueTypes.duplicate_rows')).toBeInTheDocument();
        expect(screen.getByText('insight.versionContext.undoPersistent')).toBeInTheDocument();
        expect(compareDatasetProfiles).toHaveBeenCalledWith(
            'dataset_sales',
            'version_000',
            'version_001',
            expect.any(AbortSignal),
        );
    });

    it('undoes the active cleaning from persisted operation history', async () => {
        vi.mocked(undoCleaningOperation).mockResolvedValue({
            dataset: { id: 'dataset_sales' } as any,
            activeVersion: { ...version000, status: 'active' },
            previousVersion: { ...version001, status: 'historical' },
            operation: { ...operation, id: 'undo_operation_1', operation_type: 'undo' },
            undoneOperation: { ...operation, status: 'undone' },
        });

        render(<VersionedCleaningWorkspacePanel datasetId="dataset_sales" />);
        await screen.findByText('insight.versionContext.undoPersistent');
        fireEvent.click(screen.getByText('insight.versionContext.undoPersistent'));

        await waitFor(() => expect(undoCleaningOperation).toHaveBeenCalledWith('operation_1'));
        expect(await screen.findByText('undone version_000')).toBeInTheDocument();
    });
});
