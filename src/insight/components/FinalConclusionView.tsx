import React from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Divider,
    Stack,
    Typography,
} from '@mui/material';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import type { TFunction } from 'i18next';

import type { AgentRun, FinalSummary } from '../types';

export interface FinalConclusionViewProps {
    run: AgentRun;
    summary: FinalSummary | null;
    t: TFunction;
    onOpenProcess: () => void;
}

function metricLabel(metric: Record<string, unknown>, t: TFunction): string {
    const key = typeof metric.metric === 'string' ? metric.metric : 'metric';
    const value = metric.value ?? metric.after ?? metric.delta ?? '—';
    return `${t(`insight.run.metric.${key}`, { defaultValue: key })}: ${String(value)}`;
}

export function FinalConclusionView({ run, summary, t, onOpenProcess }: FinalConclusionViewProps) {
    const title = summary?.title || t('insight.run.final.titleFallback');
    const executiveSummary = summary?.executive_summary || t('insight.run.final.summaryFallback');

    return (
        <Stack spacing={2}>
            <Card variant="outlined">
                <CardContent>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'flex-start', sm: 'center' }}>
                        <FactCheckOutlinedIcon color="success" />
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" sx={{ fontWeight: 700 }}>
                                {title}
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                                {executiveSummary}
                            </Typography>
                        </Box>
                        <Chip color="success" label={t('insight.run.status.completed')} />
                    </Stack>
                </CardContent>
            </Card>

            {summary?.metric_changes?.length ? (
                <Box>
                    <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700 }}>
                        {t('insight.run.final.metrics')}
                    </Typography>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        {summary.metric_changes.map((metric, index) => (
                            <Chip key={`${String(metric.metric)}-${index}`} variant="outlined" label={metricLabel(metric, t)} />
                        ))}
                    </Stack>
                </Box>
            ) : null}

            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                <Card variant="outlined" sx={{ flex: 1 }}>
                    <CardContent>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                            {t('insight.run.final.limitations')}
                        </Typography>
                        <Stack component="ul" spacing={0.75} sx={{ pl: 2.5, mb: 0 }}>
                            {(summary?.limitations?.length
                                ? summary.limitations
                                : [t('insight.run.final.defaultLimitation')]
                            ).map((item) => (
                                <Typography component="li" variant="body2" color="text.secondary" key={item}>
                                    {item}
                                </Typography>
                            ))}
                        </Stack>
                    </CardContent>
                </Card>
                <Card variant="outlined" sx={{ flex: 1 }}>
                    <CardContent>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                            {t('insight.run.final.nextSteps')}
                        </Typography>
                        <Stack component="ul" spacing={0.75} sx={{ pl: 2.5, mb: 0 }}>
                            {(summary?.next_steps?.length
                                ? summary.next_steps
                                : [t('insight.run.final.defaultNextStep')]
                            ).map((item) => (
                                <Typography component="li" variant="body2" color="text.secondary" key={item}>
                                    {item}
                                </Typography>
                            ))}
                        </Stack>
                    </CardContent>
                </Card>
            </Stack>

            {!summary ? (
                <Alert severity="info" variant="outlined">
                    {t('insight.run.final.skeletonNotice')}
                </Alert>
            ) : null}

            <Divider />
            <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="caption" color="text.secondary">
                    {t('insight.run.final.runReference', { runId: run.id })}
                </Typography>
                <Button startIcon={<HistoryOutlinedIcon />} onClick={onOpenProcess}>
                    {t('insight.run.viewFullProcess')}
                </Button>
            </Stack>
        </Stack>
    );
}
