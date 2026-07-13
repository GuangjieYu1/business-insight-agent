import React from 'react';
import { Chip, Tooltip } from '@mui/material';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import { useTranslation } from 'react-i18next';

import type { ServerConfig } from '../../app/dfSlice';

export interface RemoteServiceStatusProps {
    productMode: ServerConfig['APP_PRODUCT_MODE'];
    services: ServerConfig['REMOTE_ANALYSIS_SERVICES'];
}

export function RemoteServiceStatus({
    productMode,
    services,
}: RemoteServiceStatusProps) {
    const { t } = useTranslation();
    if (productMode !== 'business_insight') return null;

    const recipients = services
        .map((service) => `${service.display_name} (${service.domain})`)
        .join(', ');
    const label = recipients
        ? t('insight.egress.remoteEnabled', { recipients })
        : t('insight.egress.remoteOff');

    return (
        <Tooltip title={label}>
            <Chip
                icon={<ShieldOutlinedIcon />}
                size='small'
                variant='outlined'
                label={label}
                sx={{
                    mr: 0.75,
                    maxWidth: 330,
                    '& .MuiChip-label': {
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                    },
                }}
            />
        </Tooltip>
    );
}
