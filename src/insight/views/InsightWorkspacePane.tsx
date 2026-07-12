import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
    Alert,
    Box,
    Button,
    Chip,
    LinearProgress,
    Stack,
    Tab,
    Tabs,
    Typography,
} from '@mui/material';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { dfSelectors, type DataFormulatorState } from '../../app/dfSlice';
import type { AppDispatch, RootState } from '../../app/store';
import type { DictTable } from '../../components/ComponentType';
import { ProfileColumnsTable } from '../components/ProfileColumnsTable';
import { ProfileIssueList } from '../components/ProfileIssueList';
import { ProfileOverviewCards } from '../components/ProfileOverviewCards';
import { VersionedCleaningWorkspacePanel } from '../components/VersionedCleaningWorkspacePanel';
import {
    loadProfileForTable,
    makeProfilingRequestKey,
    selectProfilingResource,
    type ProfilingStatus,
} from '../store/profilingSlice';

type InsightTab = 'analysis' | 'profiling' | 'cleaning';

const statusMessageKey: Record<Exclude<ProfilingStatus, 'ready' | 'error' | 'idle'>, string> = {
    registering: 'insight.profile.loading.registering',
    loading: 'insight.profile.loading.loading',
    profiling: 'insight.profile.loading.profiling',
};

function resolveDatasetName(table: DictTable): string {
    return table.source?.originalTableName?.trim() || table.displayId || table.id;
}

function resolveActiveTable(state: RootState): DictTable | undefined {
    const effectiveTableId = dfSelectors.getEffectiveTableId(state as DataFormulatorState);
    return effectiveTableId ? state.tables.find((table) => table.id === effectiveTableId) : undefined;
}

function StatusBanner({
    status,
    t,
}: {
    status: Exclude<ProfilingStatus, 'ready' | 'error' | 'idle'>;
    t: TFunction;
}) {
    return (
        <Box>
            <LinearProgress />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                {t(statusMessageKey[status])}
            </Typography>
        </Box>
    );
}

function EmptyProfileState({ t }: { t: TFunction }) {
    return (
        <Stack spacing={1}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('insight.profile.emptyTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
                {t('insight.profile.emptyBody')}
            </Typography>
        </Stack>
    );
}

function MissingTableState({ t }: { t: TFunction }) {
    return (
        <Stack spacing={1}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('insight.profile.selectTableTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
                {t('insight.profile.selectTableBody')}
            </Typography>
        </Stack>
    );
}

export interface InsightWorkspacePaneProps {
    analysisView: React.ReactNode;
}

export function InsightWorkspacePane({ analysisView }: InsightWorkspacePaneProps) {
    const dispatch = useDispatch<AppDispatch>();
    const { t } = useTranslation();
    const [activeTab, setActiveTab] = useState<InsightTab>('analysis');

    const activeWorkspace = useSelector((state: RootState) => state.activeWorkspace);
    const activeTable = useSelector(resolveActiveTable);

    const requestKey = useMemo(() => {
        if (!activeWorkspace?.id || !activeTable?.id) {
            return undefined;
        }
        return makeProfilingRequestKey(activeWorkspace.id, activeTable.id);
    }, [activeTable?.id, activeWorkspace?.id]);

    const resource = useSelector((state: RootState) => selectProfilingResource(state, requestKey));
    const currentRequestRef = useRef<{ abort?: () => void } | null>(null);

    const requestProfile = React.useCallback(() => {
        if (!activeWorkspace?.id || !activeTable) {
            return null;
        }

        currentRequestRef.current?.abort?.();
        const promise = dispatch(
            loadProfileForTable({
                workspaceId: activeWorkspace.id,
                tableId: activeTable.id,
                tableName: activeTable.virtual.tableId,
                datasetName: resolveDatasetName(activeTable),
            }),
        );
        currentRequestRef.current = promise;
        return promise;
    }, [activeTable, activeWorkspace?.id, dispatch]);

    useEffect(() => {
        const needsDataset = activeTab === 'profiling' || activeTab === 'cleaning';
        if (!needsDataset || !activeWorkspace?.id || !activeTable || !requestKey) {
            return;
        }
        if (resource?.status && ['registering', 'loading', 'profiling', 'ready', 'error'].includes(resource.status)) {
            return;
        }
        void requestProfile();
    }, [activeTab, activeTable, activeWorkspace?.id, requestKey, requestProfile, resource?.status]);

    useEffect(() => {
        if (activeTab === 'analysis') {
            currentRequestRef.current?.abort?.();
        }
    }, [activeTab]);

    useEffect(() => () => currentRequestRef.current?.abort?.(), []);

    const renderSharedDatasetState = (): React.ReactNode | null => {
        if (!activeTable || !activeWorkspace?.id) return <MissingTableState t={t} />;
        if (!resource || resource.status === 'idle') return <EmptyProfileState t={t} />;
        if (resource.status === 'registering' || resource.status === 'loading' || resource.status === 'profiling') {
            return <StatusBanner status={resource.status} t={t} />;
        }
        if (resource.status === 'error') {
            return (
                <Stack spacing={1.5}>
                    <Alert severity="error" variant="outlined">
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {resource.error?.message || t('insight.profile.errorGeneric')}
                        </Typography>
                        {resource.error?.code ? (
                            <Typography variant="caption" sx={{ display: 'block', mt: 0.75 }}>
                                {t('insight.profile.errorCode', { code: resource.error.code })}
                            </Typography>
                        ) : null}
                    </Alert>
                    <Box>
                        <Button variant="contained" onClick={() => { void requestProfile(); }}>
                            {t('insight.profile.retry')}
                        </Button>
                    </Box>
                </Stack>
            );
        }
        if (!resource.profile || !resource.datasetId) return <EmptyProfileState t={t} />;
        return null;
    };

    const renderProfilingContent = () => {
        const sharedState = renderSharedDatasetState();
        if (sharedState) return sharedState;
        if (!resource?.profile || !resource.datasetId || !activeTable) return <EmptyProfileState t={t} />;

        return (
            <Stack spacing={2}>
                <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={1}
                    justifyContent="space-between"
                    alignItems={{ xs: 'flex-start', sm: 'center' }}
                >
                    <Box>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>
                            {t('insight.profile.title', { tableName: resolveDatasetName(activeTable) })}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            {t('insight.profile.subtitle', { datasetId: resource.datasetId })}
                        </Typography>
                    </Box>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        <Chip
                            size="small"
                            label={t('insight.profile.versionLabel', { versionId: resource.profile.version_id })}
                        />
                        <Button variant="outlined" size="small" onClick={() => { void requestProfile(); }}>
                            {t('insight.profile.refresh')}
                        </Button>
                    </Stack>
                </Stack>
                <ProfileOverviewCards profile={resource.profile} t={t} />
                <ProfileIssueList profile={resource.profile} t={t} />
                <ProfileColumnsTable profile={resource.profile} t={t} />
            </Stack>
        );
    };

    const renderCleaningContent = () => {
        const sharedState = renderSharedDatasetState();
        if (sharedState) return sharedState;
        if (!resource?.datasetId || !resource.profile) return <EmptyProfileState t={t} />;
        return <VersionedCleaningWorkspacePanel datasetId={resource.datasetId} />;
    };

    return (
        <Box sx={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 1.5, pt: 1 }}>
                <Tabs
                    value={activeTab}
                    onChange={(_, value: InsightTab) => setActiveTab(value)}
                    aria-label={t('insight.tabs.ariaLabel')}
                >
                    <Tab value="analysis" label={t('insight.tabs.analysis')} />
                    <Tab value="profiling" label={t('insight.tabs.profiling')} />
                    <Tab value="cleaning" label={t('insight.tabs.cleaning')} />
                </Tabs>
            </Box>
            <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                {activeTab === 'analysis' ? (
                    <Box sx={{ width: '100%', height: '100%' }}>{analysisView}</Box>
                ) : (
                    <Box sx={{ height: '100%', overflow: 'auto', px: 2, py: 2 }}>
                        {activeTab === 'profiling' ? renderProfilingContent() : renderCleaningContent()}
                    </Box>
                )}
            </Box>
        </Box>
    );
}
