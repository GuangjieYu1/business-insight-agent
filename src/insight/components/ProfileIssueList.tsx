import {
    Box,
    Card,
    CardContent,
    Chip,
    Divider,
    Stack,
    Typography,
} from '@mui/material';
import type { TFunction } from 'i18next';

import type { DatasetProfile, InsightSeverity, ProfileQualityIssue } from '../types';
import { formatMetricLabel, formatMetricValue } from './formatters';

const severityColorMap: Record<InsightSeverity, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    info: 'info',
    low: 'success',
    medium: 'warning',
    high: 'error',
    critical: 'error',
};

interface IssueDetailRowsProps {
    title: string;
    detail: Record<string, unknown>;
}

function IssueDetailRows({ title, detail }: IssueDetailRowsProps) {
    const entries = Object.entries(detail).filter(([, value]) => value !== undefined && value !== null && value !== '');
    if (entries.length === 0) {
        return null;
    }

    return (
        <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                {title}
            </Typography>
            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                {entries.map(([key, value]) => (
                    <Chip
                        key={`${title}-${key}`}
                        label={`${formatMetricLabel(key)}: ${formatMetricValue(value)}`}
                        size="small"
                        variant="outlined"
                    />
                ))}
            </Stack>
        </Box>
    );
}

function IssueCard({ issue, t }: { issue: ProfileQualityIssue; t: TFunction }) {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                <Stack spacing={1.25}>
                    <Stack
                        direction={{ xs: 'column', sm: 'row' }}
                        spacing={1}
                        justifyContent="space-between"
                        alignItems={{ xs: 'flex-start', sm: 'center' }}
                    >
                        <Box>
                            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                {t(`insight.issueTypes.${issue.issue_type}`)}
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
                                {issue.message}
                            </Typography>
                        </Box>
                        <Chip
                            color={severityColorMap[issue.severity]}
                            label={t(`insight.severity.label.${issue.severity}`)}
                            size="small"
                        />
                    </Stack>
                    <IssueDetailRows title={t('insight.profile.issueScope')} detail={issue.scope} />
                    <IssueDetailRows title={t('insight.profile.issueMetrics')} detail={issue.metrics} />
                </Stack>
            </CardContent>
        </Card>
    );
}

export interface ProfileIssueListProps {
    profile: DatasetProfile;
    t: TFunction;
}

export function ProfileIssueList({ profile, t }: ProfileIssueListProps) {
    if (profile.quality_issues.length === 0) {
        return (
            <Card variant="outlined">
                <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                        {t('insight.profile.noIssuesTitle')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {t('insight.profile.noIssuesBody')}
                    </Typography>
                </CardContent>
            </Card>
        );
    }

    return (
        <Stack spacing={1.5}>
            <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    {t('insight.profile.issuesTitle')}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    {t('insight.profile.issuesHint')}
                </Typography>
            </Box>
            <Divider />
            <Box
                sx={{
                    display: 'grid',
                    gridTemplateColumns: {
                        xs: '1fr',
                        lg: 'repeat(2, minmax(0, 1fr))',
                    },
                    gap: 1.5,
                }}
            >
                {profile.quality_issues.map((issue, index) => (
                    <IssueCard key={`${issue.issue_type}-${index}`} issue={issue} t={t} />
                ))}
            </Box>
        </Stack>
    );
}
