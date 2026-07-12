import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    FormControl,
    InputLabel,
    LinearProgress,
    MenuItem,
    Select,
    Stack,
    Typography,
} from '@mui/material';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import {
    compareDatasetProfiles,
    INSIGHT_DATASET_HISTORY_CHANGED,
    listDatasetOperations,
    listDatasetVersions,
    toInsightError,
    undoCleaningOperation,
    type ProfileComparisonResponse,
} from '../api/insightClient';
import type {
    CleaningOperation,
    DatasetVersion,
    InsightError,
    ProfileQualityIssue,
} from '../types';
import { CleaningWorkspacePanel } from './CleaningWorkspacePanel';

const CLEANING_OPERATION_TYPES = new Set([
    'trim_string',
    'replace_invalid_character',
    'drop_duplicate_rows',
    'rename_column',
    'drop_column',
]);

const comparisonMetricKeys = [
    'row_count',
    'column_count',
    'duplicate_excess_row_count',
    'quality_issue_count',
    'high_issue_count',
    'medium_issue_count',
] as const;

function issueLabel(issue: ProfileQualityIssue, t: TFunction): string {
    const column = typeof issue.scope.column === 'string' ? ` · ${issue.scope.column}` : '';
    return `${t(`insight.issueTypes.${issue.issue_type}`, { defaultValue: issue.issue_type })}${column}`;
}

export interface VersionedCleaningWorkspacePanelProps {
    datasetId: string;
}

export function VersionedCleaningWorkspacePanel({
    datasetId,
}: VersionedCleaningWorkspacePanelProps) {
    const { t } = useTranslation();
    const [versions, setVersions] = useState<DatasetVersion[]>([]);
    const [operations, setOperations] = useState<CleaningOperation[]>([]);
    const [activeVersionId, setActiveVersionId] = useState('version_000');
    const [selectedVersionId, setSelectedVersionId] = useState('version_000');
    const [comparison, setComparison] = useState<ProfileComparisonResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [comparisonLoading, setComparisonLoading] = useState(false);
    const [undoing, setUndoing] = useState(false);
    const [error, setError] = useState<InsightError | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const loadContext = useCallback(async (signal?: AbortSignal, followActive = false) => {
        setLoading(true);
        setError(null);
        try {
            const [versionResponse, operationResponse] = await Promise.all([
                listDatasetVersions(datasetId, signal),
                listDatasetOperations(datasetId, signal),
            ]);
            setVersions(versionResponse.versions);
            setOperations(operationResponse);
            setActiveVersionId(versionResponse.activeVersionId);
            setSelectedVersionId((current) => {
                if (followActive || !versionResponse.versions.some((item) => item.id === current)) {
                    return versionResponse.activeVersionId;
                }
                return current;
            });
        } catch (caught) {
            if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
                setError(toInsightError(caught));
            }
        } finally {
            if (!signal?.aborted) setLoading(false);
        }
    }, [datasetId]);

    useEffect(() => {
        const controller = new AbortController();
        setSelectedVersionId('version_000');
        setNotice(null);
        void loadContext(controller.signal, true);
        return () => controller.abort();
    }, [loadContext]);

    useEffect(() => {
        const listener = (event: Event) => {
            const detail = (event as CustomEvent<{ datasetId?: string }>).detail;
            if (!detail?.datasetId || detail.datasetId === datasetId) {
                void loadContext(undefined, true);
            }
        };
        window.addEventListener(INSIGHT_DATASET_HISTORY_CHANGED, listener);
        return () => window.removeEventListener(INSIGHT_DATASET_HISTORY_CHANGED, listener);
    }, [datasetId, loadContext]);

    const selectedVersion = useMemo(
        () => versions.find((version) => version.id === selectedVersionId),
        [selectedVersionId, versions],
    );

    useEffect(() => {
        const parentVersionId = selectedVersion?.parent_version_id;
        if (!parentVersionId) {
            setComparison(null);
            return;
        }
        const controller = new AbortController();
        setComparisonLoading(true);
        setError(null);
        compareDatasetProfiles(datasetId, parentVersionId, selectedVersion.id, controller.signal)
            .then(setComparison)
            .catch((caught) => {
                if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
                    setError(toInsightError(caught));
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) setComparisonLoading(false);
            });
        return () => controller.abort();
    }, [datasetId, selectedVersion]);

    const latestUndoableOperation = useMemo(() => [...operations].reverse().find((operation) => (
        operation.status === 'completed'
        && operation.reversible
        && operation.output_version_id === activeVersionId
        && CLEANING_OPERATION_TYPES.has(operation.operation_type)
    )) ?? null, [activeVersionId, operations]);

    const undoLatest = useCallback(async () => {
        if (!latestUndoableOperation) return;
        setUndoing(true);
        setError(null);
        setNotice(null);
        try {
            const result = await undoCleaningOperation(latestUndoableOperation.id);
            setNotice(t('insight.cleaning.notice.undone', { versionId: result.activeVersion.id }));
        } catch (caught) {
            setError(toInsightError(caught));
        } finally {
            setUndoing(false);
        }
    }, [latestUndoableOperation, t]);

    if (loading) {
        return (
            <Stack spacing={1}>
                <LinearProgress />
                <Typography variant="body2" color="text.secondary">
                    {t('insight.versionContext.loading')}
                </Typography>
            </Stack>
        );
    }

    const isHistorical = selectedVersionId !== activeVersionId;

    return (
        <Stack spacing={2}>
            <Card variant="outlined">
                <CardContent>
                    <Stack spacing={1.5}>
                        <Stack
                            direction={{ xs: 'column', sm: 'row' }}
                            spacing={1}
                            justifyContent="space-between"
                            alignItems={{ sm: 'center' }}
                        >
                            <Box>
                                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                    {t('insight.versionContext.title')}
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                    {t('insight.versionContext.subtitle')}
                                </Typography>
                            </Box>
                            <Stack direction="row" spacing={1} alignItems="center">
                                <FormControl size="small" sx={{ minWidth: 180 }}>
                                    <InputLabel>{t('insight.versionContext.select')}</InputLabel>
                                    <Select
                                        value={selectedVersionId}
                                        label={t('insight.versionContext.select')}
                                        onChange={(event) => setSelectedVersionId(event.target.value)}
                                    >
                                        {versions.map((version) => (
                                            <MenuItem key={version.id} value={version.id}>
                                                {version.id} · {version.row_count} × {version.column_count}
                                            </MenuItem>
                                        ))}
                                    </Select>
                                </FormControl>
                                <Chip
                                    size="small"
                                    color="primary"
                                    label={t('insight.cleaning.versions.active', { versionId: activeVersionId })}
                                />
                                <Button size="small" variant="outlined" onClick={() => { void loadContext(undefined, false); }}>
                                    {t('insight.cleaning.refresh')}
                                </Button>
                            </Stack>
                        </Stack>

                        {latestUndoableOperation ? (
                            <Box>
                                <Button
                                    size="small"
                                    variant="outlined"
                                    color="warning"
                                    disabled={undoing}
                                    onClick={() => { void undoLatest(); }}
                                >
                                    {undoing ? t('insight.cleaning.undoing') : t('insight.versionContext.undoPersistent')}
                                </Button>
                            </Box>
                        ) : null}
                    </Stack>
                </CardContent>
            </Card>

            {error ? <Alert severity="error">{error.message}</Alert> : null}
            {notice ? <Alert severity="success">{notice}</Alert> : null}

            {comparisonLoading ? <LinearProgress /> : null}
            {comparison ? (
                <Card variant="outlined">
                    <CardContent>
                        <Stack spacing={1.5}>
                            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                {t('insight.versionComparison.title', {
                                    before: comparison.beforeVersionId,
                                    after: comparison.afterVersionId,
                                })}
                            </Typography>
                            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                {comparisonMetricKeys.map((key) => (
                                    <Chip
                                        key={key}
                                        size="small"
                                        variant="outlined"
                                        label={t('insight.versionComparison.metric', {
                                            metric: t(`insight.versionComparison.metrics.${key}`),
                                            before: comparison.beforeMetrics[key],
                                            after: comparison.afterMetrics[key],
                                            delta: comparison.metricDelta[key] >= 0
                                                ? `+${comparison.metricDelta[key]}`
                                                : comparison.metricDelta[key],
                                        })}
                                    />
                                ))}
                            </Stack>
                            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                                <Box sx={{ flex: 1 }}>
                                    <Typography variant="subtitle2" color="success.main">
                                        {t('insight.versionComparison.resolved', { count: comparison.resolvedIssues.length })}
                                    </Typography>
                                    <Stack spacing={0.5} sx={{ mt: 0.75 }}>
                                        {comparison.resolvedIssues.map((issue, index) => (
                                            <Typography key={`${issue.issue_type}-${index}`} variant="body2">
                                                {issueLabel(issue, t)}
                                            </Typography>
                                        ))}
                                    </Stack>
                                </Box>
                                <Box sx={{ flex: 1 }}>
                                    <Typography variant="subtitle2" color="error.main">
                                        {t('insight.versionComparison.introduced', { count: comparison.introducedIssues.length })}
                                    </Typography>
                                    <Stack spacing={0.5} sx={{ mt: 0.75 }}>
                                        {comparison.introducedIssues.map((issue, index) => (
                                            <Typography key={`${issue.issue_type}-${index}`} variant="body2">
                                                {issueLabel(issue, t)}
                                            </Typography>
                                        ))}
                                    </Stack>
                                </Box>
                                <Box sx={{ flex: 1 }}>
                                    <Typography variant="subtitle2" color="text.secondary">
                                        {t('insight.versionComparison.unchanged', { count: comparison.unchangedIssues.length })}
                                    </Typography>
                                </Box>
                            </Stack>
                        </Stack>
                    </CardContent>
                </Card>
            ) : null}

            {isHistorical ? (
                <Alert severity="info">
                    {t('insight.versionContext.historicalReadOnly', {
                        selected: selectedVersionId,
                        active: activeVersionId,
                    })}
                </Alert>
            ) : (
                <CleaningWorkspacePanel
                    key={`${datasetId}:${selectedVersionId}`}
                    datasetId={datasetId}
                    versionId={selectedVersionId}
                />
            )}
        </Stack>
    );
}

export default VersionedCleaningWorkspacePanel;
