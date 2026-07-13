import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react-i18next')>();
    return {
        ...actual,
        useTranslation: () => ({
            t: (key: string, params?: Record<string, unknown>) => {
                if (key === 'insight.egress.remoteOff') return 'Remote analysis: off';
                if (key === 'insight.egress.remoteEnabled') {
                    return `Remote receivers: ${params?.recipients}`;
                }
                return key;
            },
        }),
    };
});

import { RemoteServiceStatus } from '../../../../src/insight/components/RemoteServiceStatus';

describe('RemoteServiceStatus', () => {
    it('is hidden in the original Data Formulator mode', () => {
        render(
            <RemoteServiceStatus
                productMode='data_formulator'
                services={[]}
            />,
        );
        expect(screen.queryByText(/Remote analysis/)).not.toBeInTheDocument();
    });

    it('persistently reports the default-off BIA policy', () => {
        render(
            <RemoteServiceStatus
                productMode='business_insight'
                services={[]}
            />,
        );
        expect(screen.getByText('Remote analysis: off')).toBeInTheDocument();
    });

    it('shows every administrator-enabled receiver name and domain', () => {
        render(
            <RemoteServiceStatus
                productMode='business_insight'
                services={[
                    {
                        service_id: 'ragflow',
                        display_name: 'Project knowledge',
                        domain: 'rag.example.com',
                    },
                    {
                        service_id: 'tsfl',
                        display_name: 'Forecast service',
                        domain: 'forecast.example.com',
                    },
                ]}
            />,
        );
        expect(screen.getByText(
            'Remote receivers: Project knowledge (rag.example.com), Forecast service (forecast.example.com)',
        )).toBeInTheDocument();
    });
});
