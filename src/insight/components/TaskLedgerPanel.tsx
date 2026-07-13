import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Chip,
    LinearProgress,
    Stack,
    Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useTranslation } from 'react-i18next';

import {
    listDataAgentLedgerRuns,
    readAgentRun,
    subscribeToAgentRunEvents,
} from '../api/agentRunClient';
import { toInsightError } from '../api/insightClient';
import type {
    AgentRunSnapshot,
    AgentRunStatus,
    InsightError,
} from '../types';
import { AgentProgressCard } from './AgentProgressCard';

const ACTIVE_STATUSES = new Set<AgentRunStatus>(['created', 'analyzing']);
const TERMINAL_EVENTS = new Set([
    'run_completed',
    'run_failed',
    'run_cancelled',
    'run_interrupted',
    'user_input_required',
]);

function statusColor(
    status: AgentRunStatus,
): 'default' | 'primary' | 'success' | 'error' | 'warning' {
    if (status === 'completed') return 'success';
    if (status === 'failed' || status === 'interrupted') return 'error';
    if (status === 'cancelled' || status === 'waiting_user_input') return 'warning';
    if (ACTIVE_STATUSES.has(status)) return 'primary';
    return 'default';
}

function elapsedSeconds(snapshot: AgentRunSnapshot): number {
    const started = snapshot.run.started_at
        ? Date.parse(snapshot.run.started_at)
        : Date.parse(snapshot.run.created_at);
    const ended = snapshot.run.completed_at
        ? Date.parse(snapshot.run.completed_at)
        : Date.now();
    if (!Number.isFinite(started) || !Number.isFinite(ended)) return 0;
    return Math.max(0, Math.round((ended - started) / 1000));
}

export interface TaskLedgerPanelProps {
    workspaceId: string;
    tableName: string;
}

type LedgerStatus = 'loading' | 'ready' | 'error';

export function TaskLedgerPanel({ workspaceId, tableName }: TaskLedgerPanelProps) {
    const { t } = useTranslation();
    const [status, setStatus] = useState<LedgerStatus>('loading');
    const [snapshot, setSnapshot] = useState<AgentRunSnapshot | null>(null);
    const [error, setError] = useState<InsightError | null>(null);
    const requestSequence = useRef(0);
    const requestController = useRef<AbortController | null>(null);

    const loadLatest = useCallback(async (showLoading = false) => {
        const sequence = ++requestSequence.current;
        requestController.current?.abort();
        const controller = new AbortController();
        requestController.current = controller;
        if (showLoading) setStatus('loading');
        try {
            const runs = await listDataAgentLedgerRuns(tableName, controller.signal);
            const latest = runs[0];
            const next = latest
                ? await readAgentRun(latest.id, controller.signal)
                : null;
            if (sequence !== requestSequence.current) return;
            setSnapshot(next);
            setError(null);
            setStatus('ready');
        } catch (requestError) {
            if (controller.signal.aborted || sequence !== requestSequence.current) return;
            setError(toInsightError(requestError));
            setStatus('error');
        }
    }, [tableName, workspaceId]);

    useEffect(() => {
        setSnapshot(null);
        setError(null);
        void loadLatest(true);
        const timer = window.setInterval(() => {
            void loadLatest(false);
        }, 3000);
        return () => {
            requestSequence.current += 1;
            requestController.current?.abort();
            requestController.current = null;
            window.clearInterval(timer);
        };
    }, [loadLatest]);

    useEffect(() => {
        const run = snapshot?.run;
        if (!run || !ACTIVE_STATUSES.has(run.status)) return undefined;
        const source = subscribeToAgentRunEvents(run.id, {
            onEvent: (message) => {
                void loadLatest(false);
                if (TERMINAL_EVENTS.has(message.eventType)) {
                    source.close();
                }
            },
            onError: () => {
                source.close();
            },
        });
        return () => source.close();
    }, [loadLatest, snapshot?.run.id, snapshot?.run.status]);

    const duration = useMemo(
        () => (snapshot ? elapsedSeconds(snapshot) : 0),
        [snapshot],
    );

    if (status === 'loading') {
        return (
            <Stack spacing={1.25}>
                <LinearProgress />
                <Typography variant='body2' color='text.secondary'>
                    {t('insight.ledger.loading')}
                </Typography>
            </Stack>
        );
    }

    if (status === 'error') {
        return (
            <Stack spacing={1.5}>
                <Alert severity='error' variant='outlined'>
                    {error?.message || t('insight.ledger.error')}
                </Alert>
                <Button
                    size='small'
                    startIcon={<RefreshIcon />}
                    onClick={() => { void loadLatest(true); }}
                    sx={{ alignSelf: 'flex-start' }}
                >
                    {t('insight.ledger.retry')}
                </Button>
            </Stack>
        );
    }

    if (!snapshot) {
        return (
            <Stack spacing={1}>
                <Typography variant='h6' sx={{ fontWeight: 700 }}>
                    {t('insight.ledger.emptyTitle')}
                </Typography>
                <Typography variant='body2' color='text.secondary'>
                    {t('insight.ledger.emptyBody')}
                </Typography>
            </Stack>
        );
    }

    const firstStep = snapshot.steps[0];
    return (
        <Stack spacing={2}>
            <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={1}
                justifyContent='space-between'
                alignItems={{ xs: 'flex-start', sm: 'center' }}
            >
                <Box sx={{ minWidth: 0 }}>
                    <Typography variant='h6' sx={{ fontWeight: 700 }}>
                        {t('insight.ledger.title')}
                    </Typography>
                    <Typography
                        variant='body2'
                        color='text.secondary'
                        sx={{ mt: 0.5, overflowWrap: 'anywhere' }}
                    >
                        {firstStep?.title || t('insight.ledger.untitled')}
                    </Typography>
                </Box>
                <Stack direction='row' spacing={1} useFlexGap flexWrap='wrap'>
                    <Chip
                        size='small'
                        color={statusColor(snapshot.run.status)}
                        label={t(`insight.run.status.${snapshot.run.status}`)}
                    />
                    <Button
                        size='small'
                        startIcon={<RefreshIcon />}
                        onClick={() => { void loadLatest(true); }}
                    >
                        {t('insight.ledger.refresh')}
                    </Button>
                </Stack>
            </Stack>

            <Stack direction='row' spacing={1} useFlexGap flexWrap='wrap'>
                <Chip
                    size='small'
                    variant='outlined'
                    label={t('insight.ledger.duration', { seconds: duration })}
                />
                <Chip
                    size='small'
                    variant='outlined'
                    label={t('insight.ledger.steps', { count: snapshot.steps.length })}
                />
                <Chip
                    size='small'
                    variant='outlined'
                    label={t('insight.ledger.table', { tableName })}
                />
            </Stack>

            {snapshot.run.status === 'waiting_user_input' ? (
                <Alert severity='info' variant='outlined'>
                    {t('insight.ledger.waitingUser')}
                </Alert>
            ) : null}
            {snapshot.run.status === 'interrupted' ? (
                <Alert severity='warning' variant='outlined'>
                    {t('insight.ledger.interrupted')}
                </Alert>
            ) : null}

            <Box>
                {snapshot.steps.map((step) => (
                    <AgentProgressCard key={step.id} step={step} t={t} />
                ))}
            </Box>
        </Stack>
    );
}
