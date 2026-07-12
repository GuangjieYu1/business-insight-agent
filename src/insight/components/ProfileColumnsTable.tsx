import {
    Box,
    Card,
    CardContent,
    Chip,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
} from '@mui/material';
import type { TFunction } from 'i18next';

import type { DatasetProfile, InsightSeverity } from '../types';
import { formatInteger, formatPercent } from './formatters';

const severityColorMap: Record<InsightSeverity, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    info: 'info',
    low: 'success',
    medium: 'warning',
    high: 'error',
    critical: 'error',
};

const severityRank: Record<InsightSeverity, number> = {
    critical: 5,
    high: 4,
    medium: 3,
    low: 2,
    info: 1,
};

export interface ProfileColumnsTableProps {
    profile: DatasetProfile;
    t: TFunction;
}

export function ProfileColumnsTable({ profile, t }: ProfileColumnsTableProps) {
    const issueSeverityByType = profile.quality_issues.reduce<Record<string, InsightSeverity>>((acc, issue) => {
        const current = acc[issue.issue_type];
        if (!current || severityRank[issue.severity] > severityRank[current]) {
            acc[issue.issue_type] = issue.severity;
        }
        return acc;
    }, {});

    return (
        <Card variant="outlined">
            <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
                <Box sx={{ px: 2.25, pt: 2.25, pb: 1.5 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                        {t('insight.profile.columnsTitle')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {t('insight.profile.columnsHint')}
                    </Typography>
                </Box>
                <TableContainer sx={{ maxHeight: '100%', overflow: 'auto' }}>
                    <Table stickyHeader size="small" aria-label={t('insight.profile.columnsTitle')}>
                        <TableHead>
                            <TableRow>
                                <TableCell>{t('insight.profile.columns.column')}</TableCell>
                                <TableCell>{t('insight.profile.columns.inferredType')}</TableCell>
                                <TableCell>{t('insight.profile.columns.completeness')}</TableCell>
                                <TableCell>{t('insight.profile.columns.distinctness')}</TableCell>
                                <TableCell>{t('insight.profile.columns.parseHealth')}</TableCell>
                                <TableCell>{t('insight.profile.columns.flags')}</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {profile.columns.map((column) => (
                                <TableRow key={column.name} hover>
                                    <TableCell sx={{ minWidth: 180 }}>
                                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                            {column.name}
                                        </Typography>
                                        <Typography variant="caption" color="text.secondary">
                                            {column.pandas_dtype}
                                        </Typography>
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 140 }}>
                                        <Typography variant="body2">
                                            {t(`insight.columnTypes.${column.inferred_type}`)}
                                        </Typography>
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 150 }}>
                                        <Typography variant="body2">
                                            {t('insight.profile.columns.nulls', {
                                                count: formatInteger(column.null_count),
                                                ratio: formatPercent(column.null_ratio),
                                            })}
                                        </Typography>
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 150 }}>
                                        <Typography variant="body2">
                                            {t('insight.profile.columns.distincts', {
                                                count: formatInteger(column.distinct_count),
                                                ratio: formatPercent(column.distinct_ratio),
                                            })}
                                        </Typography>
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 190 }}>
                                        <Stack spacing={0.35}>
                                            <Typography variant="body2">
                                                {t('insight.profile.columns.numericConflicts', {
                                                    count: formatInteger(column.numeric_parse_conflict_count),
                                                })}
                                            </Typography>
                                            <Typography variant="body2">
                                                {t('insight.profile.columns.datetimeConflicts', {
                                                    count: formatInteger(column.datetime_parse_conflict_count),
                                                })}
                                            </Typography>
                                        </Stack>
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 220 }}>
                                        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                                            {column.sensitive_data_detected && (
                                                <Chip
                                                    label={t('insight.profile.columns.sensitive')}
                                                    size="small"
                                                    color="warning"
                                                    variant="outlined"
                                                />
                                            )}
                                            {column.redaction_applied && (
                                                <Chip
                                                    label={t('insight.profile.columns.redacted')}
                                                    size="small"
                                                    color="warning"
                                                    variant="outlined"
                                                />
                                            )}
                                            {column.quality_issue_types.map((issueType) => (
                                                <Chip
                                                    key={`${column.name}-${issueType}`}
                                                    label={t(`insight.issueTypes.${issueType}`)}
                                                    size="small"
                                                    color={severityColorMap[issueSeverityByType[issueType] ?? 'info']}
                                                    variant="outlined"
                                                />
                                            ))}
                                            {column.quality_issue_types.length === 0 && !column.sensitive_data_detected && !column.redaction_applied && (
                                                <Typography variant="body2" color="text.secondary">
                                                    {t('insight.profile.columns.noFlags')}
                                                </Typography>
                                            )}
                                        </Stack>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            </CardContent>
        </Card>
    );
}
