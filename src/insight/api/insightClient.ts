import { ApiRequestError, apiRequest } from '../../app/apiClient';
import type {
    CleaningApplyResponse,
    CleaningOperation,
    CleaningPreviewResponse,
    CleaningProposal,
    DatasetProfile,
    DatasetVersionsResponse,
    InsightError,
    ProfileQualityIssue,
    ReadDatasetProfileResponse,
    RegisterDatasetResponse,
    UndoOperationResponse,
} from '../types';

export interface RegisterDatasetParams {
    tableName: string;
    datasetName: string;
}

export interface CleaningOperationRequest {
    operationType?: string;
    parameters?: Record<string, unknown>;
    reason?: string;
}

export interface DatasetOperationsResponse {
    operations: CleaningOperation[];
}

export interface ProfileComparisonResponse {
    datasetId: string;
    beforeVersionId: string;
    afterVersionId: string;
    beforeProfile: DatasetProfile;
    afterProfile: DatasetProfile;
    beforeMetrics: Record<string, number>;
    afterMetrics: Record<string, number>;
    metricDelta: Record<string, number>;
    resolvedIssues: ProfileQualityIssue[];
    introducedIssues: ProfileQualityIssue[];
    unchangedIssues: Array<{
        before: ProfileQualityIssue;
        after: ProfileQualityIssue;
    }>;
}

export const INSIGHT_DATASET_HISTORY_CHANGED = 'insight:dataset-history-changed';

const insightUrl = (path: string): string => `/api/insight${path}`;
const jsonOptions = (body?: unknown): RequestInit => ({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
});

function notifyDatasetHistoryChanged(datasetId: string): void {
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent(INSIGHT_DATASET_HISTORY_CHANGED, {
            detail: { datasetId },
        }));
    }
}

export function toInsightError(error: unknown): InsightError {
    if (error instanceof ApiRequestError) {
        return {
            code: error.apiError.code,
            message: error.apiError.message,
            detail: error.apiError.detail,
            retryable: error.isRetryable,
            httpStatus: error.httpStatus,
            requestId: error.apiError.request_id,
        };
    }

    if (error instanceof Error) {
        return {
            code: error.name || 'UNKNOWN_ERROR',
            message: error.message,
            retryable: false,
        };
    }

    return {
        code: 'UNKNOWN_ERROR',
        message: 'Unknown insight request failure',
        retryable: false,
    };
}

export function isInsightApiError(error: unknown, code?: string): error is ApiRequestError {
    return error instanceof ApiRequestError && (code === undefined || error.apiError.code === code);
}

export async function registerDataset(
    params: RegisterDatasetParams,
    signal?: AbortSignal,
): Promise<RegisterDatasetResponse> {
    const { data } = await apiRequest<RegisterDatasetResponse>(insightUrl('/datasets'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            tableName: params.tableName,
            datasetName: params.datasetName,
        }),
        signal,
    });
    return data;
}

export async function readVersionZeroProfile(
    datasetId: string,
    signal?: AbortSignal,
): Promise<ReadDatasetProfileResponse['profile']> {
    const { data } = await apiRequest<ReadDatasetProfileResponse>(
        insightUrl(`/datasets/${datasetId}/profiles/version_000`),
        {
            method: 'GET',
            signal,
        },
    );
    return data.profile;
}

export async function generateVersionZeroProfile(
    datasetId: string,
    signal?: AbortSignal,
): Promise<ReadDatasetProfileResponse['profile']> {
    const { data } = await apiRequest<ReadDatasetProfileResponse>(
        insightUrl(`/datasets/${datasetId}/profile`),
        {
            method: 'POST',
            signal,
        },
    );
    return data.profile;
}

export async function readDatasetVersionProfile(
    datasetId: string,
    versionId: string,
    signal?: AbortSignal,
): Promise<DatasetProfile> {
    const { data } = await apiRequest<ReadDatasetProfileResponse>(
        insightUrl(`/datasets/${datasetId}/versions/${versionId}/profile`),
        { method: 'GET', signal },
    );
    return data.profile;
}

export async function generateDatasetVersionProfile(
    datasetId: string,
    versionId: string,
    signal?: AbortSignal,
): Promise<DatasetProfile> {
    const { data } = await apiRequest<ReadDatasetProfileResponse>(
        insightUrl(`/datasets/${datasetId}/versions/${versionId}/profile`),
        { method: 'POST', signal },
    );
    return data.profile;
}

export async function listCleaningProposals(
    datasetId: string,
    versionId = 'version_000',
    signal?: AbortSignal,
): Promise<CleaningProposal[]> {
    const { data } = await apiRequest<{ proposals: CleaningProposal[] }>(
        insightUrl(`/datasets/${datasetId}/versions/${versionId}/cleaning/proposals`),
        { method: 'GET', signal },
    );
    return data.proposals;
}

export async function generateCleaningProposals(
    datasetId: string,
    versionId = 'version_000',
    signal?: AbortSignal,
): Promise<CleaningProposal[]> {
    const { data } = await apiRequest<{ proposals: CleaningProposal[] }>(
        insightUrl(`/datasets/${datasetId}/versions/${versionId}/cleaning/proposals`),
        { ...jsonOptions(), signal },
    );
    return data.proposals;
}

export async function previewCleaningProposal(
    proposalId: string,
    request: CleaningOperationRequest = {},
    signal?: AbortSignal,
): Promise<CleaningPreviewResponse> {
    const { data } = await apiRequest<CleaningPreviewResponse>(
        insightUrl(`/cleaning/proposals/${proposalId}/preview`),
        { ...jsonOptions(request), signal },
    );
    return data;
}

export async function approveCleaningProposal(
    proposalId: string,
    signal?: AbortSignal,
): Promise<CleaningProposal> {
    const { data } = await apiRequest<{ proposal: CleaningProposal }>(
        insightUrl(`/cleaning/proposals/${proposalId}/approve`),
        { ...jsonOptions(), signal },
    );
    return data.proposal;
}

export async function rejectCleaningProposal(
    proposalId: string,
    signal?: AbortSignal,
): Promise<CleaningProposal> {
    const { data } = await apiRequest<{ proposal: CleaningProposal }>(
        insightUrl(`/cleaning/proposals/${proposalId}/reject`),
        { ...jsonOptions(), signal },
    );
    return data.proposal;
}

export async function applyCleaningProposal(
    proposalId: string,
    request: CleaningOperationRequest = {},
    signal?: AbortSignal,
): Promise<CleaningApplyResponse> {
    const { data } = await apiRequest<CleaningApplyResponse>(
        insightUrl(`/cleaning/proposals/${proposalId}/apply-with-analysis`),
        { ...jsonOptions(request), signal },
    );
    notifyDatasetHistoryChanged(data.dataset.id);
    return data;
}

export async function listDatasetVersions(
    datasetId: string,
    signal?: AbortSignal,
): Promise<DatasetVersionsResponse> {
    const { data } = await apiRequest<DatasetVersionsResponse>(
        insightUrl(`/datasets/${datasetId}/versions`),
        { method: 'GET', signal },
    );
    return data;
}

export async function listDatasetOperations(
    datasetId: string,
    signal?: AbortSignal,
): Promise<CleaningOperation[]> {
    const { data } = await apiRequest<DatasetOperationsResponse>(
        insightUrl(`/datasets/${datasetId}/operations`),
        { method: 'GET', signal },
    );
    return data.operations;
}

export async function compareDatasetProfiles(
    datasetId: string,
    beforeVersionId: string,
    afterVersionId: string,
    signal?: AbortSignal,
): Promise<ProfileComparisonResponse> {
    const params = new URLSearchParams({ beforeVersionId, afterVersionId });
    const { data } = await apiRequest<ProfileComparisonResponse>(
        insightUrl(`/datasets/${datasetId}/profiles/compare?${params.toString()}`),
        { method: 'GET', signal },
    );
    return data;
}

export async function undoCleaningOperation(
    operationId: string,
    reason = 'Undo cleaning operation',
    signal?: AbortSignal,
): Promise<UndoOperationResponse> {
    const { data } = await apiRequest<UndoOperationResponse>(
        insightUrl(`/operations/${operationId}/undo`),
        { ...jsonOptions({ reason }), signal },
    );
    notifyDatasetHistoryChanged(data.dataset.id);
    return data;
}
