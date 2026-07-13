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
    agentRunEventsUrl,
    cancelAgentRun,
    createAgentRun,
    listAgentRuns,
    readAgentRun,
    subscribeToAgentRunEvents,
} from '../../../../src/insight/api/agentRunClient';

class FakeEventSource {
    static instances: FakeEventSource[] = [];

    url: string;
    onopen: ((event: Event) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    listeners = new Map<string, Array<(event: Event) => void>>();
    closed = false;

    constructor(url: string) {
        this.url = url;
        FakeEventSource.instances.push(this);
    }

    addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
        const callback = typeof listener === 'function'
            ? listener
            : (event: Event) => listener.handleEvent(event);
        this.listeners.set(type, [...(this.listeners.get(type) || []), callback]);
    }

    close(): void {
        this.closed = true;
    }

    emit(type: string, payload: Record<string, unknown>, lastEventId = ''): void {
        const event = new MessageEvent(type, {
            data: JSON.stringify(payload),
            lastEventId,
        });
        (this.listeners.get(type) || []).forEach((listener) => listener(event));
    }
}

describe('agentRunClient', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        FakeEventSource.instances = [];
        vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
    });

    it('creates a background run with the canonical request body', async () => {
        vi.mocked(apiRequest).mockResolvedValueOnce({
            data: {
                run: { id: 'run_1' },
                steps: [],
                finalSummary: null,
                profile: null,
                proposals: [],
                executionMode: 'background',
            } as any,
        });

        await createAgentRun({
            datasetId: 'dataset_sales',
            versionId: 'version_002',
        });

        expect(apiRequest).toHaveBeenCalledWith('/api/insight/runs', expect.objectContaining({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                datasetId: 'dataset_sales',
                versionId: 'version_002',
                goalId: undefined,
                executionMode: 'background',
            }),
        }));
    });

    it('lists, reads, and cancels runs through scoped endpoints', async () => {
        vi.mocked(apiRequest)
            .mockResolvedValueOnce({ data: { runs: [{ id: 'run_1' }] } as any })
            .mockResolvedValueOnce({ data: { run: { id: 'run_1' }, steps: [], finalSummary: null } as any })
            .mockResolvedValueOnce({ data: { run: { id: 'run_1' }, steps: [], finalSummary: null } as any });

        await listAgentRuns('dataset sales');
        await readAgentRun('run/1');
        await cancelAgentRun('run/1', 'Stop now');

        expect(apiRequest).toHaveBeenNthCalledWith(
            1,
            '/api/insight/runs?datasetId=dataset+sales',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/insight/runs/run%2F1',
            expect.objectContaining({ method: 'GET' }),
        );
        expect(apiRequest).toHaveBeenNthCalledWith(
            3,
            '/api/insight/runs/run%2F1/cancel',
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({ reason: 'Stop now' }),
            }),
        );
    });

    it('subscribes with a stable cursor and forwards named SSE events', () => {
        const onEvent = vi.fn();
        const onOpen = vi.fn();
        const onError = vi.fn();

        const source = subscribeToAgentRunEvents(
            'run/1',
            { onEvent, onOpen, onError },
            'step_1:stage',
        ) as unknown as FakeEventSource;

        expect(agentRunEventsUrl('run/1', 'step_1:stage')).toBe(
            '/api/insight/runs/run%2F1/events?afterEventId=step_1%3Astage',
        );
        expect(source.url).toBe('/api/insight/runs/run%2F1/events?afterEventId=step_1%3Astage');

        source.onopen?.(new Event('open'));
        source.emit(
            'step_completed',
            {
                eventType: 'step_completed',
                runId: 'run/1',
                runStatus: 'profiling',
                timestamp: '2026-07-13T00:00:00Z',
            },
            'step_2',
        );
        source.onerror?.(new Event('error'));

        expect(onOpen).toHaveBeenCalledTimes(1);
        expect(onEvent).toHaveBeenCalledWith({
            eventType: 'step_completed',
            lastEventId: 'step_2',
            payload: expect.objectContaining({
                runId: 'run/1',
                runStatus: 'profiling',
            }),
        });
        expect(onError).toHaveBeenCalledTimes(1);
    });
});
