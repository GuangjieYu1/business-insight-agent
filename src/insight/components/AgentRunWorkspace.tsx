import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
    Alert,
    Box,
    Button,
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
import type { SaveGoalParams } from '../api/goalClient';
import {
    agentRunActions,
    cancelObservableAgentRun,
    refreshAgentRun,
    restoreLatestAgentRun,
    selectAgentRunResource,
    startObservableAgentRun,
} from '../store/agentRunSlice';
import {
    createGoalIntent,
    makeGoalResourceKey,
    restoreGoalForDatasetVersion,
    saveAnalysisGoal,
    selectGoalResource,
} from '../store/goalSlice';
import type { AgentRunStatus, DatasetProfile } from '../types';
import { AgentProgressCard } from './AgentProgressCard';
import { FinalConclusionView } from './FinalConclusionView';
import { GoalConfirmationPanel } from './GoalConfirmationPanel';
import { GoalSummaryCard } from './GoalSummaryCard';
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

type GoalPanelMode = 'hidden' | 'intent' | 'custom';

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
    profile: DatasetProfile;
    onOpenCleaning: () => void;
}

export function AgentRunWorkspace({ datasetId, versionId, profile, onOpenCleaning }: AgentRunWorkspaceProps) {
    const dispatch = useDispatch<AppDispatch>();
    const { t } = useTranslation();
    const resource = useSelector((state: RootState) => selectAgentRunResource(state, datasetId));
    const goalResourceKey = useMemo(() => makeGoalResourceKey(datasetId, versionId), [datasetId, versionId]);
    const goalResource = useSelector((state: RootState) => selectGoalResource(state, goalResourceKey));
    const [goalPanelMode, setGoalPanelMode] = useState<GoalPanelMode>('hidden');
    const [reconnectToken, setReconnectToken] = useState(0);
    const lastEventIdRef = useRef<string | null>(null);
    const refreshTimerRef = useRef<number | null>(null);

    const run = resource?.run ?? null;
    const steps = resource?.steps ?? [];
    const finalSummary = resource?.finalSummary ?? null;
    const activeGoal = goalResource?.activeGoal ?? null;
    const shouldStream = Boolean(run && ACTIVE_RUN_STATUSES.has(run.status));
    const hasBlockingRun = Boolean(run && run.status !== 'completed' && run.status !== 'failed' && run.status !== 'cancelled');
    const showGoalPanel = goalPanelMode !== 'hidden' || !activeGoal;
    const canStartNewRun = Boolean(activeGoal) && goalPanelMode === 'hidden' && resource?.status !== 'starting' && goalResource?.status !== 'confirming' && !hasBlockingRun;

    useEffect(() => {
        setGoalPanelMode('hidden');
    }, [datasetId, versionId]);

    useEffect(() => {
        lastEventIdRef.current = resource?.lastEventId ?? null;
    }, [resource?.lastEventId]);

    useEffect(() => {
        if (!resource || resource.status === 'idle') {
            void dispatch(restoreLatestAgentRun({ datasetId }));
        }
    }, [datasetId, dispatch, resource?.status]);

    useEffect(() => {
        if (!goalResource || goalResource.status === 'idle') {
            void dispatch(restoreGoalForDatasetVersion({ datasetId, versionId }));
        }
    }, [datasetId, dispatch, goalResource?.status, versionId]);

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
        if (!activeGoal) return;
        void dispatch(startObservableAgentRun({ datasetId, versionId, goalId: activeGoal.id }));
    };

    const handleRefresh = () => {
        if (run) void dispatch(refreshAgentRun({ datasetId, runId: run.id }));
        else void dispatch(restoreLatestAgentRun({ datasetId }));
        void dispatch(restoreGoalForDatasetVersion({ datasetId, versionId }));
    };

    const handleCancel = () => {
        if (!run) return;
        void dispatch(cancelObservableAgentRun({
            datasetId,
            runId: run.id,
            reason: t('insight.run.cancelReason'),
        }));
    };

    const handleGenerateIntent = (userInput: string) => {
        void dispatch(createGoalIntent({
            datasetId,
            datasetVersionId: versionId,
            userInput,
        }));
    };

    const handleConfirmGoal = async (request: SaveGoalParams) => {
        const result = await dispatch(saveAnalysisGoal(request));
        if (saveAnalysisGoal.fulfilled.match(result)) {
            setGoalPanelMode('hidden');
        }
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
                    ) : null}
                </Stack>
            </Stack>

            {resource.error ? (
                <Alert severity="error" variant="outlined">
                    {resource.error.message}
                </Alert>
            ) : null}

            {goalResource?.status === 'loading' && !activeGoal ? (
                <Stack spacing={1}>
                    <LinearProgress />
                    <Typography variant="body2" color="text.secondary">
                        {t('insight.goal.loading')}
                    </Typography>
                </Stack>
            ) : null}

            {activeGoal && goalPanelMode === 'hidden' ? (
                <GoalSummaryCard
                    goal={activeGoal}
                    versionId={versionId}
                    startDisabled={!canStartNewRun}
                    starting={resource.status === 'starting'}
                    t={t}
                    onStart={handleStart}
                    onChangeGoal={() => setGoalPanelMode('intent')}
                    onNewCustomGoal={() => setGoalPanelMode('custom')}
                />
            ) : null}

            {showGoalPanel ? (
                <GoalConfirmationPanel
                    datasetId={datasetId}
                    versionId={versionId}
                    columns={profile.columns}
                    status={goalResource?.status ?? 'loading'}
                    error={goalResource?.error ?? null}
                    activeGoal={activeGoal}
                    intent={goalResource?.intent ?? null}
                    goalCandidates={goalResource?.goalCandidates ?? []}
                    questions={goalResource?.questions ?? []}
                    mode={goalPanelMode === 'custom' ? 'custom' : 'intent'}
                    t={t}
                    onGenerateIntent={handleGenerateIntent}
                    onConfirmGoal={handleConfirmGoal}
                    onCancel={activeGoal ? () => setGoalPanelMode('hidden') : undefined}
                />
            ) : null}

            {!run ? null : run.status === 'completed' ? (
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

            {resource.processOpen ? (
                <ProcessDrawer
                    open
                    run={run}
                    steps={steps}
                    t={t}
                    onClose={closeProcess}
                />
            ) : null}
        </Stack>
    );
}