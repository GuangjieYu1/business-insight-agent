import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    LinearProgress,
    Stack,
    Typography,
} from '@mui/material';
import CancelOutlinedIcon from '@mui/icons-material/CancelOutlined';
import CleaningServicesOutlinedIcon from '@mui/icons-material/CleaningServicesOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useTranslation } from 'react-i18next';

import type { AppDispatch, RootState } from '../../app/store';
import { subscribeToAgentRunEvents } from '../api/agentRunClient';
import {
    agentRunActions,
    cancelObservableAgentRun,
    refreshAgentRun,
    restoreLatestAgentRun,
    selectAgentRunResource,
    startObservableAgentRun,
} from '../store/agentRunSlice';
import type { AgentRunStatus } from '../types';
import { AgentProgressCard } from './AgentProgressCard';
import { FinalConclusionView } from './FinalConclusionView';
import { ProcessDrawer } from './ProcessDrawer';

const ACTIVE_RUN_STATUSES = new Set<AgentRunStatus>([
    'created',
    'context_building',
    'profiling',
    'planning',
    'cleaning',
    'analyzing',
    'experimenting',
    'synthesizing',
]);

const TERMINAL_STREAM_EVENTS = new Set([
    'approval_required',
    'run_completed',
    'run_failed',
    'run_cancelled',
]);

function statusColor(status: AgentRunStatus): 'default' | 'primary' | 'success' | 'error' | 'warning' {
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'error';
    if (status === 'cancelled') return 'warning';
    if (status === 'waiting_approval') return 'warning';
    if (ACTIVE_RUN_STATUSES.has(status)) return 'primary';
    return 'default';
}

export interface AgentRunWorkspaceProps {
    datasetId: string;
    versionId: string;
    onOpenCleaning: () => void;
}

export function AgentRunWorkspace({ datasetId, versionId, onOpenCleaning }: AgentRunWorkspaceProps) {
    const dispatch = useDispatch<AppDispatch>();
    const { t } = useTranslation();
    const resource = useSelector((state: RootState) => selectAgentRunResource(state, datasetId));
    const [reconnectToken, setReconnectToken] = useState(0);
    const lastEventIdRef = useRef<string | null>(null);
    const refreshTimerRef = useRef<number | null>(null);

    const run = resource?.run ?? null;
    const steps = resource?.steps ?? [];
    const finalSummary = resource?.finalSummary ?? null;
    const shouldStream = Boolean(run && ACTIVE_RUN_STATUSES.has(run.status));

    useEffect(() => {
        lastEventIdRef.current = resource?.lastEventId ?? null;
    }, [resource?.lastEventId]);

    useEffect(() => {
        if (!resource || resource.status === 'idle') {
            void dispatch(restoreLatestAgentRun({ datasetId }));
        }
    }, [datasetId, dispatch, resource, resource?.status]);

    useEffect(() => {
        if (!run?.id || !shouldStream) return undefined;

        let disposed = false;
        let reconnectTimer: number | null = null;
        dispatch(agentRunActions.streamConnecting({ datasetId }));

        const scheduleRefresh = () => {
            if (refreshTimerRef.current !== null) {
                window.clearTimeout(refreshTimerRef.current);
            }
            refreshTimerRef.current = window.setTimeout(() => {
                refreshTimerRef.current = null;
                void dispatch(refreshAgentRun({ datasetId, runId: run.id }));
            }, 40);
        };

        const source = subscribeToAgentRunEvents(
            run.id,
            {
                onOpen: () => {
                    if (!disposed) dispatch(agentRunActions.streamOpened({ datasetId }));
                },
                onEvent: (message) => {
                    if (disposed) return;
                    if (message.lastEventId) lastEventIdRef.current = message.lastEventId;
                    dispatch(agentRunActions.eventReceived({
                        datasetId,
                        lastEventId: message.lastEventId,
                        event: message.payload,
                    }));
                    scheduleRefresh();
                    if (TERMINAL_STREAM_EVENTS.has(message.eventType)) {
                        source.close();
                        dispatch(agentRunActions.streamClosed({ datasetId }));
                    }
                },
                onError: () => {
                    if (disposed) return;
                    source.close();
                    dispatch(agentRunActions.streamFailed({ datasetId }));
                    reconnectTimer = window.setTimeout(() => {
                        if (!disposed) setReconnectToken((value) => value + 1);
                    }, 1200);
                },
            },
            lastEventIdRef.current,
        );

        return () => {
            disposed = true;
            source.close();
            if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
            if (refreshTimerRef.current !== null) {
                window.clearTimeout(refreshTimerRef.current);
                refreshTimerRef.current = null;
            }
        };
    }, [datasetId, dispatch, reconnectToken, run?.id, shouldStream]);

    const currentStep = useMemo(() => {
        for (let index = steps.length - 1; index >= 0; index -= 1) {
            if (steps[index].status === 'running' || steps[index].status === 'pending') return steps[index];
        }
        return steps[steps.length - 1];
    }, [steps]);

    const handleStart = () => {
        void dispatch(startObservableAgentRun({ datasetId, versionId }));
    };

    const handleRefresh = () => {
        if (run) void dispatch(refreshAgentRun({ datasetId, runId: run.id }));
        else void dispatch(restoreLatestAgentRun({ datasetId }));
    };

    const handleCancel = () => {
        if (!run) return;
        void dispatch(cancelObservableAgentRun({
            datasetId,
            runId: run.id,
            reason: t('insight.run.cancelReason'),
        }));
    };

    const openProcess = () => dispatch(agentRunActions.setProcessOpen({ datasetId, open: true }));
    const closeProcess = () => dispatch(agentRunActions.setProcessOpen({ datasetId, open: false }));

    if (!resource || resource.status === 'loading') {
        return (
            <Stack spacing={1.5}>
                <LinearProgress />
                <Typography variant="body2" color="text.secondary">
                    {t('insight.run.loading')}
                </Typography>
            </Stack>
        );
    }

    return (
        <Stack spacing={2}>
            <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={1}
                justifyContent="space-between"
                alignItems={{ xs: 'flex-start', sm: 'center' }}
            >
                <Box>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>
                        {t('insight.run.title')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {t('insight.run.subtitle', { datasetId, versionId })}
                    </Typography>
                </Box>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    {run ? (
                        <Chip
                            color={statusColor(run.status)}
                            label={t(`insight.run.status.${run.status}`)}
                        />
                    ) : null}
                    <Button size="small" startIcon={<RefreshIcon />} onClick={handleRefresh}>
                        {t('insight.run.refresh')}
                    </Button>
                    {run && shouldStream ? (
                        <Button size="small" color="warning" startIcon={<CancelOutlinedIcon />} onClick={handleCancel}>
                            {t('insight.run.cancel')}
                        </Button>
                    ) : (
                        <Button
                            size="small"
                            variant="contained"
                            startIcon={resource.status === 'starting' ? <CircularProgress size={15} /> : <PlayArrowIcon />}
                            disabled={resource.status === 'starting' || run?.status === 'waiting_approval'}
                            onClick={handleStart}
                        >
                            {run ? t('insight.run.startNew') : t('insight.run.start')}
                        </Button>
                    )}
                </Stack>
            </Stack>

            {resource.error ? (
                <Alert severity="error" variant="outlined">
                    {resource.error.message}
                </Alert>
            ) : null}

            {!run ? (
                <Card variant="outlined">
                    <CardContent>
                        <Stack spacing={1.5} alignItems="flex-start">
                            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                                {t('insight.run.emptyTitle')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('insight.run.emptyBody')}
                            </Typography>
                            <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={handleStart}>
                                {t('insight.run.start')}
                            </Button>
                        </Stack>
                    </CardContent>
                </Card>
            ) : run.status === 'completed' ? (
                <FinalConclusionView
                    run={run}
                    summary={finalSummary}
                    t={t}
                    onOpenProcess={openProcess}
                />
            ) : (
                <Stack spacing={1.5}>
                    {shouldStream ? <LinearProgress /> : null}
                    {currentStep ? (
                        <Alert
                            severity={run.status === 'failed' ? 'error' : run.status === 'cancelled' ? 'warning' : 'info'}
                            variant="outlined"
                        >
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {currentStep.title}
                            </Typography>
                            <Typography variant="caption">
                                {currentStep.progress_text}
                            </Typography>
                        </Alert>
                    ) : null}
                    {run.status === 'waiting_approval' ? (
                        <Alert
                            severity="warning"
                            variant="outlined"
                            action={(
                                <Button color="inherit" size="small" startIcon={<CleaningServicesOutlinedIcon />} onClick={onOpenCleaning}>
                                    {t('insight.run.openCleaning')}
                                </Button>
                            )}
                        >
                            {t('insight.run.waitingApproval')}
                        </Alert>
                    ) : null}
                    <Box>
                        {steps.map((step) => <AgentProgressCard key={step.id} step={step} t={t} />)}
                    </Box>
                    {steps.length ? (
                        <Button startIcon={<HistoryOutlinedIcon />} onClick={openProcess} sx={{ alignSelf: 'flex-start' }}>
                            {t('insight.run.viewFullProcess')}
                        </Button>
                    ) : null}
                </Stack>
            )}

            <ProcessDrawer
                open={resource.processOpen}
                run={run}
                steps={steps}
                t={t}
                onClose={closeProcess}
            />
        </Stack>
    );
}
