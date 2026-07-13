import { apiRequest } from '../../app/apiClient';
import type {
    AgentRun,
    AgentRunEventPayload,
    AgentRunSnapshot,
    CreateAgentRunResponse,
} from '../types';

const insightUrl = (path: string): string => `/api/insight${path}`;

export interface CreateAgentRunParams {
    datasetId: string;
    versionId?: string;
    goalId?: string;
    executionMode?: 'synchronous' | 'background';
}

export interface AgentRunEventMessage {
    eventType: string;
    lastEventId: string;
    payload: AgentRunEventPayload;
}

export interface AgentRunSubscriptionHandlers {
    onOpen?: () => void;
    onEvent: (message: AgentRunEventMessage) => void;
    onError?: (event: Event) => void;
}

const RUN_EVENT_TYPES = [
    'run_started',
    'stage_changed',
    'step_started',
    'step_progress',
    'step_completed',
    'approval_required',
    'artifact_created',
    'claim_created',
    'run_completed',
    'run_failed',
    'run_cancelled',
    'heartbeat',
] as const;

export async function createAgentRun(
    params: CreateAgentRunParams,
    signal?: AbortSignal,
): Promise<CreateAgentRunResponse> {
    const { data } = await apiRequest<CreateAgentRunResponse>(insightUrl('/runs'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            datasetId: params.datasetId,
            versionId: params.versionId,
            goalId: params.goalId,
            executionMode: params.executionMode ?? 'background',
        }),
        signal,
    });
    return data;
}

export async function listAgentRuns(
    datasetId?: string,
    signal?: AbortSignal,
): Promise<AgentRun[]> {
    const params = new URLSearchParams();
    if (datasetId) params.set('datasetId', datasetId);
    const query = params.toString();
    const { data } = await apiRequest<{ runs: AgentRun[] }>(
        insightUrl(`/runs${query ? `?${query}` : ''}`),
        { method: 'GET', signal },
    );
    return data.runs;
}

export async function readAgentRun(
    runId: string,
    signal?: AbortSignal,
): Promise<AgentRunSnapshot> {
    const { data } = await apiRequest<AgentRunSnapshot>(
        insightUrl(`/runs/${encodeURIComponent(runId)}`),
        { method: 'GET', signal },
    );
    return data;
}

export async function cancelAgentRun(
    runId: string,
    reason = 'Cancelled by user',
    signal?: AbortSignal,
): Promise<AgentRunSnapshot> {
    const { data } = await apiRequest<AgentRunSnapshot>(
        insightUrl(`/runs/${encodeURIComponent(runId)}/cancel`),
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason }),
            signal,
        },
    );
    return data;
}

export function agentRunEventsUrl(runId: string, afterEventId?: string | null): string {
    const params = new URLSearchParams();
    if (afterEventId) params.set('afterEventId', afterEventId);
    const query = params.toString();
    return insightUrl(
        `/runs/${encodeURIComponent(runId)}/events${query ? `?${query}` : ''}`,
    );
}

export function subscribeToAgentRunEvents(
    runId: string,
    handlers: AgentRunSubscriptionHandlers,
    afterEventId?: string | null,
): EventSource {
    const source = new EventSource(agentRunEventsUrl(runId, afterEventId));
    source.onopen = () => handlers.onOpen?.();
    source.onerror = (event) => handlers.onError?.(event);

    RUN_EVENT_TYPES.forEach((eventType) => {
        source.addEventListener(eventType, (event) => {
            const messageEvent = event as MessageEvent<string>;
            const payload = JSON.parse(messageEvent.data) as AgentRunEventPayload;
            handlers.onEvent({
                eventType,
                lastEventId: messageEvent.lastEventId,
                payload,
            });
        });
    });

    return source;
}
