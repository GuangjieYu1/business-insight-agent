import React from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Box,
    Chip,
    Stack,
    Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import type { TFunction } from 'i18next';

import type { AgentStep } from '../types';

function statusIcon(step: AgentStep) {
    if (step.status === 'completed') return <CheckCircleOutlineIcon color="success" fontSize="small" />;
    if (step.status === 'failed') return <ErrorOutlineIcon color="error" fontSize="small" />;
    if (step.status === 'running') return <HourglassEmptyIcon color="primary" fontSize="small" />;
    return <RadioButtonUncheckedIcon color="disabled" fontSize="small" />;
}

function statusColor(status: AgentStep['status']): 'default' | 'primary' | 'success' | 'error' | 'warning' {
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'error';
    if (status === 'running') return 'primary';
    if (status === 'cancelled') return 'warning';
    return 'default';
}

export interface AgentProgressCardProps {
    step: AgentStep;
    t: TFunction;
}

export function AgentProgressCard({ step, t }: AgentProgressCardProps) {
    const hasDetails = Boolean(
        step.input_refs.length
        || step.output_refs.length
        || Object.keys(step.detail || {}).length,
    );

    return (
        <Accordion
            variant="outlined"
            disableGutters
            defaultExpanded={!step.collapsed_by_default || step.status === 'failed'}
            sx={{
                borderRadius: 1.5,
                '&:before': { display: 'none' },
                '& + &': { mt: 1 },
            }}
        >
            <AccordionSummary
                expandIcon={hasDetails ? <ExpandMoreIcon /> : null}
                aria-controls={`${step.id}-content`}
                id={`${step.id}-header`}
                sx={{ cursor: hasDetails ? 'pointer' : 'default' }}
            >
                <Stack direction="row" spacing={1.25} alignItems="flex-start" sx={{ width: '100%', pr: 1 }}>
                    <Box sx={{ pt: 0.25 }}>{statusIcon(step)}</Box>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {step.title}
                        </Typography>
                        {step.progress_text ? (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                {step.progress_text}
                            </Typography>
                        ) : null}
                    </Box>
                    <Chip
                        size="small"
                        color={statusColor(step.status)}
                        label={t(`insight.run.stepStatus.${step.status}`)}
                        sx={{ height: 22 }}
                    />
                </Stack>
            </AccordionSummary>
            {hasDetails ? (
                <AccordionDetails sx={{ pt: 0 }}>
                    <Stack spacing={1}>
                        {step.input_refs.length ? (
                            <Box>
                                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                                    {t('insight.run.inputs')}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', wordBreak: 'break-all' }}>
                                    {step.input_refs.join(', ')}
                                </Typography>
                            </Box>
                        ) : null}
                        {step.output_refs.length ? (
                            <Box>
                                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                                    {t('insight.run.outputs')}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', wordBreak: 'break-all' }}>
                                    {step.output_refs.join(', ')}
                                </Typography>
                            </Box>
                        ) : null}
                        {Object.keys(step.detail || {}).length ? (
                            <Box>
                                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                                    {t('insight.run.details')}
                                </Typography>
                                <Box
                                    component="pre"
                                    sx={{
                                        m: 0,
                                        mt: 0.5,
                                        p: 1,
                                        borderRadius: 1,
                                        bgcolor: 'action.hover',
                                        color: 'text.secondary',
                                        fontSize: 11,
                                        whiteSpace: 'pre-wrap',
                                        wordBreak: 'break-word',
                                    }}
                                >
                                    {JSON.stringify(step.detail, null, 2)}
                                </Box>
                            </Box>
                        ) : null}
                    </Stack>
                </AccordionDetails>
            ) : null}
        </Accordion>
    );
}
