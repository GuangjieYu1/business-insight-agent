import {
    Alert,
    Box,
    Card,
    CardContent,
    Chip,
    Stack,
    Typography,
} from '@mui/material';
import type { TFunction } from 'i18next';

import type { DatasetProfile, InsightSeverity } from '../types';
import { formatInteger } from './formatters';

const severityOrder: InsightSeverity[] = ['critical', 'high', 'medium', 'low', 'info'];

const severityColorMap: Record<InsightSeverity, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    info: 'info',
    low: 'success',
    medium: 'warning',
    high: 'error',
    critical: 'error',
};

interface MetricCardProps {
    label: string;
    value: string;
    helper?: string;
}

function MetricCard({ label, value, helper }: MetricCardProps) {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                <Typography variant="caption" color="text.secondary">
                    {label}
                </Typography>
                <Typography variant="h5" sx={{ mt: 0.5, fontWeight: 600 }}>
                    {value}
                </Typography>
                {helper ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {helper}
                    </Typography>
                ) : null}
            </CardContent>
        </Card>
    );
}

export interface ProfileOverviewCardsProps {
    profile: DatasetProfile;
    t: TFunction;
}

export function ProfileOverviewCards({ profile, t }: ProfileOverviewCardsProps) {
    const severityCounts = profile.quality_issues.reduce(
        (acc, issue) => {
            acc[issue.severity] = (acc[issue.severity] ?? 0) + 1;
            return acc;
        },
        {
            info: 0,
            low: 0,
            medium: 0,
            high: 0,
            critical: 0,
        } satisfies Record<InsightSeverity, number>,
    );

    return (
        <Stack spacing={2}>
            {(profile.redaction_applied || profile.sensitive_data_detected) && (
                <Alert severity="warning" variant="outlined">
                    {t('insight.profile.privacyAlert')}
                </Alert>
            )}

            <Box
                sx={{
                    display: 'grid',
                    gridTemplateColumns: {
                        xs: '1fr',
                        sm: 'repeat(2, minmax(0, 1fr))',
                        lg: 'repeat(4, minmax(0, 1fr))',
                    },
                    gap: 1.5,
                }}
            >
                <MetricCard
                    label={t('insight.profile.metrics.rows')}
                    value={formatInteger(profile.row_count)}
                />
                <MetricCard
                    label={t('insight.profile.metrics.columns')}
                    value={formatInteger(profile.column_count)}
                />
                <MetricCard
                    label={t('insight.profile.metrics.duplicateRows')}
                    value={formatInteger(profile.duplicate_excess_row_count)}
                    helper={t('insight.profile.metrics.duplicateRowsHelper', {
                        count: formatInteger(profile.duplicate_group_member_count),
                    })}
                />
                <MetricCard
                    label={t('insight.profile.metrics.issueCount')}
                    value={formatInteger(profile.quality_issues.length)}
                    helper={t('insight.profile.versionLabel', { versionId: profile.version_id })}
                />
            </Box>

            <Card variant="outlined">
                <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                    <Stack
                        direction={{ xs: 'column', md: 'row' }}
                        spacing={1.25}
                        justifyContent="space-between"
                        alignItems={{ xs: 'flex-start', md: 'center' }}
                    >
                        <Box>
                            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                {t('insight.profile.severitySummaryTitle')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                                {t('insight.profile.severitySummaryHint')}
                            </Typography>
                        </Box>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                            {severityOrder.map((severity) => (
                                <Chip
                                    key={severity}
                                    color={severityColorMap[severity]}
                                    label={t(`insight.severity.${severity}`, { count: severityCounts[severity] })}
                                    variant={severityCounts[severity] > 0 ? 'filled' : 'outlined'}
                                />
                            ))}
                        </Stack>
                    </Stack>
                </CardContent>
            </Card>
        </Stack>
    );
}
