import { ApiRequestError, apiRequest } from '../../app/apiClient';
import type {
    InsightError,
    ReadDatasetProfileResponse,
    RegisterDatasetResponse,
} from '../types';

export interface RegisterDatasetParams {
    tableName: string;
    datasetName: string;
}

const insightUrl = (path: string): string => `/api/insight${path}`;

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
