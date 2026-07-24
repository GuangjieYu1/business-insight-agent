import React from 'react';
import {
    Box,
    Divider,
    Drawer,
    IconButton,
    Stack,
    Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { TFunction } from 'i18next';

import type { AgentRun, AgentStep } from '../types';
import { AgentProgressCard } from './AgentProgressCard';

export interface ProcessDrawerProps {
    open: boolean;
    run: AgentRun | null;
    steps: AgentStep[];
    t: TFunction;
    onClose: () => void;
}

export function ProcessDrawer({ open, run, steps, t, onClose }: ProcessDrawerProps) {
    return (
        <Drawer
            anchor="right"
            open={open}
            onClose={onClose}
            PaperProps={{ sx: { width: { xs: '100%', sm: 480 }, maxWidth: '100%' } }}
        >
            <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2, py: 1.5 }}>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>
                            {t('insight.run.processDrawer.title')}
                        </Typography>
                        {run ? (
                            <Typography variant="caption" color="text.secondary" noWrap>
                                {t('insight.run.processDrawer.subtitle', { runId: run.id })}
                            </Typography>
                        ) : null}
                    </Box>
                    <IconButton aria-label={t('insight.run.processDrawer.close')} onClick={onClose}>
                        <CloseIcon />
                    </IconButton>
                </Stack>
                <Divider />
                <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
                    {steps.length ? (
                        steps.map((step) => <AgentProgressCard key={step.id} step={step} t={t} />)
                    ) : (
                        <Typography variant="body2" color="text.secondary">
                            {t('insight.run.processDrawer.empty')}
                        </Typography>
                    )}
                </Box>
            </Box>
        </Drawer>
    );
}
