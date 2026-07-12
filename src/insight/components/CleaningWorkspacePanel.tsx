import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Divider,
    FormControl,
    InputLabel,
    LinearProgress,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { useTranslation } from 'react-i18next';

import {
    applyCleaningProposal,
    approveCleaningProposal,
    generateCleaningProposals,
    listCleaningProposals,
    listDatasetVersions,
    previewCleaningProposal,
    rejectCleaningProposal,
    toInsightError,
    undoCleaningOperation,
} from '../api/insightClient';
import type {
    CleaningApplyResponse,
    CleaningOperation,
    CleaningPreviewResponse,
    CleaningProposal,
    DatasetVersion,
    InsightError,
    SupportedCleaningOperation,
} from '../types';

const SUPPORTED_OPERATIONS = new Set<SupportedCleaningOperation>([
    'trim_string',
    'replace_invalid_character',
    'drop_duplicate_rows',
    'rename_column',
    'drop_column',
]);

const severityColor = (severity: CleaningProposal['severity']) => {
    if (severity === 'critical' || severity === 'high') return 'error' as const;
    if (severity === 'medium') return 'warning' as const;
    if (severity === 'low') return 'info' as const;
    return 'default' as const;
};

const statusColor = (status: CleaningProposal['status']) => {
    if (status === 'applied') return 'success' as const;
    if (status === 'approved') return 'primary' as const;
    if (status === 'rejected') return 'default' as const;
    return 'warning' as const;
};

const metricKeys = [
    'row_count',
    'column_count',
    'null_cell_count',
    'duplicate_excess_row_count',
] as const;

function supportedChoices(proposal: CleaningProposal): SupportedCleaningOperation[] {
    return [proposal.recommended_operation, ...proposal.alternatives]
        .filter((operation, index, all) => all.indexOf(operation) === index)
        .filter((operation): operation is SupportedCleaningOperation =>
            SUPPORTED_OPERATIONS.has(operation as SupportedCleaningOperation));
}

function formatScope(proposal: CleaningProposal): string {
    const column = proposal.scope.column;
    if (typeof column === 'string') return column;
    return String(proposal.scope.dataset_id ?? proposal.dataset_version_id);
}

export interface CleaningWorkspacePanelProps {
    datasetId: string;
    versionId?: string;
}

export function CleaningWorkspacePanel({
    datasetId,
    versionId = 'version_000',
}: CleaningWorkspacePanelProps) {
    const { t } = useTranslation();
    const [proposals, setProposals] = useState<CleaningProposal[]>([]);
    const [versions, setVersions] = useState<DatasetVersion[]>([]);
    const [activeVersionId, setActiveVersionId] = useState(versionId);
    const [previews, setPreviews] = useState<Record<string, CleaningPreviewResponse>>({});
    const [selectedOperations, setSelectedOperations] = useState<Record<string, string>>({});
    const [renameValues, setRenameValues] = useState<Record<string, string>>({});
    const [latestOperation, setLatestOperation] = useState<CleaningOperation | null>(null);
    const [loading, setLoading] = useState(false);
    const [busyProposalId, setBusyProposalId] = useState<string | null>(null);
    const [undoing, setUndoing] = useState(false);
    const [error, setError] = useState<InsightError | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const updateProposal = useCallback((updated: CleaningProposal) => {
        setProposals((current) => current.map((item) => item.id === updated.id ? updated : item));
    }, []);

    const refreshVersions = useCallback(async (signal?: AbortSignal) => {
        const response = await listDatasetVersions(datasetId, signal);
        setVersions(response.versions);
        setActiveVersionId(response.activeVersionId);
    }, [datasetId]);

    const loadWorkspace = useCallback(async (signal?: AbortSignal) => {
        setLoading(true);
        setError(null);
        try {
            let current = await listCleaningProposals(datasetId, versionId, signal);
            if (current.length === 0) {
                current = await generateCleaningProposals(datasetId, versionId, signal);
            }
            setProposals(current);
            setSelectedOperations((previous) => {
                const next = { ...previous };
                for (const proposal of current) {
                    const choices = supportedChoices(proposal);
                    if (!next[proposal.id] && choices.length > 0) {
                        next[proposal.id] = choices.includes(proposal.recommended_operation as SupportedCleaningOperation)
                            ? proposal.recommended_operation
                            : choices[0];
                    }
                }
                return next;
            });
            setRenameValues((previous) => {
                const next = { ...previous };
                for (const proposal of current) {
                    const suggested = proposal.evidence.suggested_name;
                    if (!next[proposal.id] && typeof suggested === 'string') {
                        next[proposal.id] = suggested;
                    }
                }
                return next;
            });
            await refreshVersions(signal);
        } catch (caught) {
            if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
                setError(toInsightError(caught));
            }
        } finally {
            if (!signal?.aborted) setLoading(false);
        }
    }, [datasetId, refreshVersions, versionId]);

    useEffect(() => {
        const controller = new AbortController();
        setProposals([]);
        setPreviews({});
        setLatestOperation(null);
        setNotice(null);
        void loadWorkspace(controller.signal);
        return () => controller.abort();
    }, [loadWorkspace]);

    const requestFor = useCallback((proposal: CleaningProposal) => {
        const operationType = selectedOperations[proposal.id] || proposal.recommended_operation;
        const parameters: Record<string, unknown> = {};
        if (operationType === 'rename_column') {
            parameters.new_name = renameValues[proposal.id] || proposal.evidence.suggested_name || '';
        }
        return { operationType, parameters };
    }, [renameValues, selectedOperations]);

    const runProposalAction = useCallback(async (
        proposal: CleaningProposal,
        action: 'preview' | 'approve' | 'reject' | 'apply',
    ) => {
        setBusyProposalId(proposal.id);
        setError(null);
        setNotice(null);
        try {
            if (action === 'preview') {
                const preview = await previewCleaningProposal(proposal.id, requestFor(proposal));
                setPreviews((current) => ({ ...current, [proposal.id]: preview }));
                return;
            }
            if (action === 'approve') {
                updateProposal(await approveCleaningProposal(proposal.id));
                setNotice(t('insight.cleaning.notice.approved'));
                return;
            }
            if (action === 'reject') {
                updateProposal(await rejectCleaningProposal(proposal.id));
                setNotice(t('insight.cleaning.notice.rejected'));
                return;
            }

            const applied: CleaningApplyResponse = await applyCleaningProposal(
                proposal.id,
                requestFor(proposal),
            );
            updateProposal(applied.proposal);
            setLatestOperation(applied.operation);
            setNotice(t(applied.idempotent
                ? 'insight.cleaning.notice.alreadyApplied'
                : 'insight.cleaning.notice.applied', {
                versionId: applied.version.id,
            }));
            await refreshVersions();
        } catch (caught) {
            setError(toInsightError(caught));
        } finally {
            setBusyProposalId(null);
        }
    }, [refreshVersions, requestFor, t, updateProposal]);

    const undoLatest = useCallback(async () => {
        if (!latestOperation) return;
        setUndoing(true);
        setError(null);
        setNotice(null);
        try {
            const result = await undoCleaningOperation(latestOperation.id);
            setActiveVersionId(result.activeVersion.id);
            setVersions((current) => current.map((version) => {
                if (version.id === result.activeVersion.id) return result.activeVersion;
                if (result.previousVersion && version.id === result.previousVersion.id) return result.previousVersion;
                return version;
            }));
            setLatestOperation(null);
            setNotice(t('insight.cleaning.notice.undone', { versionId: result.activeVersion.id }));
        } catch (caught) {
            setError(toInsightError(caught));
        } finally {
            setUndoing(false);
        }
    }, [latestOperation, t]);

    const sortedProposals = useMemo(() => [...proposals].sort((left, right) => {
        const order = { pending: 0, approved: 1, applied: 2, rejected: 3 };
        return order[left.status] - order[right.status] || left.problem_type.localeCompare(right.problem_type);
    }), [proposals]);

    if (loading) {
        return (
            <Stack spacing={1}>
                <LinearProgress />
                <Typography variant="body2" color="text.secondary">
                    {t('insight.cleaning.loading')}
                </Typography>
            </Stack>
        );
    }

    return (
        <Stack spacing={2}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between">
                <Box>
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        {t('insight.cleaning.title')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                        {t('insight.cleaning.subtitle', { datasetId, versionId })}
                    </Typography>
                </Box>
                <Button variant="outlined" size="small" onClick={() => { void loadWorkspace(); }}>
                    {t('insight.cleaning.refresh')}
                </Button>
            </Stack>

            {error ? <Alert severity="error">{error.message}</Alert> : null}
            {notice ? <Alert severity="success">{notice}</Alert> : null}

            <Card variant="outlined">
                <CardContent>
                    <Stack spacing={1}>
                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                {t('insight.cleaning.versions.title')}
                            </Typography>
                            <Chip
                                size="small"
                                color="primary"
                                label={t('insight.cleaning.versions.active', { versionId: activeVersionId })}
                            />
                        </Stack>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                            {versions.map((version) => (
                                <Chip
                                    key={version.id}
                                    size="small"
                                    variant={version.id === activeVersionId ? 'filled' : 'outlined'}
                                    color={version.status === 'invalid' ? 'error' : version.id === activeVersionId ? 'primary' : 'default'}
                                    label={`${version.id} · ${version.row_count} × ${version.column_count}`}
                                />
                            ))}
                        </Stack>
                        {latestOperation?.status === 'completed' ? (
                            <Box>
                                <Button
                                    color="warning"
                                    variant="outlined"
                                    size="small"
                                    disabled={undoing}
                                    onClick={() => { void undoLatest(); }}
                                >
                                    {undoing ? t('insight.cleaning.undoing') : t('insight.cleaning.undo')}
                                </Button>
                            </Box>
                        ) : null}
                    </Stack>
                </CardContent>
            </Card>

            <Alert severity="info" variant="outlined">
                {t('insight.cleaning.privacyNotice')}
            </Alert>

            {sortedProposals.length === 0 ? (
                <Alert severity="success">{t('insight.cleaning.empty')}</Alert>
            ) : sortedProposals.map((proposal) => {
                const choices = supportedChoices(proposal);
                const selected = selectedOperations[proposal.id] || '';
                const preview = previews[proposal.id];
                const busy = busyProposalId === proposal.id;
                const supported = choices.length > 0;
                return (
                    <Card key={proposal.id} variant="outlined">
                        <CardContent>
                            <Stack spacing={1.5}>
                                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between">
                                    <Box>
                                        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                            {t(`insight.issueTypes.${proposal.problem_type}`, { defaultValue: proposal.problem_type })}
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary">
                                            {t('insight.cleaning.scope', { scope: formatScope(proposal) })}
                                        </Typography>
                                    </Box>
                                    <Stack direction="row" spacing={0.75}>
                                        <Chip size="small" color={severityColor(proposal.severity)} label={t(`insight.severity.label.${proposal.severity}`)} />
                                        <Chip size="small" color={statusColor(proposal.status)} label={t(`insight.cleaning.status.${proposal.status}`)} />
                                        <Chip size="small" variant="outlined" label={`${Math.round(proposal.confidence * 100)}%`} />
                                    </Stack>
                                </Stack>

                                {supported ? (
                                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
                                        <FormControl size="small" sx={{ minWidth: 220 }}>
                                            <InputLabel>{t('insight.cleaning.operation')}</InputLabel>
                                            <Select
                                                value={selected}
                                                label={t('insight.cleaning.operation')}
                                                onChange={(event) => setSelectedOperations((current) => ({
                                                    ...current,
                                                    [proposal.id]: event.target.value,
                                                }))}
                                                disabled={proposal.status === 'applied' || proposal.status === 'rejected'}
                                            >
                                                {choices.map((operation) => (
                                                    <MenuItem key={operation} value={operation}>
                                                        {t(`insight.cleaning.operations.${operation}`)}
                                                    </MenuItem>
                                                ))}
                                            </Select>
                                        </FormControl>
                                        {selected === 'rename_column' ? (
                                            <TextField
                                                size="small"
                                                label={t('insight.cleaning.newColumnName')}
                                                value={renameValues[proposal.id] || ''}
                                                onChange={(event) => setRenameValues((current) => ({
                                                    ...current,
                                                    [proposal.id]: event.target.value,
                                                }))}
                                                disabled={proposal.status === 'applied' || proposal.status === 'rejected'}
                                            />
                                        ) : null}
                                    </Stack>
                                ) : (
                                    <Alert severity="info">{t('insight.cleaning.unsupported')}</Alert>
                                )}

                                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                    <Button
                                        variant="outlined"
                                        size="small"
                                        disabled={!supported || busy || proposal.status === 'rejected'}
                                        onClick={() => { void runProposalAction(proposal, 'preview'); }}
                                    >
                                        {t('insight.cleaning.preview')}
                                    </Button>
                                    {proposal.status === 'pending' ? (
                                        <>
                                            <Button
                                                variant="contained"
                                                size="small"
                                                disabled={!supported || busy}
                                                onClick={() => { void runProposalAction(proposal, 'approve'); }}
                                            >
                                                {t('insight.cleaning.approve')}
                                            </Button>
                                            <Button
                                                color="inherit"
                                                size="small"
                                                disabled={busy}
                                                onClick={() => { void runProposalAction(proposal, 'reject'); }}
                                            >
                                                {t('insight.cleaning.reject')}
                                            </Button>
                                        </>
                                    ) : null}
                                    {proposal.status === 'approved' ? (
                                        <Button
                                            color="success"
                                            variant="contained"
                                            size="small"
                                            disabled={!supported || busy}
                                            onClick={() => { void runProposalAction(proposal, 'apply'); }}
                                        >
                                            {t('insight.cleaning.apply')}
                                        </Button>
                                    ) : null}
                                </Stack>

                                {preview ? (
                                    <Box sx={{ bgcolor: 'action.hover', borderRadius: 1, p: 1.5 }}>
                                        <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                            {t('insight.cleaning.previewTitle')}
                                        </Typography>
                                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                            {metricKeys.map((key) => (
                                                <Chip
                                                    key={key}
                                                    size="small"
                                                    variant="outlined"
                                                    label={t('insight.cleaning.metricDelta', {
                                                        metric: t(`insight.cleaning.metrics.${key}`),
                                                        before: preview.operation.before_metrics[key] ?? 0,
                                                        after: preview.operation.after_metrics[key] ?? 0,
                                                        delta: preview.operation.metric_delta[key] ?? 0,
                                                    })}
                                                />
                                            ))}
                                        </Stack>
                                        {preview.warnings.map((warning) => (
                                            <Alert key={warning} severity="warning" sx={{ mt: 1 }}>{warning}</Alert>
                                        ))}
                                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                                            {t('insight.cleaning.affected', {
                                                rows: preview.operation.animation_payload.affected_rows ?? 0,
                                                columns: (preview.operation.animation_payload.affected_columns ?? []).join(', '),
                                            })}
                                        </Typography>
                                    </Box>
                                ) : null}
                                <Divider />
                                <Typography variant="caption" color="text.secondary">
                                    {t('insight.cleaning.recommended', {
                                        operation: t(`insight.cleaning.operations.${proposal.recommended_operation}`, {
                                            defaultValue: proposal.recommended_operation,
                                        }),
                                    })}
                                </Typography>
                            </Stack>
                        </CardContent>
                    </Card>
                );
            })}
        </Stack>
    );
}

export default CleaningWorkspacePanel;
