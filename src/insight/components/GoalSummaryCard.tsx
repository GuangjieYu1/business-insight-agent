import React from 'react';
import {
    Button,
    Card,
    CardContent,
    Chip,
    Stack,
    Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import SettingsSuggestOutlinedIcon from '@mui/icons-material/SettingsSuggestOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import type { TFunction } from 'i18next';

import type { AnalysisGoal } from '../types';

function joinValues(values: string[]): string {
    return values.length ? values.join(', ') : '-';
}

function formatFilters(goal: AnalysisGoal): string {
    if (!goal.filters.length) return '-';
    return goal.filters
        .map((goalFilter) => {
            const suffix = goalFilter.value == null ? '' : ` ${String(goalFilter.value)}`;
            return `${goalFilter.column} ${goalFilter.operator}${suffix}`;
        })
        .join(', ');
}

export interface GoalSummaryCardProps {
    goal: AnalysisGoal;
    versionId: string;
    startDisabled: boolean;
    starting: boolean;
    t: TFunction;
    onStart: () => void;
    onChangeGoal: () => void;
    onNewCustomGoal: () => void;
}

export function GoalSummaryCard({
    goal,
    versionId,
    startDisabled,
    starting,
    t,
    onStart,
    onChangeGoal,
    onNewCustomGoal,
}: GoalSummaryCardProps) {
    return (
        <Card variant="outlined">
            <CardContent>
                <Stack spacing={1.5}>
                    <Stack
                        direction={{ xs: 'column', sm: 'row' }}
                        spacing={1}
                        justifyContent="space-between"
                        alignItems={{ xs: 'flex-start', sm: 'center' }}
                    >
                        <Stack spacing={0.5}>
                            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                                {goal.title}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('insight.goal.summaryBody')}
                            </Typography>
                        </Stack>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                            <Chip size="small" label={t(`insight.goal.types.${goal.goal_type}`)} />
                            <Chip size="small" variant="outlined" label={t('insight.profile.versionLabel', { versionId })} />
                        </Stack>
                    </Stack>
                    <Stack spacing={0.75}>
                        <Typography variant="body2">
                            <strong>{t('insight.goal.fields.targetMetric')}:</strong> {goal.target_metric || goal.target_column || '-'}
                        </Typography>
                        <Typography variant="body2">
                            <strong>{t('insight.goal.fields.timeColumn')}:</strong> {goal.time_column || '-'}
                        </Typography>
                        <Typography variant="body2">
                            <strong>{t('insight.goal.fields.dimensions')}:</strong> {joinValues(goal.dimensions)}
                        </Typography>
                        <Typography variant="body2">
                            <strong>{t('insight.goal.fields.filters')}:</strong> {formatFilters(goal)}
                        </Typography>
                    </Stack>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                        <Button
                            variant="contained"
                            startIcon={<PlayArrowIcon />}
                            disabled={startDisabled}
                            onClick={onStart}
                        >
                            {starting ? t('insight.goal.starting') : t('insight.goal.startWithGoal')}
                        </Button>
                        <Button variant="outlined" startIcon={<SettingsSuggestOutlinedIcon />} onClick={onChangeGoal}>
                            {t('insight.goal.changeGoal')}
                        </Button>
                        <Button variant="text" startIcon={<TuneOutlinedIcon />} onClick={onNewCustomGoal}>
                            {t('insight.goal.newCustomGoal')}
                        </Button>
                    </Stack>
                </Stack>
            </CardContent>
        </Card>
    );
}